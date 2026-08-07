# USAGE

## Prerequisites

- Go toolchain 1.26+ (`go version`)
- Node.js 22+ (for frontend tests: `node static/app.test.js`)
- No external services required (SQLite is embedded)
- Port 8000 must be free
- Python 3.10+
- `pip` (or `conda` for the recommended environment)

## Install

```bash
cd test-todo2/src
go mod tidy
pip install -e ".[dev]"
```

Or with conda:

```bash
conda env create -f environment.yml
conda activate mcd
```

## Start

```bash
<<<<<<< HEAD
cd test-todo2/src
go run main.go
```

The server listens on `http://127.0.0.1:8000` and auto-creates `./data/todos.db`.

## Verify

```bash
# 1) Create a cabinet (ЛК)
curl -s -X POST http://127.0.0.1:8000/personal-profile -H 'Content-Type: application/json' -d '{"name":"работа"}'

# 2) Create a todo in the cabinet
curl -s -X POST http://127.0.0.1:8000/todos -H 'Content-Type: application/json' -H 'x-lk-id: 1' -d '{"title":"Buy milk"}'

# 3) List todos for the cabinet
curl -s http://127.0.0.1:8000/todos -H 'x-lk-id: 1'

# 4) Run tests
cd test-todo2/src && go test ./...
node test-todo2/src/static/app.test.js
=======
microcode validate examples/minimal.yaml
microcode plan examples/minimal.yaml --prd prd.md
microcode apply examples/minimal.yaml --prd prd.md
```

## Verify

```bash
python -m pytest -q
```

## Stop

Ctrl+C to stop the loki agent session.

```bash
microcode destroy examples/minimal.yaml
```
