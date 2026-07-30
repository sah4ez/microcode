# Пример: cline + несколько skill-провайдеров внутри VM

Полноценный пример платформы **microcode**: один манифест `platform.yaml`
описывает три аспекта разработки — **навыки**, **оркестрацию**, **среду** — а
`microcode apply` выполняет весь путь end-to-end:

- поднимает микро-VM (stock `debian`);
- ставит окружение (`bootstrap.sh`: node + loki-mode + cline + node-shim);
- устанавливает **скиллы из разных источников ВНУТРИ VM** (`skills.in_vm`):
  obra/superpowers с GitHub (через skillkit) + локальные overlay-модули;
- запускает loki-mode с провайдером **cline** на модели **GLM (z.ai)**;
- loki читает наш overlay индекс скилл-модулей и строит notes-API;
- результат сохраняется в примонтированный `src/` (виден на хосте).

```
platform.yaml
   │  microcode apply
   ├─[skills, in VM]  skillkit install obra/superpowers ... --agent cline
   │                  + translate → cline SKILL.md в skills/
   ├─[overlay]        ./custom-skills → /workspace/skills  (mount)
   ├─[sandbox]        msb create debian + bootstrap.sh
   └─[loki, in VM]    loki --provider cline --model glm-5.2 PRD.md
                        читает skills/00-index.md (наш overlay)
                        → notes-API в /workspace (= src/ на хосте)
```

> Как расширять/заменять навыки и фазы SDLC — см.
> [`../../docs/extending-loki.md`](../../docs/extending-loki.md).

---

## Что демонстрирует этот пример

| Возможность | Где в манифесте |
|---|---|
| Скиллы **из GitHub** (obra/superpowers) | `skills.install: source: obra/superpowers` |
| Скиллы **внутри VM** (не на хосте) | `skills.in_vm: true` |
| **Локальные overlay-модули** loki (custom-skills/) | `sandbox.mounts: ./custom-skills → /workspace/skills` |
| **Кастомные правила** (TDD/security/API-contract) | `custom-skills/*.md` + `00-index.md` |
| provider **cline** + GLM | `loki.provider: cline`, `loki.model: glm-5.2` |
| **Суженный SDLC** (6 фаз) | `loki.effort: standard` |
| **Кастомные гейты** (выключен magic_debate) | `loki.quality_gates.opt_out` |
| **Кросс-проектная память** (volume) | `loki.memory.storage.enabled` |
| **Allowlist-сеть** (только нужные хосты) | `sandbox.network.mode: allowlist` |

---

## Структура примера

```
cline-multi-skills/
├── platform.yaml            # единый манифест (3 аспекта)
├── custom-skills/           # overlay скилл-модули loki (примонтируются в VM)
│   ├── 00-index.md          # индекс: копия таблицы loki + наши строки
│   ├── tdd-rules.md         # доп.: строгий RED-GREEN-REFACTOR
│   ├── security-checks.md   # доп.: security-скан перед QA
│   └── api-contract-rules.md# доп.: единый стиль HTTP-API
└── src/
    └── PRD.md               # спецификация notes-API (вход loki)
```

---

## Что понадобится на хосте

```bash
which msb skillkit node      # microsandbox, skillkit, node
# microcode установлен (из корня репо):
#   conda env create -f environment.yml && conda activate mcd
```

**Секреты z.ai (НЕ в манифесте!)** — передаются через окружение,
microcode прокидывает их в VM через `msb exec -e`:

```bash
export ZAI_BUSINESS_BASE_URL="https://api.z.ai"
export ZAI_OAUTH_ORIGIN="https://chat.z.ai"
export ZAI_OAUTH_CLIENT_ID="client_P8X5CMWmlaRO9gyO-KSqtg"   # твоё значение
```

---

## Запуск end-to-end

```bash
# 0. из корня репо microcode, с активированным окружением mcd
conda activate mcd

# 1. экспортировать секреты (выше)

# 2. посмотреть план (dry-run) — все msb/skillkit команды без выполнения
microcode plan examples/cline-multi-skills/platform.yaml

# 3. выполнить
microcode apply examples/cline-multi-skills/platform.yaml
```

Что произойдёт по фазам `apply`:

1. **doctor** — проверяет `msb` (skillkit не нужен на хосте — он в VM).
2. **plan + artifacts** — генерирует `loki-config.yaml`, `loki.env`, `bootstrap.sh`.
3. **sandbox create + bootstrap** — `msb create debian` с `--copy-file bootstrap.sh`
   и `--copy-file cline-node-shim.cjs`, затем `msb exec ... bash bootstrap.sh`
   ставит node/loki/cline/shim.
