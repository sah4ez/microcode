# Пример: todo-сервис через provider cline + GLM (z.ai)

Полноценный пример платформы **microcode**: один манифест `platform.yaml`
описывает три аспекта разработки (навыки, оркестрацию агентов, среду исполнения),
а `microcode apply` выполняет весь путь end-to-end — поднимает микро-VM,
готовит окружение, запускает loki-mode с провайдером **cline** на модели
**GLM (z.ai)** и сохраняет результат в примонтированный `src/`.

```
platform.yaml  ──(microcode apply)──►  debian micro-VM
                                            │  bootstrap.sh: node + loki + cline
                                            │  node-shim /usr/local/bin/cline
                                            ▼
                                  loki --provider cline  (внутри VM)
                                            │  GLM через z.ai OAuth
                                            ▼
                                  todo-сервис в src/  (на хосте)
```

## Что понадобится на хосте

```bash
# инструменты (проверяются microcode doctor)
which msb skillkit loki node        # microsandbox, skillkit, loki-mode, node

# окружение с microcode
cd <repo-microcode>
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Секреты z.ai

В манифесте секретов **нет** — они передаются по имени env-переменной.
Нужны 4 переменных (loki_runner пробрасывает их в VM через `msb exec -e`):

```bash
export GLM_API_KEY="..."                 # токен z.ai / GLM
export ZAI_BUSINESS_BASE_URL="https://api.z.ai"
export ZAI_OAUTH_CLIENT_ID="..."         # OAuth client id z.ai
export ZAI_OAUTH_ORIGIN="..."            # OAuth origin z.ai
```

> Почему именно OAuth, а не raw api-key: cline имеет встроенный провайдер
> `zai-coding-plan`, который ходит на **coding**-endpoint z.ai через OAuth.
> Прямой raw-key на `/api/paas/v4` даёт «Insufficient balance», а Anthropic-compat
> `/api/anthropic` работает только для некоторых моделей. OAuth-провайдер —
> единственный стабильно рабочий путь для cline + GLM.

## Шаг 0. Навыки (один раз)

Скиллы `obra/superpowers` — аналоги доменов loki-mode (планирование, TDD,
дебаггинг, code-review). Ставим под целевого агента `cline`:

```bash
cd examples/todo-api-cline
skillkit install obra/superpowers \
  --skills writing-plans,executing-plans,test-driven-development,\
systematic-debugging,requesting-code-review \
  --agent cline --yes --no-scan
```

Они лягут в `src/.cline/skills/` и будут видны loki внутри VM через mount.
Поэтому в манифесте `skills.enabled: false` (провижнинг уже сделан вручную).

## Шаг 1. Посмотреть план (ничего не выполняется)

```bash
microcode plan platform.yaml --prd src/PRD.md
```

Вывод: список артефактов (`.skills`, `loki-config.yaml`, `loki.env`,
`bootstrap.sh`) и команд (`msb create`, `msb exec bootstrap`, `loki start`).
Также показывается сгенерированный `bootstrap.sh`.

## Шаг 2. Применить (полный путь)

```bash
microcode apply platform.yaml --prd src/PRD.md
```

Что происходит по порядку (всё — оркестратором, без ручных `msb`):

1. **doctor** — проверяет `msb` и `skillkit` на хосте.
2. **plan + artifacts** — генерирует `bootstrap.sh`, `loki-config.yaml`,
   `loki.env`, `.skills` и копирует `cline-node-shim.cjs` в `.microcode/artifacts/`.
3. **`msb create debian:bookworm-slim`** — поднимает VM с allowlist-сетью
   и **двумя rootfs-patch'ами**: `bootstrap.sh` + `cline-node-shim.cjs`.
4. **`msb exec bash bootstrap.sh`** — ставит node (через `n`), npm, loki-mode,
   cline и **создаёт wrapper `/usr/local/bin/cline` → node-shim**.
5. **`msb exec --user loki ... loki start --provider cline src/PRD.md`** —
   loki читает PRD и строит todo-сервис в `src/`, вызывая cline (→ GLM).

## Шаг 3. Проверить результат

```bash
cd src
pip install -r requirements.txt
python -m todo_service &        # поднимется на 127.0.0.1:8000
curl -s -X POST localhost:8000/todos -H 'Content-Type: application/json' \
  -d '{"title":"купить молоко"}'
