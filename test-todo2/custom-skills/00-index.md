# Skill Modules Index (microcode overlay)

Overlay поверх встроенных модулей loki (`skills/*.md`). Loki грузит модули по
фазе задачи — 1-3 за раз, по этой таблице. Файлы с тем же именем здесь
переопределяют встроенные.

**Проектный стек: Go 1.26 + github.com/seniorGolang/tg/v3 + go-fiber + SQLite
(modernc.org/sqlite, pure-Go).** Все overlay-модули ниже заточены под этот стек.
PRD-001 требует рефакторинга текущего Python-сервиса в Go — НЕ продолжайте на Python.

## ⚠️ tg v3 codegen — ОБЯЗАТЕЛЬНО (не опционально)

**tg v3 — основное требование проекта, а не один из вариантов.** HTTP-транспорт
ДОЛЖЕН генерироваться через `tg server` (плагины `astg` + `server` уже стоят в
VM — `tg pkg list`). Ручной fiber-код (`fiber.New()`, `app.Get/Post`) для
контрактных эндпоинтов **запрещён**. Подробнее — `tg-dev.md` (читать ПЕРВЫМ).

Модуль `tg-dev.md` грузится ВСЕГДА перед написанием любого Go-кода сервиса.

Load 1-3 modules based on your current task. Do not load all modules.

## Module Selection Rules

| If your task involves...                                  | Load these modules   | origin     |
|-----------------------------------------------------------|----------------------|------------|
| **ЛЮБОЙ код Go-сервиса (всегда первым!)**                 | **tg-dev.md**        | overlay    |
| HTTP endpoint design, request/response shapes, status     | api-contract-rules.md| overlay    |
| Writing tests (table-driven, persistence-reopen)          | tdd-rules.md         | overlay    |
| Security checks, pre-QA transition                        | security-checks.md   | overlay    |
| Model / tool selection                                    | model-selection.md   | loki built-in |
| Code review, quality checks                               | quality-gates.md     | loki built-in |
| Debugging, errors, failures                               | troubleshooting.md   | loki built-in |
| Architecture decisions                                    | patterns-advanced.md | loki built-in |

## Overlay modules

### tg-dev.md (ОБЯЗАТЕЛЬНЫЙ)
Когда: **ВСЕГДА** перед написанием Go-кода сервиса. Единственный способ
опубликовать HTTP — контракт `// @tg` (в `contracts/`) + генерация транспорта
`tg server -o internal/transport`. Модуль фреймворка
`github.com/seniorGolang/tg/v3` (суффикс `/v3` обязателен — без него модуль
неразрешим). НЕ v2 `tg transport`, НЕ ручной fiber. tg CLI + плагины tgp-go
уже установлены в VM — не пытайтесь «установить» их и не откатывайтесь на
ручной fiber «потому что tg недоступен».

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
2. **Always read `tg-dev.md` first when writing Go service code.**
3. Pick 1-2 more modules matching the current phase/task.
4. Read those files.
5. Execute with loaded context.
