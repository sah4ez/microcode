# Расширение и замена навыков loki; предопределение фаз SDLC

loki-mode — автономный spec-driven build-loop (RARV-C: **R**eason-**A**ct-
**R**eflect-**V**erify-**C**ompound), покрывающий весь SDLC. В microcode loki
работает **внутри** микро-VM (stock `debian`), а его знания и поведение
настраиваются тремя независимыми слоями. Этот документ описывает, как каждый
слой расширять, заменять и комбинировать.

---

## Три слоя знаний/управления loki

| Слой | Что это | Где живёт | Как меняется |
|---|---|---|---|
| **1. Скилл-модули** | Markdown-инструкции, грузимые по фазе задачи | `skills/*.md` (внутри VM — примонтированная папка) | добавить/переопределить `.md` + индекс |
| **2. Фазы SDLC** | state-machine: BOOTSTRAP→DISCOVERY→…→GROWTH | захардкочена в `SKILL.md` loki | сузить через `effort`; дополнить через модули; гейты через манифест |
| **3. Манифест microcode** | провайдер, модель, гейты, бюджет, env | `platform.yaml` | декларативные поля `loki.*` |

**Принцип:** слои 1 и 2 — это «мягкое» управление через Markdown + env (без
кода); полный state-machine фаз (слой 2) можно сузить, но не переписать — его
дополняют скилл-модулями и регулируют гейтами из слоя 3.

---

## Слой 1. Скилл-модули loki

Loki грузит инструкции **модульно, по текущей фазе**. Это не код, а Markdown,
который loki читает как контекст перед действиями.

### Механика загрузки (из `00-index.md` + `SKILL.md`)

1. При старте сессии loki читает `skills/00-index.md` (индекс, один раз).
2. Каждый ход грузит **1–2 модуля**, соответствующих текущей задаче/фазе, по
   таблице «task involves → load these modules».
3. Модули лежат в директории `skills/` — внутри VM это примонтированная папка.

Встроенные модули loki: `model-selection`, `testing`, `quality-gates`,
`production`, `troubleshooting`, `agents`, `artifacts`, `parallel-workflows`,
`github-integration`, `compound-learning`, `memory`, `healing`, `providers`,
`documentation`, `magic-modules`, `patterns-advanced` и др.

### Расширить — добавить свой модуль

1. Создай Markdown-файл с правилами для твоего домена:

```markdown
<!-- custom-skills/payment-rules.md -->
### payment-rules.md
**When:** Writing payment/refund code, DEVELOPMENT phase
- All money math via Decimal, never float
- Refunds require an idempotency key
- Log every state transition to the audit table
- Never expose raw card numbers in logs/errors
```

2. Положи его в папку skills через mount в манифесте:

```yaml
sandbox:
  mounts:
    - { host: ./custom-skills, dest: /workspace/skills, readonly: false }
```

3. Зарегистрируй в индексе — добавь строку в `custom-skills/00-index.md`
   (см. шаблон ниже), чтобы loki знал, когда его грузить.

### Заменить — переопределить существующий модуль

Loki грузит модули по имени файла. Если в примонтированной `skills/` есть файл
с тем же именем (например `testing.md`), он перекрывает встроенный:

```
custom-skills/
├── 00-index.md          # индекс: копия loki-индекса + твои строки
├── testing.md           # твоя версия заменяет встроенную
└── payment-rules.md     # новое
```

> **Важно:** loki читает из **одной** директории skills. Чтобы твои модули и
> встроенные сосуществовали, твоя overlay-папка должна содержать копию
> `00-index.md` + твои дополнения/переопределения. При полном совпадении имён
> файлов — твой файл выигрывает.

### Шаблон `00-index.md` (overlay)

```markdown
# Skill Modules Index

Load 1-3 modules based on your current task. Do not load all modules.

## Module Selection Rules

| If your task involves...          | Load these modules              |
|-----------------------------------|---------------------------------|
| Writing code, implementing        | model-selection.md              |
| Running tests, E2E                | testing.md                      |
| Code review, quality checks       | quality-gates.md                |
| Debugging, errors, failures       | troubleshooting.md              |
| Payment/refund code               | payment-rules.md                |  <!-- новое -->
| Architecture decisions            | patterns-advanced.md            |

## How to Load
1. Read this index.
2. Pick 1-2 modules matching the current phase/task.
3. Read those files.
4. Execute with loaded context.
```

---

## Слой 2. Фазы SDLC

Фазы — это конечный автомат, который loki проходит:

```
BOOTSTRAP → DISCOVERY → ARCHITECTURE → DEEPEN_PLAN → INFRASTRUCTURE
         → DEVELOPMENT → QA → DEPLOYMENT → GROWTH
```

Переходы **гейтированные**: «All phase quality gates passed. No Critical/High
issues» (`SKILL.md:132`). Сам state-machine захардкочен в `SKILL.md` loki.

