"""microcode CLI — validate / plan / apply / destroy / show / doctor."""

from __future__ import annotations

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
from microcode.orchestrator import doctor, dump_plan
from microcode.planner import build_plan

app = typer.Typer(
    name="microcode",
    help="Unified IaC for skillkit + loki-mode + microsandbox.",
    no_args_is_help=True,
    add_completion=False,
)


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
