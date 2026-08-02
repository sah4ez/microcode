---
name: git-sync
description: >-
  Bidirectional sync between this VM and the host via a shared remote git server
  plus a local git-daemon. Use when the workspace must mirror the remote codebase
  (PRD, skills, source) and expose loki's work back to the host. Covers cloning
  the remote into /workspace before loki starts (so loki reuses shared history
  instead of a disconnected `git init`), the vm/<sandbox> branch model, starting
  the read-only git-daemon on :9418, and the checkpoint cycle. Load this module
  BEFORE the first git operation in the VM and whenever syncing work to/from host.
---

# git-sync — VM↔host synchronization via shared remote + local git-daemon

## When

**Always, before the first commit and whenever you need to pull fresh code from
the remote or expose your work to the host.** This module defines the ONLY
correct way files move between the VM, the shared remote, and the host.

## Topology (the source of truth for all sync decisions)

```
                 ┌─────────────────────┐
                 │  Remote git server  │  ◄── codebase (PRD, skills, src)
                 │ (github private /   │      source of truth. HOST pushes here.
                 │  internal SSH)      │
                 └──────────┬──────────┘
                            │ pull ONLY (this VM pulls code, never pushes)
                            ▼
                 ┌─────────────────────┐    git-daemon :9418 (read-only for host)
                 │      THIS VM        │──────────┐
                 │  /workspace (loki)  │          │ host PULLS loki's result
                 │  branch vm/<name>   │          ▼
                 └─────────────────────┘    ┌──────────┐
                                          │   HOST   │
                                          │ push→remote (edits)
                                          │ pull←remote (base)
                                          │ pull←VM:9418 (loki result)
                                          └──────────┘
```

**Data flow rules (memorize these):**
1. The host pushes its edits (PRD, skills, source) to the **remote** — that is
   the ONLY place the host writes.
2. This VM **pulls** the codebase from the **remote**. The VM is a **read-only
   consumer of the remote** — it NEVER pushes to the remote.
3. Loki commits its work on the local `vm/<sandbox-name>` branch in `/workspace`.
4. A read-only **git-daemon on :9418** exposes the local repo (including
   `vm/<name>`) to the host through the msb port-forward.
5. The host **pulls** loki's result from `git://localhost:9418/` (the VM daemon).

## Branching strategy

Two branches matter; everything else is a mistake:

- **`main`** — mirrors the remote's base branch (`main`/`master`, see
  `$SYNC_BRANCH`). Read-only inside the VM: `git fetch origin` updates it, but
  **never commit on `main`** in the VM. The host merges work down to `main`.
- **`vm/<sandbox-name>`** — THIS VM's working branch. All loki commits land here.
  The name is derived from the sandbox name (`$SANDBOX_NAME`, e.g.
  `vm/notes-build`), so each VM gets a unique branch — this is the multi-VM
  seam. The host fetches `vm/<name>` and merges selectively.

This is single-VM today, but the `vm/<name>` naming means a second VM
(`vm/other-build`) can coexist on the same remote without colliding.

## Configuration (provided by the host via env, never hardcoded)

The host injects these through `msb exec -e` (resolved host-side from the host
environment, so secrets never appear in the manifest):

| env var             | meaning                                              | example                          |
|---------------------|------------------------------------------------------|----------------------------------|
| `$SYNC_REMOTE_URL`  | remote URL (`https://` or `ssh://`)                  | `https://github.com/o/repo.git`  |
| `$SYNC_REMOTE_TOKEN`| HTTPS PAT (HTTPS mode only; empty for SSH)           | `ghp_…`                          |
| `$SYNC_SSH_KEY`     | path to SSH private key (SSH mode only; empty otherwise) | `/home/loki/.ssh/id_ed25519` |
| `$SYNC_BRANCH`      | base branch on the remote                            | `main`                           |
| `$SANDBOX_NAME`     | this VM's sandbox name → `vm/<this>` branch          | `notes-build`                    |

If `$SYNC_REMOTE_URL` is empty/unset, git-sync is disabled — fall back to the
seeded workspace and loki's default local repo. Do NOT invent a remote.

## Procedure

### Step 1 — Clone the remote into /workspace (shared history)

Do this ONCE, before loki's first commit. It replaces the seeded workspace's
disconnected `.git` with the remote's shared history so loki reuses it (loki
skips `git init` when `/workspace` is already a repo).

```bash
cd /workspace
# Clone into a temp dir, then move only .git + reconcile the working tree.
# (Cloning directly into /workspace would fail — it is already populated by
# the seed.) --depth 1 keeps it fast; loki does not need full history.
case "$SYNC_REMOTE_URL" in
  https://*)
    git clone --depth 1 --branch "$SYNC_BRANCH" \
      "${SYNC_REMOTE_URL#https://}https://${SYNC_REMOTE_TOKEN}@${SYNC_REMOTE_URL#https://}" \
      /tmp/ws-clone 2>/dev/null \
      || git clone --depth 1 --branch "$SYNC_BRANCH" "$SYNC_REMOTE_URL" /tmp/ws-clone
    ;;
  ssh://*|git@*)
    export GIT_SSH_COMMAND="ssh -i ${SYNC_SSH_KEY:-$HOME/.ssh/id_ed25519} -o StrictHostKeyChecking=accept-new"
    git clone --depth 1 --branch "$SYNC_BRANCH" "$SYNC_REMOTE_URL" /tmp/ws-clone
    ;;
esac
# Adopt the remote's history without clobbering working files already seeded:
rm -rf /workspace/.git
cp -a /tmp/ws-clone/.git /workspace/.git
git -C /workspace reset --mixed HEAD      # index ← remote HEAD, working tree kept
git -C /workspace remote set-url origin "$SYNC_REMOTE_URL"
rm -rf /tmp/ws-clone
```

