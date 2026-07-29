"""Orchestrator: writes artifacts and drives runners in the planned order.

Phases of ``apply``:
1. validate environment (doctor)
2. generate plan
3. write artifacts into <state_dir>/artifacts/
4. skillkit (host): install + translate skills
5. sandbox (msb): create VM, inject bootstrap.sh, run init (± snapshot)
6. loki (msb exec): start loki inside the VM

``destroy`` tears down the VM and cleans generated state.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from microcode import config, logging_utils
from microcode.errors import DependencyError, RunnerError
from microcode.manifest import PlatformManifest
from microcode.planner import Plan, build_plan
from microcode.runners import LokiRunner, SandboxRunner, SkillkitRunner, which

# Guest path where the loki config lands (must match planner.GUEST_CONFIG).
GUEST_CONFIG = "/workspace/.microcode/artifacts/loki-config.yaml"


def write_artifacts(plan: Plan, artifacts_dir: Path) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for art in plan.artifacts:
        (artifacts_dir / art.name).write_text(art.content, encoding="utf-8")


def doctor() -> list[str]:
    """Return a list of human-readable status lines; raise on missing tools."""
    problems: list[str] = []
    for tool in ("msb", "skillkit"):
        path = which(tool)
        if path:
            logging_utils.ok(f"{tool}: {path}")
        else:
            problems.append(tool)
            logging_utils.error(f"{tool}: NOT FOUND")
    if problems:
        raise DependencyError("missing required tools: " + ", ".join(problems))
    return problems


def apply(
    m: PlatformManifest,
    *,
    root: Path,
    dry_run: bool = False,
    prd: str | None = None,
    skip_doctor: bool = False,
) -> Plan:
    artifacts_dir = config.artifacts_dir(root, m.project.state_dir)

    if not skip_doctor and not dry_run:
        logging_utils.step("Checking dependencies")
        doctor()

    logging_utils.step("Building plan")
    plan = build_plan(m, prd=prd)

    logging_utils.step("Writing artifacts")
    if dry_run:
        for art in plan.artifacts:
            logging_utils.info(f"  [dim](would write)[/dim] {artifacts_dir / art.name}")
    else:
        write_artifacts(plan, artifacts_dir)
        logging_utils.ok(f"artifacts written to {artifacts_dir}")

    # 1) skillkit on host
    logging_utils.step("Provisioning skills (skillkit)")
    SkillkitRunner(cwd=str(root)).run(plan.skillkit_commands, dry_run=dry_run)

    # 2) sandbox: create + init (+ snapshot)
    logging_utils.step("Provisioning sandbox (microsandbox)")
    SandboxRunner(artifacts_dir=artifacts_dir, cwd=str(root)).run(
        plan.sandbox_commands, dry_run=dry_run
    )

    # 3) loki inside VM
    logging_utils.step("Starting loki-mode inside the VM")
    LokiRunner(m=m, config_guest=GUEST_CONFIG, prd=prd, cwd=str(root)).run(dry_run=dry_run)

    if dry_run:
        logging_utils.warn("dry-run: nothing was executed")
    else:
        logging_utils.ok("apply complete")
    return plan


def destroy(m: PlatformManifest, *, root: Path, dry_run: bool = False) -> None:
    name = m.sandbox.name
    state = config.state_dir(root, m.project.state_dir)

    logging_utils.step(f"Tearing down sandbox '{name}'")
    teardown = [
        ["msb", "stop", name],
        ["msb", "rm", "-f", name],
    ]
    runner = SkillkitRunner(cwd=str(root))  # reuses shell + dry-run logic
    if not dry_run:
        # msb must exist; but tolerate already-removed sandboxes
        if which("msb") is None:
            logging_utils.warn("msb not found; skipping VM teardown")
        else:
            for argv in teardown:
                try:
                    runner.run([argv])
                except RunnerError as e:
                    logging_utils.warn(f"ignored: {e}")
    else:
        runner.run(teardown, dry_run=True)

    logging_utils.step("Removing generated state")
    if dry_run:
        logging_utils.info(f"  [dim](would remove)[/dim] {state}")
    else:
        if state.exists():
            shutil.rmtree(state)
            logging_utils.ok(f"removed {state}")
        else:
            logging_utils.info(f"  nothing to remove at {state}")

    if dry_run:
        logging_utils.warn("dry-run: nothing was executed")
    else:
        logging_utils.ok("destroy complete")


def dump_plan(plan: Plan, path: Path) -> None:
    """Persist the plan as JSON for inspection / re-runs."""
    payload = {
        "artifacts": [{"name": a.name} for a in plan.artifacts],
        "skillkit_commands": plan.skillkit_commands,
        "sandbox_commands": plan.sandbox_commands,
        "loki_command": plan.loki_command,
        "notes": plan.notes,
        "prd": plan.prd,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
