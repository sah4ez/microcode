"""microcode CLI — validate / plan / apply / destroy / show / doctor / steer / status / rollback."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import typer
from rich.panel import Panel
from rich.syntax import Syntax

from microcode import __version__, config, logging_utils
from microcode.errors import MicrocodeError
from microcode.manifest import find_manifest, load_manifest
from microcode.orchestrator import apply as apply_plan
from microcode.orchestrator import destroy as destroy_plan
from microcode.orchestrator import doctor, dump_plan, write_artifacts
from microcode.planner import build_plan

app = typer.Typer(
    name="microcode",
    help="Unified IaC for skillkit + loki-mode + microsandbox.",
    no_args_is_help=True,
    add_completion=False,
)

snapshot_app = typer.Typer(
    name="snapshot",
    help="Manage cached base-image snapshots (save/load for portability).",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(snapshot_app, name="snapshot")


def _resolve_manifest(file: str | None) -> Path:
    return Path(file).expanduser().resolve() if file else find_manifest()


def _load(file: str | None):
    path = _resolve_manifest(file)
    return path, load_manifest(path)


@app.command()
def validate(file: str = typer.Argument(None, help="path to platform.yaml")):
    """Validate the manifest (pydantic schema)."""
    path, m = _load(file)
    logging_utils.ok(f"valid: {path}")
    logging_utils.info(
        f"project={m.project.name} skills={len(m.skills.install)} "
        f"provider={m.loki.provider} image={m.sandbox.image_ref}"
    )


@app.command()
def plan(
    file: str = typer.Argument(None),
    prd: str = typer.Option(None, "--prd", help="PRD / spec to pass to loki"),
):
    """Build and print the execution plan without running anything."""
    path, m = _load(file)
    root = path.parent
    p = build_plan(m, prd=prd)

    logging_utils.step("Artifacts")
    for a in p.artifacts:
        logging_utils.info(f"  • {config.artifacts_dir(root, m.project.state_dir) / a.name}")

    logging_utils.step("skillkit commands")
    for c in p.skillkit_commands:
        logging_utils.cmd(" ".join(c))

    logging_utils.step("sandbox commands")
    for c in p.sandbox_commands:
        logging_utils.cmd(" ".join(c))

    logging_utils.step("loki command")
    if p.loki_command:
        logging_utils.cmd(" ".join(p.loki_command))

    if p.notes:
        logging_utils.step("Notes")
        for n in p.notes:
            logging_utils.info(f"  - {n}")

    # also persist a generated bootstrap.sh preview
    bs = next((a for a in p.artifacts if a.name == config.BOOTSTRAP_NAME), None)
    if bs:
        logging_utils.console.print(
            Panel(
                Syntax(bs.content, "bash", theme="ansi_dark", word_wrap=True),
                title="bootstrap.sh (generated)",
                border_style="cyan",
            )
        )


@app.command()
def apply(
    file: str = typer.Argument(None),
    prd: str = typer.Option(None, "--prd", help="PRD / spec to pass to loki"),
    dry_run: bool = typer.Option(False, "--dry-run", help="print commands, execute nothing"),
    skip_doctor: bool = typer.Option(False, "--skip-doctor", help="skip dependency check"),
):
    """Apply the plan: provision skills, VM, and start loki."""
    path, m = _load(file)
    root = path.parent
    try:
        p = apply_plan(m, root=root, dry_run=dry_run, prd=prd, skip_doctor=skip_doctor)
    except MicrocodeError as e:
        logging_utils.error(str(e))
        raise typer.Exit(code=1)
    # persist the applied plan for reproducibility (skip in dry-run: no side effects)
    if not dry_run:
        dump_plan(p, config.artifact_path(config.PLAN_NAME, root, m.project.state_dir))


@app.command()
def build(
    file: str = typer.Argument(None),
    dry_run: bool = typer.Option(False, "--dry-run", help="print commands, execute nothing"),
    skip_doctor: bool = typer.Option(False, "--skip-doctor", help="skip dependency check"),
):
    """Build a cached base-image snapshot (bootstrap once, reuse forever).

    Boots the stock debian VM, runs bootstrap.sh (node/bun/loki/cline/skillkit),
    stops the VM, and captures a snapshot named by ``sandbox.init.snapshot.name``.
    Subsequent ``apply`` calls with ``snapshot.from_snapshot`` boot from it,
    skipping bootstrap entirely (~seconds vs ~30 min on arm64).
    """
    from microcode.runners import SandboxRunner

    path, m = _load(file)
    root = path.parent
    if not m.sandbox.init.snapshot.name:
        logging_utils.error("sandbox.init.snapshot.name is empty")
        raise typer.Exit(code=1)
    try:
        if not skip_doctor and not dry_run:
            logging_utils.step("Checking dependencies")
            doctor(m)

        logging_utils.step("Building plan")
        plan = build_plan(m)

        logging_utils.step("Writing artifacts")
        artifacts_dir = config.artifacts_dir(root, m.project.state_dir)
        if dry_run:
            for art in plan.artifacts:
                logging_utils.info(f"  [dim](would write)[/dim] {artifacts_dir / art.name}")
        else:
            write_artifacts(plan, artifacts_dir)
            logging_utils.ok(f"artifacts written to {artifacts_dir}")

        # The plan already contains the full sequence when snapshot.enabled:
        # msb create + bootstrap + msb stop + msb snapshot create. We just run
        # it (no skillkit, no loki — that's `apply`'s job).
        if not dry_run:
            # remove a stale same-name sandbox so msb create doesn't fail with
            # "already exists" (msb create has no --replace, unlike msb run).
            from microcode.runners import SkillkitRunner
            rm = ["msb", "rm", "-f", m.sandbox.name]
            logging_utils.step(f"Removing stale sandbox '{m.sandbox.name}' (if any)")
            try:
                SkillkitRunner(cwd=str(root)).run([rm])
            except MicrocodeError:
                pass  # tolerate "not found"
            # Fallback: msb 0.6.8 sometimes leaves a hidden sandbox dir that
            # msb rm -f / msb list don't see, but msb create still rejects.
            # Purge it from the msb data dir directly.
            import os
            msb_dir = os.path.expanduser("~/.microsandbox/sandboxes")
            stale = os.path.join(msb_dir, m.sandbox.name)
            if os.path.exists(stale):
                import shutil
                shutil.rmtree(stale, ignore_errors=True)
        logging_utils.step("Creating sandbox + bootstrapping + snapshot")
        SandboxRunner(artifacts_dir=artifacts_dir, cwd=str(root)).run(
            plan.sandbox_commands, dry_run=dry_run
        )

        if dry_run:
            logging_utils.warn("dry-run: nothing was executed")
        else:
            snap_name = m.sandbox.init.snapshot.name
            logging_utils.ok(
                f"snapshot '{snap_name}' built. Set "
                f"snapshot.from_snapshot: {snap_name} and run `microcode apply` to reuse it."
            )
    except MicrocodeError as e:
        logging_utils.error(str(e))
        raise typer.Exit(code=1)


@snapshot_app.command("save")
def snapshot_save(
    name: str = typer.Argument(..., help="snapshot name/path"),
    out: str = typer.Argument(..., help="output archive path (tar.zst)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="print command, execute nothing"),
):
    """Export a snapshot to a portable archive (with OCI cache for offline boot)."""
    from microcode.runners import SkillkitRunner

    cmd = ["msb", "snapshot", "save", name, out, "--with-image"]
    logging_utils.cmd(" ".join(cmd))
    if not dry_run:
        try:
            SkillkitRunner().run([cmd])
            logging_utils.ok(f"saved snapshot '{name}' -> {out}")
        except MicrocodeError as e:
            logging_utils.error(str(e))
            raise typer.Exit(code=1)


@snapshot_app.command("load")
def snapshot_load(
    archive: str = typer.Argument(..., help="archive path (tar.zst)"),
    dest: str = typer.Argument(None, help="optional destination dir"),
    dry_run: bool = typer.Option(False, "--dry-run", help="print command, execute nothing"),
):
    """Import a snapshot archive on another machine."""
    from microcode.runners import SkillkitRunner

    cmd = ["msb", "snapshot", "load", archive]
    if dest:
        cmd.append(dest)
    logging_utils.cmd(" ".join(cmd))
    if not dry_run:
        try:
            SkillkitRunner().run([cmd])
            logging_utils.ok(f"loaded snapshot from {archive}")
        except MicrocodeError as e:
            logging_utils.error(str(e))
            raise typer.Exit(code=1)


@app.command()
def destroy(
    file: str = typer.Argument(None),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Destroy the sandbox and remove generated state."""
    path, m = _load(file)
    root = path.parent
    try:
        destroy_plan(m, root=root, dry_run=dry_run)
    except MicrocodeError as e:
        logging_utils.error(str(e))
        raise typer.Exit(code=1)


