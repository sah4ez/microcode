# Host↔VM git-daemon sync

When you need LIVE bidirectional sync between the host and a microsandbox VM
(the default `msb cp` seeding is one-shot and doesn't reflect mid-session edits),
run a read-only git daemon inside the VM and fetch from it over the forwarded
port.

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

Rules:
1. Host pushes edits to the **remote** (the only place the host writes).
2. VM **pulls** the codebase from the remote (read-only; never pushes).
3. Loki commits on `vm/<sandbox-name>` inside `/workspace`.
4. A read-only **git-daemon on :9418** exposes the repo to the host.
5. Host **pulls** loki's result from `git://localhost:9418/`.

## Why this works with loki

loki normally does a fresh `git init` in `/workspace`, producing a disconnected
local repo the host can never merge (`fatal: refusing to merge unrelated
histories`). But loki **skips `git init` when `/workspace` is already a repo**.
So cloning the remote into `/workspace` before loki starts means loki reuses
that shared history and commits on top — the host can fetch+merge normally.

## Branch model

| branch          | owner        | purpose                                         |
|-----------------|--------------|-------------------------------------------------|
| `main`          | host (remote)| base branch; VM only fetches, never commits.    |
| `vm/<sandbox>`  | VM (loki)    | this VM's work; unique per sandbox → multi-VM safe. |

## Manifest setup

```yaml
sandbox:
  ports:
    - "8000:8000"
    - "9418:9418"                    # git-daemon (read-only for host)
  env:
    SYNC_REMOTE_URL: "${SYNC_REMOTE_URL}"     # resolved host-side, never inlined
    SYNC_REMOTE_TOKEN: "${SYNC_REMOTE_TOKEN}" # HTTPS PAT (empty for ssh://)
    SYNC_SSH_KEY: "${SYNC_SSH_KEY}"           # ssh:// key path (empty for https)
    SYNC_BRANCH: "${SYNC_BRANCH}"             # base branch (main)
    SANDBOX_NAME: "${SANDBOX_NAME}"
```

The git-daemon start (in `extra_shell`, runs as loki which owns /workspace):

```bash
runuser -u loki -- bash -c '
  cd /workspace 2>/dev/null || exit 0
  nohup git daemon --reuseaddr --base-path=/workspace --export-all \
           --listen=0.0.0.0 --port=9418 >/tmp/git-daemon.log 2>&1 &
' || true
```

Flags that matter:
- `--export-all` — REQUIRED; without it the daemon refuses a repo lacking
  `git-daemon-export-ok` (host sees "access denied").
- `--listen=0.0.0.0` — REQUIRED; msb port-forward reaches the VM on eth0, not
  loopback. A 127.0.0.1 bind makes the daemon look up but host fetch hangs.
- `--base-path=/workspace` — serve repos under /workspace by relative path.

## Host setup (export before apply)

```bash
# HTTPS (private GitHub):
export SYNC_REMOTE_URL=https://github.com/<org>/<repo>.git
export SYNC_REMOTE_TOKEN=ghp_xxx           # PAT with read access
export SYNC_BRANCH=main

# OR internal SSH server (also allowlist its host:port in network):
export SYNC_REMOTE_URL=ssh://git@git.internal:2222/repo.git
export SYNC_SSH_KEY=/path/to/id_ed25519
export SYNC_BRANCH=main
```

Leave `SYNC_REMOTE_URL` empty to disable sync (loki uses its local repo).

## Pulling loki's result onto the host

```bash
# The VM's git-daemon is forwarded to host localhost:9418.
git fetch git://localhost:9418/ vm/<sandbox-name>
git log FETCH_HEAD --oneline          # inspect what loki did
git merge FETCH_HEAD                  # or cherry-pick specific commits
```

No `msb cp`, no tar — pure git, with real history.

## If the daemon isn't serving (debug)

1. Is `/workspace` a git repo yet? The daemon refuses a non-repo path. Init or
   clone first: `git -C /workspace rev-parse --git-dir`.
2. Is the daemon alive? `/proc` scan for `git-daemon` (pgrep may be missing).
3. Restart as loki (owner of /workspace) with `--export-all --listen=0.0.0.0`.
4. From the host: `git ls-remote git://localhost:9418/` should list refs.

## Never

- Push to the remote from the VM — the VM is read-only consumer of the remote.
- Commit on `main` inside the VM — all work goes on `vm/<sandbox-name>`.
- Run `git init` in /workspace if a remote is configured — clone instead (init
  creates disconnected history the host can't merge).
- Bind the daemon to 127.0.0.1 — host fetch will hang.
- Drop `--export-all` — host sees "access denied".
- Hardcode the remote URL or token in a committed file — read from `$SYNC_*` env.
