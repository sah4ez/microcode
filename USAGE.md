# USAGE

## Prerequisites

- Python 3.10+
- `pip` (or `conda` for the recommended environment)

## Install

```bash
pip install -e ".[dev]"
```

Or with conda:

```bash
conda env create -f environment.yml
conda activate mcd
```

## Start

```bash
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
