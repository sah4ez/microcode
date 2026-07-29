# microcode

**Unified IaC for skillkit + loki-mode + microsandbox** — configure skills,
agent orchestration, and the execution environment in a single `platform.yaml`.

microcode wires three complementary systems into one platform:

| Aspect | Tool | What microcode does |
|---|---|---|
| Skills | [skillkit](https://github.com/rohitg00/skillkit) | Installs + translates skills into a single format for loki |
| Orchestration | [loki-mode](https://github.com/asklokesh/loki-mode) | Generates loki config (providers, gates, memory, budget) |
| Execution | [microsandbox](https://github.com/superradcompany/microsandbox) | Boots a stock `debian` microVM, installs the runtime via init script, runs loki inside |

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design.

## Install

```bash
git clone <this-repo> microcode && cd microcode
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Host prerequisites (checked by `microcode doctor`):

* [`msb`](https://github.com/superradcompany/microsandbox) (microsandbox CLI)
* [`skillkit`](https://github.com/rohitg00/skillkit) CLI
* The secret values referenced in the manifest (e.g. `ANTHROPIC_API_KEY`) in
  your shell environment — they are **never** written into the manifest.

## Quick start

```bash
# 1. validate the manifest
microcode validate examples/minimal.yaml

# 2. see exactly what would run (no execution)
microcode plan examples/minimal.yaml --prd prd.md

# 3. provision everything: skills + VM + init + loki
microcode apply examples/minimal.yaml --prd prd.md

# 4. tear it all down
microcode destroy examples/minimal.yaml
```

`apply --dry-run` prints every command without executing anything.

## The manifest

One file, three sections:

```yaml
version: 1

skills:                       # → skillkit
  install:
    - { source: anthropics/skills, skills: [code-review], agents: [claude-code] }
  translate: { target_agent: claude-code, output_dir: skills }

loki:                         # → loki-mode
  provider: claude
  max_budget_usd: 10.0
  quality_gates: { enabled: true }

sandbox:                      # → microsandbox
  image: debian               # stock image; runtime installed via bootstrap.sh
  cpus: 2
  memory: 2048
  init:
    packages:
      apt: [curl, git, python3, python3-pip]
      npm_global: [loki-mode, "@skillkit/cli"]
      bun: true
  secrets:
    - { env: ANTHROPIC_API_KEY, allow_hosts: [api.anthropic.com] }
  mounts:
    - { host: ./src, dest: /workspace }
```

Full reference: [`platform.schema.json`](platform.schema.json) and
[`examples/`](examples/) (`minimal.yaml`, `allowlist.yaml`, `full-stack.yaml`).

### Network allow/deny lists

`sandbox.network.mode` selects how egress is controlled:

* `profile` (default) — compose egress profiles (`public`, `private`, `host`).
* `allowlist` — **deny-by-default**; only the listed `allow` rules pass (DNS
  auto-allowed). Strictest mode for untrusted agent output.
* `denylist` — allow-by-default; `deny` rules block specific domains/IPs/CIDRs.

```yaml
sandbox:
  network:
    mode: allowlist
    default_egress: deny
    allow:
      - { action: allow, target: api.anthropic.com, proto: tcp, port: 443 }
      - { action: allow, target: registry.npmjs.org, proto: tcp, port: 443 }
    deny_domain_suffixes: [telemetry.example.com]
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md#network-policies-allow--deny-lists) for
the full rule grammar and all three modes.

### Secrets

Secrets are referenced **by host env-var name only**. microcode emits
`msb --secret ENV@host`; the real value stays on the host and is swapped by
microsandbox's TLS proxy only for allow-listed hosts. The manifest never
contains a secret value.

## CLI

| Command | Description |
|---|---|
| `microcode validate [file]` | Validate the manifest (pydantic schema) |
| `microcode plan [file] --prd ...` | Print the ordered plan + generated `bootstrap.sh` |
| `microcode apply [file] --prd ...` | Provision skills, VM, init, and start loki |
| `microcode destroy [file]` | Stop/remove the VM and clean generated state |
| `microcode show [file]` | Dump the resolved manifest |
| `microcode doctor` | Check `msb` and `skillkit` are on PATH |

## Development

```bash
python -m pytest -q          # 30 tests, no external tools required
```

Tests cover manifest validation, all four generators (incl. `bootstrap.sh`
shell-quoting), planner determinism, and orchestrator artifact writing.

## License

Apache-2.0.
