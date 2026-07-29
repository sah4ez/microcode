"""Tests for orchestrator artifact writing + dry-run (no real CLI execution)."""

from __future__ import annotations

from pathlib import Path

from microcode import config
from microcode.manifest import PlatformManifest
from microcode.orchestrator import apply as apply_plan
from microcode.orchestrator import write_artifacts
from microcode.planner import build_plan


def _m():
    return PlatformManifest.model_validate({"version": 1})


def test_write_artifacts_creates_files(tmp_path: Path):
    m = _m()
    plan = build_plan(m)
    adir = tmp_path / "artifacts"
    write_artifacts(plan, adir)
    assert (adir / "bootstrap.sh").exists()
    assert (adir / "loki-config.yaml").exists()
    assert (adir / ".skills").exists()
    assert (adir / "loki.env").exists()


def test_apply_dry_run_executes_nothing_but_writes_plan(tmp_path: Path):
    m = _m()
    plan = apply_plan(m, root=tmp_path, dry_run=True, skip_doctor=True)
    # artifacts dir created? In dry-run we do NOT write; confirm absence.
    adir = config.artifacts_dir(tmp_path, m.project.state_dir)
    assert not adir.exists()
    # but a plan was returned
    assert plan.loki_command is not None