4. **skills (внутри VM)** — `msb exec notes-build --user loki -- bash -lc
   '... skillkit install obra/superpowers ... --agent cline'` + translate
   (скиллы попадают в `/workspace/skills/` рядом с overlay).
5. **loki (внутри VM)** — `msb exec ... loki start --config ... --provider cline
   --model glm-5.2 ... PRD.md`. Loki читает `skills/00-index.md` (наш overlay),
   грузит tdd-rules + api-contract-rules по фазе, строит notes-API.

---

## Проверка результата

После завершения `apply` notes-API будет в `src/` на хосте:

```bash
# тесты (если loki их написал)
cd examples/cline-multi-skills/src && pytest -q

# запустить сервер
uvicorn main:app --host 0.0.0.0 --port 8000 &

# smoke-тест
curl -s localhost:8000/notes
curl -s -X POST localhost:8000/notes -H 'Content-Type: application/json' \
     -d '{"title":"hello","body":"from microcode"}'
curl -s localhost:8000/notes
```

---

## Как скилл-провайдеры комбинируются

В этом примере навыки приходят из **двух независимых источников**:

### (1) GitHub-source через skillkit (`skills.install`)
obra/superpowers — публичный репо. skillkit (внутри VM) клонирует выбранные
скиллы (`test-driven-development`, `systematic-debugging`, ...) и переводит их
под формат **cline** (`--agent cline`). Переведённые `SKILL.md` попадают в
`skills/` (та же папка, что overlay).

### (2) Локальные overlay-модули loki (`custom-skills/` → mount)
Это не skillkit-скиллы, а **Markdown-модули loki** (инструкции по фазе задачи).
Монтируются напрямую через `sandbox.mounts`. loki читает `00-index.md` и грузит
модули (`tdd-rules.md`, `security-checks.md`, `api-contract-rules.md`) по таблице
«task involves → load these modules».

> Оба источника оказываются в `/workspace/skills/` внутри VM — loki видит их
> вместе. Overlay-`00-index.md` индексирует и те, и другие.

### Другие поддерживаемые skill-провайдеры

Поле `skills.install[].source` принимает (тип `Provider`):

| source | пример | что делает skillkit |
|---|---|---|
| GitHub repo | `obra/superpowers` | клонирует/тянет скиллы |
| GitHub gist | gist URL | ставит скилл из gist |
| local path | `./my-local-skills` | копирует локальные скиллы |
| marketplace | имя из registry | ставит из registry |

Можно добавить несколько `install`-записей — каждая со своим `source`:

```yaml
skills:
  install:
    - source: obra/superpowers           # GitHub
      skills: [test-driven-development]
    - source: ./my-local-skills          # локальная папка
      skills: [my-domain-rules]
```

---

## Известные ограничения / обходы

1. **cline Bun-краш на arm64.** cline CLI — это нативный Bun-бинар; на arm64
   microsandbox VM падает (bus error). microcode обходит это: `bootstrap.sh`
   ставит `@cline/core` и кладёт node-shim в `/usr/local/bin/cline` (чистый JS,
   без Bun). Подробности — в `ARCHITECTURE.md` "cline provider limitation".
2. **z.ai OAuth, не сырой ключ.** Провайдер `zai-coding-plan` требует
   `ZAI_OAUTH_*` (OAuth-flow), а не один `apiKey` — сырой ключ даёт
   "Insufficient balance".
3. **Allowlist-сеть.** VM ходит только к явно разрешённым хостам
   (`api.z.ai`, npm, github, apt, nodejs.org). DNS auto-allowed microsandbox.
4. **Bootstrap медленный (~20-30 мин на arm64)** при первом запуске — ставит
   node + loki + cline + @cline/core. Повторные запуски можно ускорить через
   `sandbox.init.snapshot.enabled: true`.

---

## Разбор: как настроить свой вариант

- **Заменить набор скиллов** — отредактируй `skills.install[].skills`.
- **Добавить свои правила** — положи `.md` в `custom-skills/` + строку в
  `00-index.md` (см. шаблон в `docs/extending-loki.md`).
- **Сузить SDLC** — `loki.effort: low` (3 фазы) или `standard` (6).
- **Сменить модель** — `loki.model: glm-4.6` (или любую доступную z.ai).
- **Выключить гейт** — добавь в `loki.quality_gates.opt_out`.
- **Другой провайдер loki** — `loki.provider: claude` (+ `provider_clis: [claude]`).