### Сузить SDLC через тир сложности

`loki.effort` управляет числом фаз:

| effort | tier | фаз | особенности |
|---|---|---|---|
| `low` | simple | 3 | без DEEPEN_PLAN, минимальный цикл |
| `standard` | standard | 6 | с DEEPEN_PLAN (4 research-агента) |
| `high` | complex | 8 | полный SDLC, все фазы |

```yaml
loki:
  effort: low        # 3 фазы, без DEEPEN_PLAN — быстро для простых задач
```

### Дополнить фазу — через скилл-модуль

Фаза — это набор инструкций в RARV-цикле. Дополнить поведение фазы = дать loki
доп. инструкции через модуль, срабатывающий по фазе. Например, обязательный
security-скан перед переходом в QA:

```markdown
<!-- custom-skills/security-checks.md -->
### security-checks.md
**When:** DEVELOPMENT phase, before QA transition
- Run `semgrep --config=auto` on changed files
- Block the transition if HIGH/CRITICAL findings exist
- Log results to .loki/proofs/<run>/security.json
- If semgrep is unavailable, fall back to `grep -rE "(password|secret|token)" src/`
```

### Предопределить начальную фазу / пропустить фазы

Через `config_overrides` (мерджится в `loki-config.yaml` последними):

```yaml
loki:
  config_overrides:
    start_phase: DEVELOPMENT      # старт со стадии разработки
    # skip_phases поддерживается, если loki-версия recognises этот ключ
```

### Управление гейтами

Восемь blocking-gate'ов (static analysis, test suite, 3-reviewer council,
anti-sycophancy, mock-integrity, test-mutation, doc-coverage, magic-debate)
плюс evidence-gate. В манифесте:

```yaml
loki:
  quality_gates:
    enabled: true
    opt_out:                      # выключить поимённо
      - mock_integrity
      - magic_debate
  proofs:
    enabled: false                # без evidence-receipts
```

---

## Слой 3. Управление через манифест microcode

Ключевые рычаги `platform.yaml`:

| Цель | Поле | Эффект |
|---|---|---|
| Superpowers-скиллы → loki-формат | `skills.install` + `translate.target_agent` | skillkit переводит и кладёт в `skills/` |
| Зеркалирование в память loki | `skills.translate.also_into_memory: true` | SKILL.md попадают в `.loki/memory/skills/` |
| Своя папка скилл-модулей | `sandbox.mounts` (host → `/workspace/skills`) | overlay поверх встроенных |
| Фазы/тир сложности | `loki.effort` | сужает SDLC |
| Гейты | `loki.quality_gates` (`opt_out`) | вкл/выкл гейты |
| Бюджет/итерации | `loki.max_iterations`, `loki.max_budget_usd` | лимиты RARV-цикла |
| Модель провайдера | `loki.model` | model id для активного провайдера |
| Произвольные ключи loki | `loki.config_overrides` | мерджатся последними, выигрывают |
| Память (cross-project) | `loki.memory.storage` | named-volume, `LOKI_MEMORY_BASE_PATH` |
| Скиллы **внутри** VM | `skills.in_vm: true` | skillkit бежит в окружении loki |

### Полный пример: кастомные навыки + суженный SDLC

```yaml
version: 1
skills:
  in_vm: true
  install:
    - source: obra/superpowers
      skills: [test-driven-development, systematic-debugging, verification-before-completion]
  translate: { target_agent: cline, output_dir: skills, also_into_memory: true }

loki:
  provider: cline
  model: glm-5.2
  effort: standard              # 6 фаз вместо 8
  quality_gates:
    enabled: true
    opt_out: [magic_debate]     # Gate 8 не нужен (нет UI)
  config_overrides:
    start_phase: DEVELOPMENT
  proofs: { enabled: true }

sandbox:
  image: debian
  mounts:
    - { host: ./custom-skills, dest: /workspace/skills, readonly: false }
    - { host: ./src, dest: /workspace, readonly: false }
```

---

## Итоговая таблица «что где меняется»

| Цель | Инструмент | Слой |
|---|---|---|
| Добавить domain-правила | новый `.md` в `skills/` + строка в `00-index.md` | скилл-модули |
| Заменить тестовые/ревью-правила | файл с тем же именем в `skills/` | скилл-модули |
| Дополнить фазу (напр. security перед QA) | скилл-модуль, срабатывающий по фазе | модули + фазы |
| Сузить SDLC (fewer фаз) | `loki.effort` | манифест |
| Выключить гейт | `loki.quality_gates.opt_out` | манифест |
| Произвольный ключ loki | `loki.config_overrides` | манифест |
| Superpowers-скиллы → loki | `skills.install` + `translate` | манифест |
| Кросс-проектная память | `loki.memory.storage` (volume) | манифест |

См. также: [`examples/cline-multi-skills/`](../examples/cline-multi-skills/) —
полный работающий пример c разными skill-провайдерами внутри VM.
