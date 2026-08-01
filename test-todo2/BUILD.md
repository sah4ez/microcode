# Сборка Go+tg v3 todo-сервиса — пошаговая инструкция

Ручная сборка сервиса по PRD-001 (рефакторинг Python todo в Go на
`github.com/seniorGolang/tg/v3` + go-fiber + SQLite) через `microcode`.
Рассчитана на выполнение с нуля, с проверкой каждого этапа.

> Все команды — из корня репозитория `microcode`. `msb` должен быть на PATH
> (`export PATH="$HOME/.microsandbox/bin:$PATH"`).

## 0. Предусловия

```bash
cd <путь>/microcode
export PATH="$HOME/.microsandbox/bin:$PATH"     # msb CLI
export CLINE_API_KEY="<твой ключ z.ai>"          # секрет, не в манифесте
# при необходимости:
export ZAI_BUSINESS_BASE_URL="https://api.z.ai"
export ZAI_OAUTH_ORIGIN="https://chat.z.ai"
export ZAI_OAUTH_CLIENT_ID="client_..."
```

Проверка: `msb list` отвечает, `.venv/bin/microcode --help` работает, `go version`
на хосте ≥ 1.26 (для кросс-компиляции пропатченного tg, см. шаг 3).

## 1. Снять VM с прошлого запуска (если была)

```bash
msb rm -f notes-build 2>/dev/null
rm -rf ~/.microsandbox/sandboxes/notes-build
msb list                  # должно быть пусто / "No sandboxes found"
```

## 2. Собрать базовый образ (snapshot) — один раз

Это ставит Go 1.26, tg v3, cline, loki, skillkit, **и плагины tgp-go (astg +
server)**. Долго (~25 мин): apt + node + npm-global + bun + cline + extra_shell
(Go toolchain + tg + plugins). Запускай и жди завершения.

```bash
# build.yaml уже в режиме BUILD (snapshot.enabled: true, from_snapshot закомментирован)
grep -A2 "snapshot:" test-todo2/build.yaml | head -4

.venv/bin/microcode build test-todo2/build.yaml --skip-doctor
```

Что происходит внутри (extra_shell):
1. качает Go 1.26.5 с `go.dev` → `/usr/local/go`;
2. `go install github.com/seniorGolang/tg/v3/cmd/tg@latest`;
3. `tg pkg add ...:astg` + `...:server` (WASM-плагины кодегена);
4. **если шаг 3 падает на `Failed to extract archive ...-skills.tar.gz: EOF`**
   (известный race-condition в tg, см. `custom-skills/tg-patch/README.md`) —
   extra_shell клонирует tg v3.0.5, подкладывает пропатченный `install.go`
   (`custom-skills/tg-patch/install.go.patched`), кросс-компилирует под
   linux/arm64 и повторяет `tg pkg add`.

Проверка результата:
```bash
msb snapshot list                          # mcd-base присутствует, свежий digest
```

> Если хочется быстрее и ты уже собирал snapshot раньше — можно пропустить и
> сразу к шагу 4 (apply из `from_snapshot`).

## 3. (Опционально) Ручная проверка tg-плагинов в собранной VM

Если хочешь убедиться, что codegen работает, перед запуском loki:

```bash
msb run --from-snapshot mcd-base --name notes-check --detach --replace
msb exec notes-check --user root -- bash -lc '
  export PATH=/usr/local/go/bin:/usr/local/bin:/root/go/bin:$PATH HOME=/root
  echo "go:   $(go version)"
  echo "tg:   $(tg --version 2>&1 | head -1)"
  echo "plugins:"; tg pkg list 2>&1 | grep -E "astg|server"
'
msb rm -f notes-check
```

Ожидаемо: `astg v1.0.8` и `server v1.0.8`, оба с `✓`.

## 4. Переключить build.yaml в режим APPLY (boot из snapshot)

В `test-todo2/build.yaml`, секция `snapshot:`:

```yaml
    snapshot:
      # --- APPLY mode: boot from the pre-built snapshot ---
      from_snapshot: mcd-base
      # --- BUILD mode (закомментируй при apply) ---
      # enabled: true
      name: mcd-base
```

Проверь:
```bash
.venv/bin/microcode validate test-todo2/build.yaml   # ✓ valid
```

## 5. Запустить loki на сборку Go-сервиса

```bash
.venv/bin/microcode apply test-todo2/build.yaml --prd src/PRD-001.md --skip-doctor
```

Это:
1. boot из `mcd-base` (быстро, ~секунды);
2. seed named-volume `/workspace` из хостового `./src` (tar-merge: только PRD,
   без stale-файлов от прошлых запусков);
3. skillkit install+translate (obra/superpowers → cline-скиллы);
4. `loki start ... PRD-001.md` — RARV-цикл (cline + GLM-5.2).