If the clone fails (network/auth), STOP and report — do NOT fall back to
`git init`, that creates a disconnected history the host can never merge.

### Step 2 — Create / switch to the vm/<sandbox> branch

```bash
cd /workspace
VM_BRANCH="vm/${SANDBOX_NAME:-unknown}"
git checkout -b "$VM_BRANCH" "$SYNC_BRANCH" 2>/dev/null || git checkout "$VM_BRANCH"
# loki's identity for checkpoint commits (host may override later):
git config user.name  "${GIT_AUTHOR_NAME:-Loki}"
git config user.email "${GIT_AUTHOR_EMAIL:-loki@local}"
echo "$VM_BRANCH" > /workspace/.loki/state/sync-branch.txt
```

All subsequent loki commits (the `**Always commit**` checkpoint cycle) now land
on `vm/<sandbox-name>` automatically.

### Step 3 — The git-daemon is already running (started by bootstrap)

Bootstrap starts a read-only daemon exposing `/workspace` on `0.0.0.0:9418`:

```bash
git daemon --reuseaddr --base-path=/workspace --export-all \
           --listen=0.0.0.0 --port=9418 >/tmp/git-daemon.log 2>&1 &
```

Verify it is alive (do this at the top of any sync-related task):

```bash
pgrep -f "git daemon" >/dev/null && echo "daemon up" \
  || { git daemon --reuseaddr --base-path=/workspace --export-all \
                    --listen=0.0.0.0 --port=9418 >/tmp/git-daemon.log 2>&1 & echo "daemon (re)started"; }
git ls-remote git://127.0.0.1:9418/ HEAD >/dev/null 2>&1 && echo "daemon serves" || echo "daemon broken"
```

`--export-all` is required: without it the daemon refuses to serve a repo
lacking `git-daemon-export-ok`. `0.0.0.0` (NOT `127.0.0.1`) is required so the
host reaches it through the msb port-forward on `eth0`.

### Step 4 — Pull fresh code from the remote (when host pushed updates)

Only when the working tree is clean (before starting a new task, never mid-work):

```bash
cd /workspace
VM_BRANCH="$(cat /workspace/.loki/state/sync-branch.txt 2>/dev/null || echo vm/${SANDBOX_NAME:-unknown})"
git fetch origin "$SYNC_BRANCH"
# Replay this VM's work on top of the updated base (keeps history linear):
git rebase "origin/$SYNC_BRANCH"
```

If the rebase hits conflicts, STOP and report — do NOT resolve blindly and do
NOT force anything. Conflicts mean the host and the VM edited the same lines;
a human (the host operator) must decide.

### Step 5 — Checkpoint commit (loki's normal cycle, now on vm/<name>)

This is unchanged from loki's `**Always commit**` rule — just ensure you are on
`vm/<sandbox-name>` first:

```bash
cd /workspace
git add -A
git commit -m "CHECKPOINT: <what changed>"   # atomic, after each task
```

### Step 6 — Host pulls loki's result (this is a HOST action, documented here)

The host runs this OUTSIDE the VM; it is listed so you know how your work
leaves the VM and can verify it is reachable:

```bash
# On the host:
git fetch git://localhost:9418/ vm/notes-build
git log FETCH_HEAD --oneline -5      # inspect loki's commits
git merge FETCH_HEAD                 # or cherry-pick selectively
```

## Verification gate

Before declaring sync "done" or handing off to the host — **all must pass**:
- `git -C /workspace rev-parse --abbrev-ref HEAD` prints `vm/<sandbox-name>`
  (you are on the correct branch, NOT `main` and NOT `loki/session-*`).
- `git -C /workspace status --porcelain` is empty (clean tree after a commit).
- `git -C /workspace log --oneline -3` shows checkpoint commits on `vm/<name>`.
- `git ls-remote git://127.0.0.1:9418/ vm/<sandbox-name>` returns a SHA (the
  host can see this branch through the daemon).
- `/workspace/.loki/state/sync-branch.txt` exists and matches the current branch.

## Never

- **Push to the remote from the VM.** The VM is a read-only consumer of the
  remote; only the host writes there. Pushing from the VM creates a divergent
  history the host's workflow does not expect.
- **Commit on `main` inside the VM.** All VM work goes on `vm/<sandbox-name>`.
  `main` mirrors the remote base branch and is updated only by `git fetch`.
- **Run `git init` in /workspace.** If `/workspace` is not already a repo, run
  Step 1 (clone) — `git init` produces a disconnected history the host can never
  merge (`fatal: refusing to merge unrelated histories`).
- **Bind the git-daemon to `127.0.0.1`.** The host reaches the VM via the msb
  port-forward on `eth0`; a loopback bind makes the daemon look started but
  every host `git fetch` hangs/empties. Always `--listen=0.0.0.0`.
- **Serve the daemon without `--export-all`.** Without it the daemon silently
  refuses the repo (no `git-daemon-export-ok` marker) and the host sees
  "access denied".
- **Force-push or `reset --hard` to rewrite published `vm/<name>` history.**
  Once the host has fetched the branch, rewriting it breaks the host's local
  refs. If you must reorganize, do it before the host fetches.
- **Rebase onto `origin/main` while the working tree is dirty.** Conflicts
  mid-task corrupt the checkpoint. Fetch+rebase only at a clean-tree boundary
  (before starting a new task).
- **Hardcode the remote URL or token in a committed file.** Read them from
  `$SYNC_REMOTE_URL` / `$SYNC_REMOTE_TOKEN` (host-injected env). A token in a
  committed file is a leaked credential.
