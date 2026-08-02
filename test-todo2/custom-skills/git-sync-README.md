# git-sync — branching & sync strategy (human reference)

This document is the human-facing reference for the VM↔host git synchronization
described in `git-sync.md` (the loki-facing skill). Read this to understand the
topology, branch model, and how to pull loki's work onto the host.

## Topology

```
                 ┌─────────────────────┐
                 │  Remote git server  │  ◄── codebase (PRD, skills, src)
                 │ (github private /   │      source of truth. HOST pushes here.
                 │  internal SSH)      │
                 └──────────┬──────────┘
                            │ pull ONLY (VM pulls code, never pushes)
                            ▼
                 ┌─────────────────────┐    git-daemon :9418 (read-only for host)
                 │         VM          │──────────┐
                 │  /workspace (loki)  │          │ host PULLS loki's result
                 │  branch vm/<name>   │          ▼
                 └─────────────────────┘    ┌──────────┐
                                          │   HOST   │
                                          │ push→remote (edits)
                                          │ pull←remote (base)
                                          │ pull←VM:9418 (loki result)
                                          └──────────┘
```

**Rules:**
1. Host pushes edits (PRD, skills, source) to the **remote** — the only place
   the host writes.
2. VM **pulls** the codebase from the remote (read-only consumer; never pushes).
3. Loki commits on `vm/<sandbox-name>` inside `/workspace`.
4. A read-only **git-daemon on :9418** exposes the local repo to the host.
5. Host **pulls** loki's result from `git://localhost:9418/`.

## Branch model

| branch            | owner        | purpose                                         |
|-------------------|--------------|-------------------------------------------------|
| `main`            | host (remote)| base branch; VM only fetches it, never commits. |
| `vm/<sandbox>`    | VM (loki)    | this VM's work; unique per sandbox → multi-VM safe. |

Single-VM today. When a second VM joins (`vm/other-build`), the host merges the
`vm/*` branches it wants — they never collide because of the per-sandbox name.

## Why this works with loki

Loki normally does a fresh `git init` in `/workspace`, producing a disconnected
local repo the host can never merge (`fatal: refusing to merge unrelated
histories`). But loki **skips `git init` when `/workspace` is already a repo**
(`loki-mode run.sh: maybe_git_init_engine_workspace` guard). So the git-sync
skill **clones the remote into `/workspace` before loki starts** — loki then
reuses that shared history and commits on top of it. No loki fork needed.

## Host setup

Export these on the host before `microcode apply` (they are passed to the VM via
`msb -e`, resolved host-side — secrets never appear in the manifest):

```bash
# HTTPS (private GitHub):
export SYNC_REMOTE_URL=https://github.com/<org>/<repo>.git
export SYNC_REMOTE_TOKEN=ghp_xxx           # PAT with read access
export SYNC_BRANCH=main

# OR internal SSH server (also allowlist its host:port in build.yaml network):
export SYNC_REMOTE_URL=ssh://git@git.internal:2222/repo.git
export SYNC_SSH_KEY=/path/to/id_ed25519
export SYNC_BRANCH=main
```

Leave `SYNC_REMOTE_URL` empty to disable sync (loki uses its local repo).

## Pulling loki's work onto the host

```bash
# The VM's git-daemon is port-forwarded to host localhost:9418.
git fetch git://localhost:9418/ vm/notes-build
git log FETCH_HEAD --oneline          # inspect what loki did
git merge FETCH_HEAD                  # or cherry-pick specific commits
```

No `msb cp`, no tar — pure git, with real history.

## Pushing host edits to the VM

```bash
# On the host: push to the remote (the VM pulls from there).
git add -A && git commit -m "edit PRD" && git push origin main
# The VM's next `git fetch origin && git rebase origin/main` picks it up.
```

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| host `git fetch git://localhost:9418/` hangs | daemon bound to 127.0.0.1 | restart with `--listen=0.0.0.0` |
| daemon "access denied" / serves nothing | missing `--export-all` | restart with `--export-all` |
| host fetch says "unrelated histories" | VM ran `git init` instead of clone | re-run the clone step (Step 1) |
| rebase conflicts in VM | host and VM edited same lines | human resolves; VM never force-pushes |