curl -s localhost:8000/todos     # [{"id":1,"title":"купить молоко",...}]
```

SQLite-файл `data/todos.db` — локальное хранилище, переживает рестарт сервера.

## Шаг 4. Снести

```bash
microcode destroy platform.yaml   # msb stop/rm + чистка .microcode
```

---

## Ключевые обходные пути (вшиты в генераторы microcode)

Эти решения найдены при отладке на arm64 microsandbox VM и зафиксированы в
генераторах, чтобы `microcode apply` был самодостаточным.

### 1. cline падает на arm64 → node-shim через `@cline/core`
cline CLI — это **Bun-compiled native binary**. На arm64 microsandbox VM он
падает с `Bus error` в JIT (проверено на node 18/22.5/22.11/22.20/22.23,
с/без ASLR). Под qemu-user — `Segfault`.

Решение: `cline-node-shim.cjs` запускает cline через чистый-JS `@cline/core`
SDK под node, **без Bun**. Корневая находка: провайдер `zai-coding-plan` +
`ZAI_OAUTH_*` env-vars — тогда `ClineCore.create()` → `cline.start()` →
**`cline.send()`** запускает agent LLM tool-use loop (без `send()` loop молчит).
bootstrap ставит wrapper `/usr/local/bin/cline` → shim, и loki не замечает
подмены.

### 2. apt роняет overlay-FS → tmpfs-кэш
CoW-overlay microsandbox периодически роняет apt на `rename failed`.
Решение: bootstrap редиректит кэш apt в `/tmp` (tmpfs):
`Dir::Cache::Archives "/tmp/apt-cache/archives"`. И **без `-qq`** (он маскировал
прогресс и оставлял dpkg-lock занятым).

### 3. node через `n`, а не NodeSource / прямой tarball
NodeSource-apt-репо в VM ненадёжно (GPG-key не fetched, иногда ставит node без
npm). Прямой tarball с nodejs.org таймаит на больших файлах. Решение: ставим
debian-`nodejs` (быстро) + npm из маленького tarball (3 МБ) + апгрейдим node
через `n install 22` (роьет надёжнее).

### 4. Непривилегированный пользователь `loki`
claude/cline CLI отказываются работать с `--dangerously-skip-permissions` под
root. Решение: bootstrap создаёт пользователя `loki`, выставляет PATH в его
`.bashrc`, а `loki_runner` запускает `loki start` через `--user loki` с явным
`export PATH=/opt/npm-global/bin:...` (non-root login-shell может не читать
`.bashrc`).

### 5. Внешняя память loki → named volume
Память learnings loki (`~/.loki`) теряется между запусками VM. Решение:
`loki.memory.storage.enabled: true` монтирует named-volume и выставляет
`LOKI_MEMORY_BASE_PATH` — learnings персистентны на хосте.

### 6. Сеть: allowlist + порт 80 для apt
`mode: allowlist` (deny-by-default). Debian bookworm sources используют **http
(порт 80)**, поэтому apt-зеркала разрешены и на 80, и на 443. DNS microsandbox
резолвит автоматически — явное `allow@dns` правило **не нужно** (и msb его
отклоняет).

---

## Структура примера

```
todo-api-cline/
├── platform.yaml        # единый манифест (навыки + loki + sandbox)
├── README.md            # этот файл
└── src/
    ├── PRD.md           # спецификация todo-сервиса (читает loki)
    └── .cline/skills/   # скиллы obra/superpowers (после шага 0)
```

После `microcode apply` в `src/` появятся:
```
src/todo_service/{app,db,models,schemas,__main__}.py
src/tests/test_todos.py
src/requirements.txt, src/README.md
src/data/todos.db        # локальная SQLite
```