@app.command()
def show(file: str = typer.Argument(None)):
    """Print the resolved manifest in a readable form."""
    path, m = _load(file)
    logging_utils.console.print(
        Panel(m.model_dump_json(indent=2), title=f"resolved manifest — {path}", border_style="cyan")
    )


@app.command()
def steer(
    file: str = typer.Argument(None),
    message: str = typer.Argument(..., help="directive to inject into the running loki session"),
):
    """Inject a steering directive into a running loki session (async).

    Appends the message to .loki/HUMAN_INPUT.md inside the VM. Loki reads it
    on the next RARV iteration and incorporates it into the prompt. Does NOT
    pause loki — it's an asynchronous course correction.
    """
    from microcode.runners import SkillkitRunner

    path, m = _load(file)
    name = m.sandbox.name
    cmd = [
        "msb", "exec", name, "--user", "loki", "--",
        "bash", "-c", f"mkdir -p /workspace/.loki && printf '%s\\n' {shlex.quote(message)} >> /workspace/.loki/HUMAN_INPUT.md",
    ]
    logging_utils.cmd(" ".join(cmd))
    try:
        SkillkitRunner().run([cmd])
        logging_utils.ok(f"steer directive injected into '{name}'")
    except MicrocodeError as e:
        logging_utils.error(str(e))
        raise typer.Exit(code=1)


