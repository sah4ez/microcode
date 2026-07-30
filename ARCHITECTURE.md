# Architecture

`microcode` is a single IaC layer that unifies three complementary systems around
AI coding agents:

| Aspect | Subsystem | Role in microcode |
|---|---|---|
| **Skills** | [skillkit](https://github.com/rohitg00/skillkit) | Provision + translate skills (`SKILL.md`) |
| **Orchestration** | [loki-mode](https://github.com/asklokesh/loki-mode) | Spec-driven agent build loop (RARV) |
| **Execution** | [microsandbox](https://github.com/superradcompany/microsandbox) | Isolated microVM runtime |

The three are **complementary, not overlapping**: skillkit ships *what* an agent
should know, loki-mode drives *how* the agent builds, microsandbox provides
*where* it runs safely. microcode is the single place that configures all three.

## Design principles

1. **One source of truth.** `platform.yaml` is the only file you edit. Each
   subsystem receives only the generated subset it understands.
2. **Generators are pure functions** (`manifest -> text/json`). They have no I/O
   and are unit-tested without any tool installed.
3. **Runners are thin.** They only shell out to `skillkit` / `msb` / `loki` and
   support `--dry-run` uniformly.
4. **Deterministic plans.** The same manifest always yields the same plan. This
   makes `plan` reproducible and `apply` safe to re-run. (We deliberately omit
   timestamps from generated artifacts.)
5. **Secrets never enter the manifest or the VM.** Secrets are referenced by
   host env-var name and injected via microsandbox's `--secret ENV@host` TLS
   interception — the real value stays on the host and is swapped at the network
   boundary only for allow-listed hosts.
6. **Stock `debian` image + init script.** Rather than baking a custom OCI
   image, microcode boots the stock `debian` image and installs the runtime
   (node, bun, python, loki-mode, skillkit, provider CLIs) via a generated
   `bootstrap.sh` injected through microsandbox's rootfs-patch (`--copy-file`).
   This keeps iteration fast (no image rebuilds) and the manifest authoritative.

## Data flow

```
platform.yaml  ──(read+validate)──►  Planner
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  skills generator              loki generator                  bootstrap + sandbox
  → .skills                     → loki-config.yaml              → bootstrap.sh
  → skillkit cmds               → loki.env                      → msb create/exec cmds
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
                                   Orchestrator
                          (write artifacts + run in order)
                                         │
   ┌──────────────────┬──────────────────┼───────────────────┐
   ▼                  ▼                  ▼                   ▼
 skillkit CLI    msb create debian   msb exec bootstrap   msb exec loki start
 (on host)       + --copy-file        (install runtime)    (--config loki-config.yaml)
```

## The `apply` pipeline (deterministic order)

1. **doctor** — verify `msb` and `skillkit` are on PATH.
2. **plan** — build the plan (generators only, pure).
3. **write artifacts** to `<state_dir>/artifacts/` (`.skills`, `loki-config.yaml`,
   `loki.env`, `bootstrap.sh`).
4. **skillkit (host)** — `skillkit install <source> --yes ...` per source, then
   `skillkit translate --all --to <agent> -o skills/`. The translated `SKILL.md`
   files land in the host `skills/` dir, which is mounted into the VM.
5. **msb create** — boot `debian:bookworm-slim` with resources, network,
   secrets, volumes, mounts, ports, **and** `--copy-file bootstrap.sh:/root/bootstrap.sh`.
   The script is injected into the rootfs *before* boot.
6. **msb exec bootstrap** — `msb exec <name> -- bash /root/bootstrap.sh`. Runs as
   root (debian default); installs node/bun/python + loki-mode + skillkit + provider CLIs.
7. **(optional) snapshot** — if `sandbox.init.snapshot.enabled`, `msb snapshot
   create <name> --from <name>`. Subsequent applies can start from the snapshot
   and skip step 6.
8. **msb exec loki start** — `loki start --config /workspace/.microcode/artifacts/loki-config.yaml
   --no-dashboard --simple <prd>`. Config + skills are available via the mount.

### Optional: skillkit inside the VM (`skills.in_vm: true`)

By default skillkit runs on the **host** (step 4). Set `skills.in_vm: true` to
instead run it **inside** the microsandbox VM. In that mode:

* step 4 is skipped on the host (`doctor` no longer requires `skillkit` locally);
* each `skillkit install`/`translate` command is wrapped as
  `msb exec <name> --user loki -- bash -lc '<env-prefix> && skillkit ...'` and
  runs **after** steps 5–6 (the VM must exist and be bootstrapped);
* skills are provisioned in the exact environment loki will use (same node,
  same `@skillkit/cli` version installed by `bootstrap.sh`).

Phase order becomes: doctor → plan → artifacts → **sandbox (create+init)** →
**skillkit (in VM)** → loki. The translated `SKILL.md` files still land in the
mounted `skills/` dir, so nothing else changes.

## Why stock debian + init script (not a custom image)

* **Faster iteration.** Changing the manifest (packages, provider CLIs) does not
  require rebuilding/pushing an OCI image.
* **Less lock-in.** No private Dockerfile to maintain; the image is a stock
  upstream artifact.
* **Native microsandbox feature.** `--copy-file` rootfs-patch + `msb exec` is
  the supported one-shot bootstrap pattern; `--init auto` (systemd) is only
  needed for long-running multi-service supervision, which loki-mode does not
  require.
* **Cacheable.** The optional `msb snapshot` caches the installed environment so
  re-creates are fast without paying for an image rebuild.

Trade-off: the first boot pays the install cost (network egress for apt/npm/pip).
The snapshot flag mitigates this for repeated runs.

## Network policies (allow / deny lists)

microcode exposes microsandbox's full network-rule model through three
`sandbox.network.mode` values. Under the hood it emits either `--net <profiles>`
or `--net-default-egress <X>` + repeated `--net-rule "<token>"` — the two are
mutually exclusive in `msb`, so exactly one mechanism is used per sandbox.

Rule token grammar (microsandbox `net_rule.rs`):
`<action>[:<direction>]@<target>[:<proto>[:<ports>]]` — the port **always** lives
in the proto slot, never in the target.

### `mode: profile` (default — backward compatible)

Compose egress profiles; optional `deny_domains` / `deny_domain_suffixes` add
deny rules on top.

```yaml
network:
  mode: profile
  profile: [public, host]
  deny_domains: [evil.example.com]
  deny_domain_suffixes: [ads.example.com]
```
→ `--net public,host --net-rule deny@evil.example.com --net-rule deny@suffix=ads.example.com`

### `mode: allowlist` (deny-by-default, white list)

Only explicitly allowed destinations pass; everything else is blocked. DNS is
auto-allowed so names still resolve. This is the strictest mode and the
recommended one for running untrusted agent output.

```yaml
network:
  mode: allowlist
  default_egress: deny
  allow:
    - { action: allow, target: api.anthropic.com, proto: tcp, port: 443 }
    - { action: allow, target: host }
```
→ `--net-default-egress deny --net-rule allow@api.anthropic.com:tcp:443
   --net-rule allow@host --net-rule allow@dns`

### `mode: denylist` (allow-by-default, black list)

Default-allow public egress, but block specific destinations (domains, IPs,
CIDRs, suffixes). Convenient when you trust the workload generally but want to
kill known-bad destinations.

```yaml
network:
  mode: denylist
  default_egress: allow
  deny:
    - { action: deny, target: 10.0.0.0/8 }
    - { action: deny, target: malicious.example.com }
```
→ `--net-default-egress allow --net-rule deny@10.0.0.0/8
   --net-rule deny@malicious.example.com`

### Validation rules enforced

* In `allowlist`, only `allow` rules are permitted (deny is the default).
* In `denylist`, only `deny` rules are permitted (allow is the default).
* A rule with a `port` must set an explicit `proto` (microsandbox's `any`
  proto carries no ports).
* `deny_domain_suffixes` must be ≥2-label domains (`example.com`, not `com`).
* Port ranges use the `lo-hi` form (e.g. `8000-8100`).

See [`examples/allowlist.yaml`](examples/allowlist.yaml) and
[`examples/full-stack.yaml`](examples/full-stack.yaml) for complete setups.

## External loki memory (persistent volume)

loki-mode keeps its cross-project learnings in a local store under its memory
base path (SQLite + FTS5, by default `~/.loki`). Inside an ephemeral microVM
that store is lost every time the VM is destroyed/recreated.

`loki.memory.storage` moves the store onto a **microsandbox named volume** that
persists on the host across VM lifecycles:

```yaml
loki:
  memory:
    enabled: true
    managed: true
    storage:
      enabled: true            # mount the volume + set LOKI_MEMORY_BASE_PATH
      volume: loki-memory      # named volume (created/reused by msb)
      dest: /data/loki-memory  # guest path = LOKI_MEMORY_BASE_PATH
```

What microcode does when `storage.enabled`:
* mounts the named volume at `dest` (`msb create ... -v loki-memory:/data/loki-memory`) — added automatically, no need to duplicate it under `sandbox.volumes`;
* sets `LOKI_MEMORY_BASE_PATH=<dest>` in both the generated `loki.env` and the
  `msb exec ... loki start` invocation (via `-e`).

The volume lives under microsandbox's volume directory on the host and survives
`microcode destroy` + `apply` cycles, so loki accumulates learnings across runs.

## Secret handling

```yaml
sandbox:
  secrets:
    - env: ANTHROPIC_API_KEY              # host env var name
      allow_hosts: [api.anthropic.com]    # only these hosts may receive it
```

microcode emits `msb ... --secret ANTHROPIC_API_KEY@api.anthropic.com`. The real
key is read from the **host** environment by `msb`; inside the VM only a harmless
placeholder exists. microsandbox's TLS-intercepting proxy swaps the placeholder
for the real value *only* for traffic to allow-listed hosts and blocks it
everywhere else. The manifest never contains a secret value.

## cline provider limitation on arm64 microsandbox VMs

`loki --provider cline` shells out to the `cline` CLI. The cline npm package
ships a **platform-specific Bun-compiled native binary** (fetched by
postinstall into `node_modules/@cline/cli-<plat>-<arch>/`). On **arm64
microsandbox VMs** that Bun runtime crashes during real work:

```
Bun v1.3.13 (bf2e2cec) Linux arm64
panic(main thread): Bus error at address 0x920EB5A
```

`cline --version` succeeds (static path), but any LLM-driven run panics in Bun's
JIT. This is a Bun/microsandbox-arm64 incompatibility, **not** a node-version
issue (verified on node 18, 22.5, 22.11, 22.20) and not fixed by disabling ASLR.
On the host (macOS arm64) cline works because it runs the **darwin-x86_64**
binary under Rosetta, not the arm64 one.

Workaround options:
1. **`--provider claude`** (Claude Code) pointed at z.ai's Anthropic-compatible
   endpoint (`ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic`, model
   `glm-4.6`). This runs GLM through a stable native binary and is the path used
   in `examples/` and `todo-run/`.
2. **`@cline/core` under node** — the core SDK is pure JS (`ClineCore.create()`
   → `cline.start({prompt})`) and loads under node without Bun. A node-based
   CLI shim exposed via `CLINE_BIN_PATH` could satisfy loki's `cline` contract,
   but requires reproducing cline's full CLI/tool behavior through the
   undocumented core API.
3. Run an **x86_64 VM** (qemu/Docker emulation) where the cline x86_64 binary is
   stable.

Until (2) or (3) is implemented, `--provider cline` is **not functional inside
arm64 microsandbox VMs**; use `--provider claude` + z.ai for GLM.

## Module layout

```
src/microcode/
├── manifest.py          # pydantic schema (single source of truth model)
├── generators/          # manifest -> artifacts (pure)
│   ├── skills.py        #  → .skills + skillkit cmds
│   ├── loki.py          #  → loki-config.yaml + loki.env
│   ├── bootstrap.py     #  → bootstrap.sh from sandbox.init
│   └── sandbox.py       #  → msb create/exec/snapshot cmds
├── planner.py           # ordered Plan (deterministic)
├── orchestrator.py      # write artifacts + drive runners
├── runners/             # thin CLI wrappers (dry-run aware)
│   ├── skillkit_runner.py
│   ├── sandbox_runner.py   # resolves bootstrap.sh placeholder + chmod 0755
│   └── loki_runner.py
└── cli.py               # typer: validate/plan/apply/destroy/show/doctor
```

## Limits (MVP)

* No custom MCP bridge over skillkit (file-generation path chosen instead).
* Does not auto-install `msb`/`skillkit` on the host — `doctor` checks them.
* Single loki provider per manifest.
* No parallel multi-sandbox orchestration.
