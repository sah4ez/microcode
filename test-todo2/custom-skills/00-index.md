# Skill Modules Index (microcode overlay)

Overlay поверх встроенных модулей loki (`skills/*.md`). Loki грузит модули по
фазе задачи — 1-3 за раз, по этой таблице. Файлы с тем же именем здесь
переопределяют встроенные.

**Проектный стек: Go + github.com/seniorGolang/tg (v2) + go-fiber + SQLite
(modernc.org/sqlite).** Все overlay-модули ниже заточены под этот стек. PRD-001
требует рефакторинга текущего Python-сервиса в Go — НЕ продолжайте на Python.

Load 1-3 modules based on your current task. Do not load all modules.

## Module Selection Rules

| If your task involves...                                  | Load these modules   | origin     |
|-----------------------------------------------------------|----------------------|------------|
| Writing Go service code, defining tg contracts            | tg-dev.md            | overlay    |
| HTTP endpoint design, request/response shapes, status     | api-contract-rules.md| overlay    |
| Writing tests (table-driven, persistence-reopen)          | tdd-rules.md         | overlay    |
| Security checks, pre-QA transition                        | security-checks.md   | overlay    |
| Model / tool selection                                    | model-selection.md   | loki built-in |
| Code review, quality checks                               | quality-gates.md     | loki built-in |
| Debugging, errors, failures                               | troubleshooting.md   | loki built-in |
| Architecture decisions                                    | patterns-advanced.md | loki built-in |

## Overlay modules

### tg-dev.md
Когда: ЛЮБОЙ код Go-сервиса (определять контракт `// @tg`, запускать codegen
`tg transport ...`, собирать сервер на go-fiber, подключать SQLite-репозиторий).
Это **фреймворк** github.com/seniorGolang/tg/v2 — НЕ Tool-Gateway CLI.

### api-contract-rules.md
Когда: проектирование HTTP-эндпоинтов, формы запросов/ответов, статус-коды,
контракт ошибок. Go-версия (struct + json tags, sentinel errors, 201/204/404/422).

### tdd-rules.md
Когда: реализация любой фичи/багфикса, ДО написания кода.
RED-GREEN-REFACTOR на `go test`. Table-driven, реальный SQLite (без моков),
обязательный тест персистентности (reopen DB-файла).

### security-checks.md
Когда: фаза DEVELOPMENT, перед переходом в QA.
Security-скан изменившихся файлов, блокировка перехода при HIGH-находках.

## How to Load
1. Read this index.
2. Pick 1-2 modules matching the current phase/task.
3. Read those files.
4. Execute with loaded context.