@app.command()
def status(file: str = typer.Argument(None)):
    """Show the running loki session status: phase, iteration, recent commits."""
    from microcode.runners import SkillkitRunner

    path, m = _load(file)
    name = m.sandbox.name
    # gather: orchestrator state + recent git log + workspace listing
    cmd = [
        "msb", "exec", name, "--user", "loki", "--", "bash", "-c",
        "echo '=== PHASE / STATE ==='; "
        "cat /workspace/.loki/state/orchestrator.json 2>/dev/null || echo '(no state)'; "
        "echo; echo '=== RECENT COMMITS ==='; "
        "git -C /workspace log --oneline -5 2>/dev/null || echo '(no git)'; "
        "echo; echo '=== WORKSPACE ==='; "
        "ls -la /workspace/ 2>/dev/null | head -20",
    ]
    logging_utils.cmd(" ".join(cmd[:6]) + " ...")
    try:
        SkillkitRunner().run([cmd])
    except MicrocodeError as e:
        logging_utils.error(str(e))
        raise typer.Exit(code=1)


@app.command()
def rollback(
    file: str = typer.Argument(None),
    to: str = typer.Option(None, "--to", help="git commit/checkpoint hash to reset to (default: HEAD~1)"),
):
    """Roll back the workspace to a previous loki git checkpoint."""
    from microcode.runners import SkillkitRunner

    path, m = _load(file)
    name = m.sandbox.name
    target = to or "HEAD~1"
    cmd = [
        "msb", "exec", name, "--user", "loki", "--",
        "bash", "-c", f"git -C /workspace reset --hard {target} && echo 'rolled back to {target}'",
    ]
    logging_utils.cmd(" ".join(cmd[:6]) + " ...")
    try:
        SkillkitRunner().run([cmd])
        logging_utils.ok(f"rolled back to {target}")
    except MicrocodeError as e:
        logging_utils.error(str(e))
        raise typer.Exit(code=1)


@app.command(name="doctor")
def doctor_cmd():
    """Check required tools are on PATH."""
    try:
        doctor()
    except MicrocodeError as e:
        logging_utils.error(str(e))
        raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", is_eager=True),
):
    if version:
        typer.echo(f"microcode {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
