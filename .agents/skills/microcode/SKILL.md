---
name: microcode
description: >-
  Drive the microcode IaC platform end-to-end: author/validate a platform.yaml
  manifest, run microcode apply/build/steer/status/rollback, and operate the
  microsandbox (msb) VM it provisions. Use whenever the user mentions microcode,
  platform.yaml, microcode apply/build/steer, msb exec/cp/snapshot, loki-mode
  builds inside a VM, or needs to sync code between a host and a microsandbox VM.
  Covers the snapshot-from-image workflow, the named-volume seeding workaround
  (msb can't bind-mount with --from-snapshot), host↔VM git-daemon sync, port
  forwarding, secrets via env, and the common failure modes (loki stuck in
  BUILDING, disk full, go.sum mismatches, 0.0.0.0 bind requirement).
---

# microcode — IaC platform for spec-driven VM builds

microcode binds three systems through one `platform.yaml` manifest:
**skillkit** (skill delivery) + **loki-mode** (spec-driven RARV build loop) +
**microsandbox/msb** (isolated microVM). One CLI provisions skills, boots a VM,
and starts loki to implement a PRD — no manual `msb` calls.

## When to use this skill

- Authoring or fixing a `platform.yaml` / `build.yaml` manifest.
- Running `microcode apply`/`build`/`steer`/`status`/`rollback`/`destroy`.
- Debugging a build stuck in a phase, a VM that won't boot, port-forward issues,
  or host↔VM file sync.
- Provisioning tools (Go, tg, npm packages) into the VM via `extra_shell`.

## The apply pipeline (what `microcode apply` does, in order)

`doctor → plan → write artifacts → boot VM (create OR from_snapshot) →
seed named volumes → skillkit install → loki start`. You normally do NOT call
`msb` yourself — the orchestrator does. Understand the steps to debug them.

## Core commands

| command | purpose |
|---|---|
| `microcode doctor` | verify msb + skillkit on PATH |
| `microcode validate [file]` | pydantic + JSON schema validation |
| `microcode plan [file]` | print the plan + bootstrap.sh preview (dry) |
| `microcode apply [file] --prd src/PRD.md` | provision + boot VM + start loki |
| `microcode build [file]` | run bootstrap once, capture a snapshot |
| `microcode steer [file] "msg"` | async directive into a RUNNING loki |
| `microcode status [file]` | phase / commits / workspace in the VM |
| `microcode rollback [file] --to HASH` | reset the VM workspace to a checkpoint |
| `microcode destroy [file]` | stop VM + clean state |

Always `validate` then `plan --dry-run` before `apply`. The plan preview catches
manifest errors before a slow boot.

## The build→apply workflow (do this for speed)

Bootstrap (apt installs, Go toolchain, npm, skillkit) is slow (~20-30 min).
**Build once, apply many:**

```bash
# 1) ONE-TIME: in build.yaml set snapshot.enabled: true (comment from_snapshot)
microcode build build.yaml        # runs bootstrap, captures snapshot mcd-base

# 2) Flip build.yaml: from_snapshot: mcd-base (comment enabled)
microcode apply build.yaml --prd src/PRD.md   # boots from snapshot (seconds)
```

## The #1 gotcha: --from-snapshot CANNOT bind-mount host paths

`msb run --from-snapshot` rejects host-path bind mounts — `mount: Not a directory`
/ `patches cannot be combined with from_snapshot` (msb 0.6.8). So when booting
from a snapshot, every `mounts:` entry becomes a **named volume** that is seeded
from the host dir via `msb cp` (tarball) after boot.

Consequences you WILL hit:
- **Named volumes do not sync live with the host.** Edits in the VM stay in the
  volume; host edits appear only on the next seed (next `apply`). For live sync
  see *Host↔VM sync* below.
- **`msb cp <dir> vm:/dest` ALWAYS nests the dir** inside /dest (→ `/workspace/src`
  instead of `/workspace`), regardless of trailing slash. To merge contents, tar
  them: `tar czf tmp.tgz -C <dir> .` → `msb cp tmp.tgz vm:/tmp/x.tgz` →
  `msb exec vm -- tar xzf /tmp/x.tgz -C /workspace/`.
- **Named volumes persist across applies** and can hold stale state. The
  orchestrator clears the dest before seeding (pruning nested mount points).

For the full seeding logic and the `msb cp` nesting workaround, read
`references/msb-operations.md`.

## Services MUST bind 0.0.0.0 (not 127.0.0.1)

A service inside the VM reached via msb port-forward (`ports: ["8000:8000"]`)
is contacted on the VM's `eth0`, NOT loopback. Binding `127.0.0.1` makes the
port look open but every host request gets an empty reply (curl exit 52 /
`ERR_EMPTY_RESPONSE`). Always bind `0.0.0.0:PORT`. This applies to the app,
the git-daemon, and the loki dashboard alike.

## Host↔VM sync: three approaches

1. **`sandbox.sync` (git clone, recommended)** — when `sync.enabled: true`,
   microcode clones the remote into the workspace during build/apply, replacing
   the bind mount / tar-seed. The `./src` mount for `sync.dest` is suppressed
   automatically; the git host is auto-allowlisted for egress. Loki gets shared
   git history and commits on a `vm/<sandbox>` branch the host can fetch+merge.
   Credentials via `auth.token_env`/`ssh_key_env` (host env, never inlined).
2. **msb cp** (default one-shot, when sync is off) — copy files host↔VM. Fine
   for seeding; bad for iterative work (no live sync). Use the tar workaround
   above for dirs.
3. **git-daemon** (live pull of loki's result) — run a read-only `git daemon`
   in the VM on a forwarded port; the host fetches loki's commits via git.
   Complements `sandbox.sync` (clone gives the VM the codebase IN; the daemon
   lets the host pull loki's work OUT). See `references/git-sync.md`.

Prefer `sandbox.sync` for the codebase-in direction; add the git-daemon when
you also need to pull loki's result back repeatedly.

## Secrets: never inline, always ${VAR}

Reference secrets by env-var name in the manifest; `expand_env` resolves them
host-side (like `CLINE_API_KEY`). The `secrets:` field adds `allow_hosts`
egress scoping. Required z.ai env: `CLINE_API_KEY`, `ZAI_BUSINESS_BASE_URL`,
`ZAI_OAUTH_ORIGIN`, `ZAI_OAUTH_CLIENT_ID`.

```yaml
sandbox:
  env:
    MY_TOKEN: "${MY_TOKEN}"        # resolved from host env at apply time
  secrets:
    - env: CLINE_API_KEY
      allow_hosts: [api.z.ai]
```

## Loki: how it runs and how to steer it

loki-mode runs **inside the VM** (as user `loki`), in a RARV loop
(Reason-Act-Reflect-Verify). It reads an overlay of skills from
`/workspace/skills/00-index.md` (your `custom-skills/` dir, mounted in). It
commits checkpoints on a `loki/session-*` branch inside `/workspace`.

- **Stuck in BUILDING / 0 tasks completed for many minutes**: the cline-shim is
  waiting on the GLM API. Verify `CLINE_API_KEY` is set and the
  `zai-coding-plan` provider exists in `~/.cline/data/settings/providers.json`.
  For a large directive, prefer a PRD-file `--prd` over inline `steer` (loki's
  PRD context absorbs short inline messages).
- **steer is async**: `microcode steer` appends to `.loki/HUMAN_INPUT.md`; loki
  reads it on the next RARV iteration. It needs `LOKI_PROMPT_INJECTION=1`
  (loki_runner passes this automatically).
- **`--prd src/PRD.md` path remap**: `./src` mounts INTO `/workspace`, so the
  prd path is remapped (`src/PRD.md` → `PRD.md` = `/workspace/PRD.md`) by
  `_resolve_prd_guest_path` in loki_runner.py. Don't "fix" a not-found prd by
  adding `src/` — it's already handled.

## VM operations cheat sheet

```bash
export PATH="$HOME/.microsandbox/bin:$PATH"
msb ps                              # list running VMs + forwarded ports
msb exec <name> --user loki -- bash -lc '...'   # run inside VM as loki
msb cp <host-file> <name>:<guest-path>          # copy in (note nesting trap for dirs)
msb cp <name>:<guest-path> <host-file>          # copy out
msb stop <name> && msb rm -f <name>             # teardown
msb snapshot create mcd-base --from <name> --force   # capture
```

`pgrep`/`ps` are often **unavailable** in the VM — scan `/proc/[0-9]*/cmdline`.
Go builds fill `/tmp` (tmpfs) — clean `$(go env GOCACHE)` if you hit ENOSPC.

For the full msb reference (hidden-sandbox bug, root-disk rules, snapshot
export/import, the `/proc` scan idiom), read `references/msb-operations.md`.

## Common failure modes → first check

| symptom | likely cause | fix |
|---|---|---|
| `apply` hangs, loki 0 tasks done | cline-shim waiting on GLM API | verify CLINE_API_KEY + provider json; use `--prd` file |
| host curl to forwarded port → empty reply | service bound 127.0.0.1 | rebind `0.0.0.0:PORT` |
| `mount: Not a directory` at boot | bind-mount + from_snapshot | expected; uses named volume + seed |
| VM disk full (ENOSPC) | overlay too small / GOCACHE in tmpfs | `root_disk: 8G`; clean caches |
| `msb create` says "already exists" but `msb ps` empty | hidden sandbox bug | `rm -rf ~/.microsandbox/sandboxes/<name>` |
| go.sum checksum mismatch | stale/foreign module hash | `GONOSUMDB=off GONOSUMCHECK=* go mod tidy` via proxy.golang.org |
| `go install` fails `lookup storage.googleapis.com` | GCS-only module (circl/go-git) | add storage.googleapis.com + *.googleapis.com to allowlist |
| steer directive ignored | needs LOKI_PROMPT_INJECTION=1 | already set by loki_runner; use PRD-file instead of inline |

## Reference files (read on demand)

- `references/msb-operations.md` — msb CLI deep dive: the cp nesting workaround,
  hidden-sandbox purge, root-disk rules, /proc scan, snapshot save/load.
- `references/git-sync.md` — the host↔VM git-daemon topology, branching model
  (main read-only in VM, vm/<sandbox> working branch), and why loki reuses a
  pre-cloned repo instead of git init.
- `references/manifest.md` — full platform.yaml section reference (sandbox,
  loki, skills, mounts, ports, env, secrets, network/allowlist, snapshot,
  init.packages, extra_shell) with annotated examples.
