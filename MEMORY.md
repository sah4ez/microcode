# MEMORY — контекст проекта microcode

> Снимок состояния работы на 2026-07-31. Этот файл — чтобы быстро войти в
> контекст при возобновлении: что сделано, ключевые решения, найденные обходы,
> что доказано, что осталось.

## Что это за проект

**microcode** — единая IaC-платформа, связывающая три системы в один пайплайн
через один манифест `platform.yaml`:

| Аспект | Подсистема | Роль |
|---|---|---|
| Навыки | [skillkit](https://github.com/rohitg00/skillkit) | Доставка + перевод скиллов |
| Оркестрация | [loki-mode](https://github.com/asklokesh/loki-mode) | Spec-driven build (RARV) |
| Среда | [microsandbox](https://github.com/superradcompany/microsandbox) | Изолированная microVM |

`microcode apply` оркестрирует весь путь: doctor → plan → artifacts → boot VM
(create или from_snapshot) → skillkit install → loki start — без ручных msb.

## Текущее состояние (ДОКАЗАНО)

- **Todo-приложение с UI построено через `provider cline` + GLM-5.2/z.ai** внутри
  microcode VM. 20/20 тестов зелёные. CRUD + toggle done + delete, SQLite
  персистентен, UI (vanilla JS) обслуживается сервером. Код в `test-todo/src/`.
- **Полный pipeline работает end-to-end**: `microcode build` (snapshot) →
  `microcode apply` (from_snapshot + named volumes + msb cp seeding) → skillkit
  install+translate (obra/superpowers) → loki start --provider cline --api →
  RARV-цикл → готовое приложение. `msb cp` копирует результат в локальный репо.
- **Loki dashboard доступен** на http://localhost:57374 (live RARV прогресс,
  Lab tab для постановки задач).
- **Todo-app доступен** на http://localhost:8000 (UI для управления задачами).
- **Тесты: 79/79 зелёные.**
- 7 примеров валидны: minimal, allowlist, full-stack, skills-in-vm,
  cached-base, todo-api-cline, cline-multi-skills.
- Всё запушено в `origin/master` (github.com:sah4ez/microcode.git).

## Ключевое достижение: cline работает без Bun через node-shim

**Проблема:** cline CLI — это Bun-compiled native binary. На arm64 microsandbox
VM падает с **Bus error** в JIT. Под qemu — Segfault.

**Решение:** `src/microcode/assets/cline-node-shim.cjs` — запускает cline через
чистый-JS `@cline/core` SDK под node, **без Bun**. Корневые находки реверса
core-API (v8.4.0):

- провайдер `zai-coding-plan` + **`CLINE_API_KEY`** env (apiKey из cline config,
  не OAuth-only — OAuth-env vars отдельно);
- `ClineCore.create()` → `cline.start({config:{providerId,modelId,apiKey,
  enableTools:true,enableSpawnAgent:false,enableAgentTeams:false},prompt,...})`
  → возвращает `{sessionId,manifest,result}` где `result.text` — ответ модели;
- **НЕ вызывать `cline.send()`** — start() уже выполняет agent-loop синхронно;
- поля `enableTools/enableSpawnAgent/enableAgentTeams` — **camelCase** в `config`
  (zod-схема маппит их в snake_case внутри startResolvedSession);
- `enableAgentTeams` (не `enableTeams`!) — точное имя из минифицированного кода.

bootstrap перекрывает npm-cline **во всех bin-директориях** (`/usr/local/bin`,
`/opt/npm-global/bin`, `/root/.npm-global/bin`) — shim выигрывает независимо от
PATH.

## Найденные обходы (вшиты в генераторы microcode)

1. **cline arm64 Bun crash** → node-shim через `@cline/core` (см. выше).
2. **apt роняет overlay-FS** → tmpfs apt-cache + **без `-qq`**.
3. **node через `n`**: debian-`nodejs` + npm-tarball + `n install 22`.
4. **Непривилегированный `loki`**: bootstrap создаёт + PATH; runner через
   `--user loki` с явным `export PATH`.
5. **npm-global lib вложенный** (`lib/lib`): `cp -a lib/node_modules/. → lib/node_modules/`.
6. **bun-global относительные symlink'и**: `readlink -f` → абсолютные symlink'и
   в `/opt/npm-global/bin` (cp -a копировал битые относительные ссылки).
7. **skillkit — это npm-пакет `skillkit`**, а НЕ `@skillkit/cli` (последний —
   библиотека без bin → `command not found`).
8. **`LOKI_CLINE_MODEL`** (не `CLINE_MODEL`!) — loki's cline provider читает
   именно эту env; shim читает `CLINE_MODEL`. Передаём обе.
9. **loki config providers.json** для `zai-coding-plan` — bootstrap создаёт
   `~/.cline/data/settings/providers.json` для пользователя loki.
10. **Snapshot round-trip**: `msb run --from-snapshot` НЕ поддерживает bind-mounts
    ("mount: Not a directory"). Решение: bind-mounts → **named volumes**
    (`mcd-workspace`, `mcd-workspace-skills`) + `msb cp` seeding после boot.
    Named volumes — root-owned → **`chown -R loki:loki`** после cp.
11. **`--root-disk 8G`** только для `msb create` (msb run --from-snapshot его
    отвергает: "requires an OCI image").
12. **Hidden sandbox** (msb 0.6.8 баг): `msb rm -f`/`msb list` не видят sandbox,
    но `msb create` падает "already exists". Fallback: `rm -rf
    ~/.microsandbox/sandboxes/<name>`.
13. **Stale sandbox** перед `msb create` → `msb rm -f` + fallback rm (нет
    `--replace` у create, только у `msb run`).
14. **`--force`** в `msb snapshot create` (перезапись существующего snapshot).
15. **DNS**: `sandbox.network.dns.nameservers` → `--dns-nameserver` (repeatable)
    когда хост-резолверы не резолвят (bun.sh и др.).
16. **loki-config не в VM**: генерируется на хосте в `<state_dir>/artifacts/`, но
    mount только `./src`. Решение: `msb cp` конфига в VM перед `loki start`.
17. **ENOSPC**: default overlay ~4G переполняется bootstrap'ом → `root_disk: 8G`
    + cleanup apt/npm caches в конце bootstrap.
18. **translate output_dir collision**: `--output skills` конфликтует с overlay
    mount `/workspace/skills` → `output_dir: .skills-generated`.
19. **loki dashboard**: `--api` (включить) или `--no-dashboard`. Биндится на
    `127.0.0.1` по умолчанию → нужен `--host 0.0.0.0` для доступа с хоста.
    Требует fastapi/uvicorn (pypi.org в allowlist + pip install).
20. **env-substitution** `${VAR}` в sandbox.env (секреты по имени, не инлайн).

## CLI команды (полный список)

| Команда | Что делает |
|---|---|
| `microcode validate [file]` | pydantic + JSON Schema валидация |
| `microcode plan [file]` | печать плана + bootstrap.sh preview |
| `microcode apply [file]` | provision skills, VM, start loki |
| `microcode build [file]` | build snapshot (bootstrap once) |
| `microcode snapshot save/load` | экспорт/импорт snapshot |
| `microcode destroy [file]` | остановить VM + чистка state |
| `microcode steer [file] "msg"` | асинхронная директива в running loki |
| `microcode status [file]` | фаза/итерация/commits/workspace |
| `microcode rollback [file] [--to HASH]` | откат к git checkpoint |
| `microcode show [file]` | resolved manifest |
| `microcode doctor` | проверка msb/skillkit |

## Архитектура (где что)

```
src/microcode/
├── manifest.py            # pydantic-схема (skills/loki/sandbox + Net/DNS/Snapshot)
├── generators/            # манифест → артефакты (чистые функции)
│   ├── bootstrap.py       # → bootstrap.sh (node, bun, user loki, cline shim override, cline config)
│   ├── net.py             # rule_token/network_argv/dns_argv (3 режима + DNS)
│   ├── skills.py          # → .skills + skillkit cmds (in_vm wrapping, LOKI_AGENTS)
│   ├── loki.py            # → loki-config.yaml + loki.env (model, phases, dashboard)
│   └── sandbox.py         # → msb create/run/snapshot (from_snapshot→named volumes)
├── runners/
│   ├── sandbox_runner.py  # resolve mounts→absolute, inject shim, ensure mount dirs
│   └── loki_runner.py     # bash -lc, --user loki, -e secrets+CLINE_MODEL+LOKI_CLINE_MODEL, --api/--no-dashboard
├── orchestrator.py        # apply (rm stale + purge hidden + from_snapshot cp+chown), destroy
├── planner.py             # детерминированный Plan
├── assets/cline-node-shim.cjs   # ★ node-shim cline через @cline/core (camelCase config)
└── cli.py                 # typer: validate/plan/apply/build/snapshot/destroy/steer/status/rollback/show/doctor
docs/extending-loki.md     # гайд: расширение/замена навыков + фазы SDLC
examples/                  # 7 примеров
test-todo/                 # реальный прогон: platform.yaml + PRD + custom-skills + результат
environment.yml            # conda env mcd (dev)
```

## Манифест — ключевые поля (кратко)

```yaml
skills:
  in_vm: true/false        # skillkit внутри VM или на хосте
  agents: [cline]          # = LOKI_AGENTS (claude, codex, cline, aider)
  install: [{source, skills}]
  translate: {target_agent, output_dir}
loki:
  provider: cline          # claude/codex/cline/aider
  model: glm-5.2           # → CLINE_MODEL + LOKI_MODEL_OVERRIDE
  dashboard: true          # --api (web UI на 57374)
  stop_after_phase: ...    # пофазовые паузы
  start_phase: ...
  memory.storage: {enabled, volume, dest}  # named volume (LOKI_MEMORY_BASE_PATH)
sandbox:
  root_disk: 8G            # writable rootfs (только для msb create)
  network.dns.nameservers  # кастомные DNS
  init.snapshot:
    enabled: true          # build: создать snapshot
    from_snapshot: mcd-base # apply: boot из snapshot
  ports: ["8000:8000", "57374:57374"]
```

## Сеть провайдера (z.ai) — что работает

- ✅ **cline `zai-coding-plan` + apiKey** через node-shim → GLM-5.2 (доказано:
  shim возвращает `Hello`, loki строит приложения).
- ✅ Dashboard на http://localhost:57374 (Lab tab для постановки задач).
- ✅ Todo-app на http://localhost:8000.

## Ограничения

- bootstrap на arm64 VM медленный (~20-30 мин). Snapshot (`microcode build`)
  решает — apply из snapshot занимает секунды.
- from_snapshot НЕ поддерживает bind-mounts (msb 0.6.8) → named volumes + cp.
- loki dashboard требует fastapi/uvicorn (pip install, нужен pypi в allowlist).
- snapshot от post-bootstrap VM иногда даёт `Read-only file system` при boot —
  баг msb 0.6.8 (msb 0.6.7 тоже). Workaround: named volumes вместо snapshot.

## Как возобновить

```bash
cd /Users/aleksandrkozlenkov/git/microcode
conda activate mcd            # или: conda env create -f environment.yml
PYTHONPATH=src python -m pytest -q   # 79 passed

# полный прогон (from_snapshot):
cd test-todo
export CLINE_API_KEY="21dbd6...FkmS" ZAI_BUSINESS_BASE_URL="https://api.zai" \
       ZAI_OAUTH_ORIGIN="https://chat.z.ai" ZAI_OAUTH_CLIENT_ID="client_..."
PYTHONPATH=../src python -m microcode.cli apply platform.yaml --prd src/PRD.md

# UI:
# http://localhost:8000      — todo app
# http://localhost:57374     — loki dashboard (Lab tab для новых задач)
```

Гайды: `docs/extending-loki.md`, `examples/cline-multi-skills/README.md`,
`ARCHITECTURE.md`.
