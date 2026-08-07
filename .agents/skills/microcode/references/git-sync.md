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

## Manifest setup (structured sandbox.sync)

microcode clones the remote for you when `sandbox.sync` is enabled — no manual
clone step. The `./src` mount for `sync.dest` is suppressed automatically.

```yaml
sandbox:
  ports:
    - "8000:8000"
    - "9418:9418"                    # git-daemon (read-only for host)
  sync:
    enabled: true
    remote_url: https://github.com/<org>/<repo>.git
    branch: main
    dest: /workspace
    auth:
      method: https                 # or "ssh"
      token_env: GH_TOKEN           # https: host env var with PAT
      # ssh_key_env: SYNC_SSH_KEY   # ssh: host env var with key PATH
    depth: 1                        # shallow clone (0 = full history)
```

The git host is **auto-allowlisted** for egress (tcp/443 for https, tcp/22 or
the URL port for ssh) — no manual `network.allow` entry needed.

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

## Host setup (export the credential env vars before apply)

The manifest references credentials by env-var NAME (`token_env` / `ssh_key_env`);
export the actual values on the host before `microcode apply`/`build`:

```bash
# HTTPS (private GitHub) — matches auth.token_env: GH_TOKEN:
export GH_TOKEN=ghp_xxx             # PAT with read access

# OR internal SSH server — matches auth.ssh_key_env: SYNC_SSH_KEY:
export SYNC_SSH_KEY=/path/to/id_ed25519
```

Leave `sync.enabled: false` (the default) to disable sync entirely — the VM
uses the bind mount (build) / tar-seed (apply) as before.

## Pulling loki's result onto the host

The preferred way is the `microcode sync` command — it bundles the VM's
commits (`origin/{branch}..HEAD`) via `git bundle`, copies the bundle to the
host with `msb cp`, fetches it, and cherry-picks the commits onto the current
host branch (or merges with `-s merge`):

```bash
microcode sync platform.yaml                 # cherry-pick (linear history)
microcode sync platform.yaml -s merge        # merge commit instead
microcode sync platform.yaml --dry-run       # preview the commands
```

This requires `sandbox.sync.enabled` (the VM workspace was git-cloned, not
tar-seeded). It runs fully locally (no daemon needed), so it works even when
the git-daemon isn't serving.

If you need to inspect what loki did before applying, the bundle + fetch can be
done manually:

```bash
msb exec <name> --user loki -- bash -c \
  'cd /workspace && git bundle create /tmp/vm.bundle origin/master..HEAD'
msb cp <name>:/tmp/vm.bundle /tmp/vm.bundle
git fetch /tmp/vm.bundle 'HEAD:refs/heads/from-vm/sync'
git log from-vm/sync --oneline              # inspect before applying
git cherry-pick $(git merge-base HEAD from-vm/sync)..from-vm/sync
```

No `msb cp`, no tar — pure git, with real history.

## If the daemon isn't serving (debug)

`microcode sync` does NOT need the daemon (it uses `git bundle` + `msb cp`).
This section is only for the alternative `git fetch git://localhost:9418/`
flow.

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
