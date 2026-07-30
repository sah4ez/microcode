# Skill Modules Index (microcode overlay)

Overlay поверх встроенных модулей loki (`skills/*.md`). Loki грузит модули по
фазе задачи — 1-3 за раз, по этой таблице. Файлы с тем же именем здесь
переопределяют встроенные.

Load 1-3 modules based on your current task. Do not load all modules.

## Module Selection Rules

| If your task involves...              | Load these modules            | origin     |
|---------------------------------------|-------------------------------|------------|
| Writing code, implementing            | model-selection.md            | loki built-in |
| Running tests, E2E                    | testing.md                    | loki built-in |
| Code review, quality checks           | quality-gates.md              | loki built-in |
| Debugging, errors, failures           | troubleshooting.md            | loki built-in |
| Architecture decisions                | patterns-advanced.md          | loki built-in |
| TDD: red-green-refactor               | tdd-rules.md                  | overlay    |  <!-- наше -->
| Security checks, pre-QA transition    | security-checks.md            | overlay    |  <!-- наше -->
| API contract: FastAPI + Pydantic      | api-contract-rules.md         | overlay    |  <!-- наше -->

## Overlay modules

### tdd-rules.md
Когда: реализация любой фичи/багфикса, ДО написания кода.
Дополняет встроенные правила тестирования: обязательный RED-GREEN-REFACTOR,
тесты рядом с кодом, без моков там, где можно проверить реальное поведение.

### security-checks.md
Когда: фаза DEVELOPMENT, перед переходом в QA.
Security-скан изменившихся файлов, блокировка перехода при HIGH-находках.

### api-contract-rules.md
Когда: написание HTTP-эндпоинтов, валидация запросов/ответов.
Единый стиль: Pydantic-модели для всех тел, статус-коды по RFC, описание в
docstring, тест на каждый эндпоинт.

## How to Load
1. Read this index.
2. Pick 1-2 modules matching the current phase/task.
3. Read those files.
4. Execute with loaded context.
