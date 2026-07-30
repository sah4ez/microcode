# MEMORY — контекст проекта microcode

> Снимок состояния работы на 2026-07-30. Этот файл — чтобы быстро войти в
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

`microcode apply` оркестрирует весь путь: doctor → plan → artifacts → `msb create`
(debian) → `msb exec bootstrap.sh` → `msb exec loki start` — без ручных msb.

## Текущее состояние (ДОКАЗАНО)

- **Todo-сервис построен через `provider cline` + GLM/z.ai** внутри microcode VM.
  agent.log: `Provider: cline`, `RARV Phase: REFLECT`. Сервис в `src/` работает:
  CRUD + toggle, SQLite `data/todos.db` переживает рестарт.
- **`microcode apply` end-to-end** проходит полностью (без ручных msb):
  `[bootstrap] cline node-shim installed`, `[bootstrap] done.`, затем loki start.
- **Тесты: 51/51 зелёные.**
- Все 4 примера валидны: minimal, allowlist, full-stack, todo-api-cline.
- Всё запушено в `origin/master` (github.com:sah4ez/microcode.git), последний
  коммит `9c24d2b`.

## Ключевое достижение: cline работает без Bun через node-shim

**Проблема:** cline CLI — это Bun-compiled native binary. На arm64 microsandbox
VM он падает с **Bus error** в JIT (проверено: node 18/22.5/22.11/22.20/22.23,
с/без ASLR). Под qemu-user — Segfault. На хосте (macOS arm64) работает только
через darwin-x86_64 binary под Rosetta.

**Решение:** `src/microcode/assets/cline-node-shim.cjs` — запускает cline через
чистый-JS `@cline/core` SDK под node, **без Bun**. Корневые находки реверса
core-API:
- провайдер `zai-coding-plan` + **`ZAI_OAUTH_*` env-vars** (coding-endpoint z.ai,
  OAuth, не raw api-key — paas/v4 даёт «Insufficient balance»);
- `ClineCore.create()` → `cline.start({config, prompt})` → **`cline.send()`**
  запускает agent LLM tool-use loop (без `send()` loop молчит — только
  session_snapshot/status);
- core предоставляет tools (read/write/exec) → cline делает file-операции.

bootstrap ставит wrapper `/usr/local/bin/cline` → shim, loki не замечает подмены.

## Найденные обходы (вшиты в генераторы microcode)

1. **cline arm64 Bun crash** → node-shim через `@cline/core` (см. выше).
2. **apt роняет overlay-FS** (`rename failed`) → tmpfs apt-cache
   (`Dir::Cache::Archives "/tmp/apt-cache/archives"`) + **без `-qq`**
   (маскировал прогресс, оставлял dpkg-lock занятым).
3. **node через `n`**, не NodeSource (GPG не fetched) и не прямой tarball
   (nodejs.org таймаит на больших файлах): debian-`nodejs` + npm-tarball (3 МБ)
   + `n install 22`.
4. **Непривилегированный пользователь `loki`**: claude/cline отказываются с
   `--dangerously-skip-permissions` под root. bootstrap создаёт `loki` + PATH в
   `.bashrc`; `loki_runner` запускает через `--user loki` с явным
   `export PATH=/opt/npm-global/bin:...` (non-root login-shell может не читать
   `.bashrc`).
5. **Внешняя память loki** → named volume + `LOKI_MEMORY_BASE_PATH`
   (`loki.memory.storage`). learnings переживают destroy/recreate VM.
6. **Сеть allowlist + порт 80** для apt (bookworm использует http). DNS
   microsandbox резолвит авто — `allow@dns` правило **не нужно** (msb его
   отклоняет: "dns target supports tcp/udp/any").
7. **`skills.enabled: false`** + точечный translate по имени с `--force`
   (`--all` падал на коллизиях с глобальными скиллами).