`--prd src/PRD-001.md` автоматически мапится в `/workspace/PRD-001.md` внутри VM
(`_resolve_prd_guest_path` в `loki_runner.py`). Запуск долгий (десятки минут),
лучше в background:

```bash
nohup .venv/bin/microcode apply test-todo2/build.yaml --prd src/PRD-001.md \
      --skip-doctor > /tmp/apply.log 2>&1 &
```

## 6. Мониторинг прогресса loki

```bash
# текущая фаза + метрики
.venv/bin/microcode status test-todo2/build.yaml

# напрямую в VM:
msb exec notes-build --user loki -- bash -lc \
  'cat /workspace/.loki/state/orchestrator.json'
msb exec notes-build --user loki -- bash -lc \
  'cd /workspace && git log --oneline -10'      # коммиты = завершённые задачи

# появление .go-файлов = идёт разработка:
msb exec notes-build --user loki -- bash -lc \
  'find /workspace -name "*.go" -not -path "*/.loki/*" | head'
```

loki dashboard (если включён `loki.dashboard`): http://localhost:57374

Подкорректировать loki в процессе (асинхронная директива):
```bash
.venv/bin/microcode steer test-todo2/build.yaml "Используй modernc.org/sqlite, не mattn"
```

## 7. Проверка результата (Definition of Done из PRD-001)

После завершения apply проверь прямо в VM:

```bash
msb exec notes-build --user loki -- bash -lc '
  export PATH=/usr/local/go/bin:/home/loki/go/bin:/opt/npm-global/bin:$PATH
  cd /workspace
  echo "=== go vet ===";  go vet ./...   && echo "VET OK"
  echo "=== go build ==="; go build ./... && echo "BUILD OK"
  echo "=== go test ==="; go test ./...   # все 6 эндпоинтов + persistence-restart
'
```

Smoke-тест через curl (Definition of Done: «curl examples in README work»):
```bash
# поднять сервер
msb exec notes-build --user loki -- bash -lc \
  'export PATH=/usr/local/go/bin:$PATH; cd /workspace; go run ./cmd/server' &
sleep 3
curl -s -X POST localhost:8000/todos -H "Content-Type: application/json" \
     -d "{\"title\":\"test\",\"description\":\"d\"}"   # → 201 + {id,created_at,completed:false}
curl -s localhost:8000/todos                            # → [ {...} ]
msb exec notes-build --user root -- bash -lc \
  'for p in $(ls /proc/[0-9]*/cmdline 2>/dev/null | xargs grep -l "cmd/server" 2>/dev/null); do kill ${p#/proc/}; done'
```

Persistence-restart (Definition of Done: «./data/todos.db survives a restart»):
создать todo, остановить сервер, поднять заново, `GET /todos` — todo на месте.

Результат зеркалится на хост в `test-todo2/src/` (named volume `/workspace`).

## 8. Откат / повтор

```bash
# откатить loki к git-checkpoint
.venv/bin/microcode rollback test-todo2/build.yaml

# полный пересбор с нуля
.venv/bin/microcode destroy test-todo2/build.yaml     # msb rm notes-build
# и снова с шага 2 (build) или 5 (apply из существующего snapshot)
```

## Краткая шпаргалка

| Что | Команда |
|---|---|
| собрать образ | `microcode build test-todo2/build.yaml --skip-doctor` |
| переключить в apply | в build.yaml: `from_snapshot: mcd-base`, `# enabled: true` |
| запустить loki | `microcode apply test-todo2/build.yaml --prd src/PRD-001.md --skip-doctor` |
| статус | `microcode status test-todo2/build.yaml` |
| подкорректировать | `microcode steer test-todo2/build.yaml "..."` |
| откатить | `microcode rollback test-todo2/build.yaml` |
| проверить | `go vet ./... && go test ./...` в VM |

## Известные подводные камни

- **`tg pkg add ... EOF`** — race в загрузчике tg (возвращает до flush файла).
  В build.yaml уже авто-патчится (clone v3.0.5 → cp patched install.go →
  cross-compile → retry). Если патч не сработал — см. `custom-skills/tg-patch/`.
- **`lookup storage.googleapis.com: no such host`** при `go install tg` — модуль
  `cloudflare/circl` (через go-git) отдаётся только с GCS. Уже в allowlist.
- **npm `ECONNRESET`/`EIDLETIMEOUT`** на `cline` — флапающая сеть VM↔registry.
  extra_shell повторяет npm-install; при ручной сборке просто перезапусти
  `microcode build`.
- **`PRD file not found`** — забытый `--prd src/PRD-001.md` или путь не под
  монтируемой `./src`. path-резолвер в loki_runner мапит `src/X` → `/workspace/X`.
- **loki висит** на multi-agent команде (parallel sub-agents + большие промпты
  к GLM) — долго, но не зависание. Подождать или подкорректировать сужением
  `loki.effort: low` / `max_iterations`.
