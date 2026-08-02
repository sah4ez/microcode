# platform.yaml manifest reference

The manifest (pydantic schema in `manifest.py`) is the single source of truth.
`extra="forbid"` on every model — unknown keys are an error, so spell sections
exactly as below. Validate with `microcode validate` before applying.

## Top-level sections

```yaml
version: 1
project:
  name: my-service
  state_dir: .microcode         # artifacts/loki-config/bootstrap.sh land here
skills:  ...                    # skillkit: install/translate/agents/in_vm
loki:    ...                    # provider/model/dashboard/phases/memory
sandbox: ...                    # VM: image/resources/network/snapshot/ports/env
```

## sandbox (the VM)

```yaml
sandbox:
  name: notes-build
  image: debian:bookworm-slim
  cpus: 4
  memory: 4096                  # MB
  root_disk: 8G                 # writable rootfs (msb create ONLY; build mode)
  user: loki                    # unprivileged user loki runs as

  init:
    packages:
      apt: [curl, git, ca-certificates]        # extra apt packages
    extra_shell: |                             # extra bootstrap steps
      apt-get install -y some-tool
      # run as root during bootstrap; loki user already created
    snapshot:
      enabled: true                # BUILD mode: capture snapshot after bootstrap
      # from_snapshot: mcd-base    # APPLY mode: boot from snapshot (faster)
      name: mcd-base

  network:
    mode: allowlist                # default-deny; allow specific hosts
    allow:
      - { action: allow, target: api.z.ai, port: 443, protocol: tcp }
      - { action: allow, target: github.com, port: 443, protocol: tcp }
    dns:
      nameservers: [1.1.1.1, 8.8.8.8]   # when host resolvers fail

  mounts:
    - { host: ./custom-skills, dest: /workspace/skills, readonly: false }
    - { host: ./src, dest: /workspace, readonly: false }
    # NOTE: with from_snapshot these become NAMED VOLUMES (msb can't bind-mount).
    # They are seeded via msb cp on each apply; they do NOT sync live.

  ports:
    - "8000:8000"                  # host:guest — service must bind 0.0.0.0
    - "9418:9418"                  # git-daemon (optional, for git-sync)

  env:
    MY_TOKEN: "${MY_TOKEN}"        # ${VAR} resolved host-side via expand_env
    SYNC_REMOTE_URL: "${SYNC_REMOTE_URL}"

  secrets:
    - env: CLINE_API_KEY           # host env var name (value never inlined)
      allow_hosts: [api.z.ai]      # egress scoping
```

### network modes
- `allowlist` (default-deny) — only `allow:` targets reachable; everything else
  blocked. Use this for locked-down builds.
- `denylist` — everything allowed except `deny:` targets.
- (profile-based) — a named profile; see `generators/net.py`.

### snapshot: build vs apply
- `enabled: true` → **build mode**: `microcode build` runs bootstrap once and
  captures a snapshot. Slow (~20-30 min) but done once.
- `from_snapshot: mcd-base` → **apply mode**: boot from the pre-built snapshot.
  Fast (seconds). Bind mounts become named volumes (see SKILL.md gotcha).
- These two are **mutually exclusive** (validator enforces it).

## loki (the build agent)

```yaml
loki:
  provider: cline                 # claude | codex | cline | aider
  model: glm-5.2                  # → CLINE_MODEL + LOKI_CLINE_MODEL (pass BOTH)
  dashboard: false                # true → --api (web UI on :57374, needs fastapi)
  max_iterations: 50
  max_budget_usd: 5.0
  effort: high                    # low | medium | high
  start_phase: DEVELOPMENT        # BOOTSTRAP/DISCOVERY/.../DEPLOYMENT/GROWTH
  stop_after_phase: QA            # pause for human review after this phase
  memory:
    storage:
      enabled: true               # mount a named volume for cross-apply memory
      volume: loki-memory
      dest: /data/loki-memory
```

Env-var naming trap: loki's cline provider reads `LOKI_CLINE_MODEL`; the node-shim
reads `CLINE_MODEL`. The runner passes both — if you set `loki.model`, you're
covered.

## skills (skillkit)

```yaml
skills:
  in_vm: true                     # skillkit runs inside VM (vs host)
  agents: [cline]                 # LOKI_AGENTS
  install:
    - source: github://obra/superpowers
      skills: ["*"]
  translate:
    target_agent: cline
    output_dir: .skills-generated   # NOT "skills" — collides with overlay mount
```

`output_dir` collision: `skills` conflicts with the `/workspace/skills` overlay
mount → use `.skills-generated`.

## Custom overlay skills (the loki-facing skill files)

Skills you author (like `tg-dev.md`, `git-sync.md`) live in `custom-skills/` on
the host and are mounted to `/workspace/skills/`. loki reads
`/workspace/skills/00-index.md` first — a table mapping task-type → which skill
files to load (1-3 per phase). Each skill file has YAML frontmatter (`name`,
`description`) and a `**When:**` trigger header. These are pure markdown mounted
as-is; no generator change needed to add one.

## Secrets pattern (critical)

NEVER inline a secret value in the manifest. Reference it by env-var name:

```yaml
sandbox:
  env:
    CLINE_API_KEY: "${CLINE_API_KEY}"   # expand_env resolves from host env
  secrets:
    - env: CLINE_API_KEY
      allow_hosts: [api.z.ai]           # restrict egress
```

Required z.ai env vars: `CLINE_API_KEY`, `ZAI_BUSINESS_BASE_URL`,
`ZAI_OAUTH_ORIGIN`, `ZAI_OAUTH_CLIENT_ID`.

## 7 annotated examples

In the microcode repo under `examples/`: `minimal.yaml`, `allowlist.yaml`,
`full-stack.yaml`, `skills-in-vm.yaml`, `cached-base.yaml`, `todo-api-cline.yaml`,
`cline-multi-skills.yaml`. Read the one closest to your use case before writing
a manifest from scratch.