8. **env-substitution** `${VAR}` в `sandbox.env` (секреты по имени, не инлайн).
9. **VM create от root**, loki start от `loki` (sandbox.user=root для create/init,
   т.к. пользователь `loki` появляется только в bootstrap — иначе msb create с
   `--user loki` падает "guest user not found").

## Архитектура (где что)

```
src/microcode/
├── manifest.py            # pydantic-схема (навыки/loki/sandbox + NetRule, LokiMemoryStorage)
├── generators/            # манифест → артефакты (чистые функции)
│   ├── bootstrap.py       # → bootstrap.sh (tmpfs, node-via-n, unzip, user loki, cline shim wrapper)
│   ├── net.py             # rule_token/suffix_token/network_argv (3 режима сети)
│   ├── skills.py          # → .skills + skillkit cmds (enabled, translate по имени + force)
│   ├── loki.py            # → loki-config.yaml + loki.env (LOKI_MEMORY_BASE_PATH если storage)
│   └── sandbox.py         # → msb create/exec/snapshot (+авто-volume для memory)
├── runners/               # тонкие CLI-обёртки (dry-run)
│   ├── sandbox_runner.py  # resolve bootstrap.sh + inject cline-node-shim.cjs как 2й --copy-file
│   └── loki_runner.py     # bash -lc, --user loki, -e секреты + LOKI_MEMORY_BASE_PATH, --provider
├── orchestrator.py        # write_artifacts (копирует shim-asset) + apply/destroy
├── planner.py             # детерминированный Plan
├── assets/cline-node-shim.cjs   # ★ node-shim cline через @cline/core
└── cli.py                 # typer: validate/plan/apply/destroy/show/doctor
templates/, examples/, tests/, platform.yaml, platform.schema.json
todo-run/                   # реальный прогон: platform.yaml + PRD + .cline/skills + результат
```

## Сеть провайдера (z.ai) — что работает, что нет

- ✅ **cline `zai-coding-plan` + OAuth** (`ZAI_OAUTH_*`) → coding-endpoint, GLM-4.6
  работает через node-shim (доказано: `text=SHIM_OK`, file-операции).
- ✅ z.ai **Anthropic-compat** `/api/anthropic` (curl: полный SSE
  message_start→...→message_stop для glm-4.6). Используется claude-code CLI.
- ❌ z.ai **OpenAI-compat** `/api/paas/v4` → «Insufficient balance» (другой биллинг).
- ❌ raw apiKey для `zai-coding-plan` → «Model returned empty response» (нужен OAuth).

## Не сделано / ограничения

- Автотесты сгенерированного todo-сервиса падают на `httpx 0.27` ASGITransport
  API (minor-баг пина в сгенерированном коде). Реальные HTTP-запросы работают.
- bootstrap на arm64 VM медленный (~30 мин): nodejs.org прямые下载 тайматят,
  `n` вытягивает, но долго. Snapshot-кэш (`init.snapshot.enabled`) смягчает.
- `loki.memory` run-state (`todo-run/.loki/memory/`) — gitignored, это run-state,
  не «ценная» память (patterns пустые). Реальная кросс-проектная память — через
  named-volume (storage), не в репо.

## Как возобновить

```bash
cd /Users/aleksandrkozlenkov/git/microcode
source ~/miniconda3/etc/profile.d/conda.sh; conda activate mcd
python -m pytest -q                                   # 51 passed
microcode validate examples/todo-api-cline/platform.yaml
# полный прогон:
cd examples/todo-api-cline
export GLM_API_KEY=... ZAI_BUSINESS_BASE_URL=... ZAI_OAUTH_CLIENT_ID=... ZAI_OAUTH_ORIGIN=...
microcode apply platform.yaml --prd src/PRD.md
```

Подробный гайд со всеми обходами — `examples/todo-api-cline/README.md`.
Дизайн-док — `ARCHITECTURE.md` (включая секцию "cline provider limitation").
