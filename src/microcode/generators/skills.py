"""Generator: skills section -> skillkit ``.skills`` manifest + CLI commands.

Produces:
* ``.skills``           — skillkit team-share manifest (install plan)
* ``skills-install``    — a sequence of ``skillkit`` argv lists to execute

The translated ``SKILL.md`` files are written by skillkit itself into
``skills.translate.output_dir`` (then mounted into the VM).

Two execution sites:

* **Host** (default, ``skills.in_vm=false``): bare ``skillkit ...`` argv lists
  run by :class:`~microcode.runners.skillkit_runner.SkillkitRunner` on the host
  *before* the sandbox is created.
* **In-VM** (``skills.in_vm=true``): each command is wrapped in
  ``msb exec <name> --user loki -- bash -lc '<env-prefix> && skillkit ...'`` so
  skillkit runs inside the already-bootstrapped microsandbox VM. This runs
  *after* sandbox create+init (the orchestrator reorders the phases).
"""

from __future__ import annotations

import json
import shlex

from microcode.generators.base import GeneratedArtifact, GenerationResult
from microcode.manifest import PlatformManifest


def _in_vm_prefix(m: PlatformManifest) -> str:
    """PATH/HOME prefix for skillkit commands run as the VM's ``loki`` user.

    Mirrors the loki runner prefix so the same npm-global tooling is visible.
    """
    nver = m.sandbox.init.packages.node_version
    return (
        f"export PATH=/opt/npm-global/bin:/opt/node{nver}/bin:/usr/local/bin:/usr/bin:$PATH "
        f"&& export HOME=/home/loki && cd /workspace"
    )


def _wrap_in_vm(cmd: list[str], m: PlatformManifest) -> list[str]:
    """Wrap a bare ``skillkit ...`` argv as ``msb exec ... -- bash -lc '...'``."""
    inner = f"{_in_vm_prefix(m)} && " + " ".join(shlex.quote(t) for t in cmd)
    return [
        "msb", "exec", m.sandbox.name, "--user", "loki",
        "--", "bash", "-lc", inner,
    ]


def _build_skills_manifest(m: PlatformManifest) -> dict:
    skills = m.skills
    # The fixed agent set skills target — mirrors loki-mode's providers 1:1
    # (claude, codex, cline, aider) so skills never target a provider loki
    # cannot run. Falls back to the single translate target only if the user
    # explicitly emptied skills.agents.
    agents_default = list(skills.agents) or [skills.translate.target_agent]
    entries = []
    for inst in skills.install:
        entries.append(
            {
                "source": inst.source,
                "enabled": True,
                "skills": list(inst.skills),
                "agents": list(inst.agents) if inst.agents else list(agents_default),
            }
        )
    return {
        "skills": entries,
        "agents": agents_default,
        "installMethod": "copy",
        # NOTE: intentionally no timestamp — plans must be deterministic.
    }


def generate_skills(m: PlatformManifest) -> GenerationResult:
    skills = m.skills
    artifacts: list[GeneratedArtifact] = []
    commands: list[list[str]] = []

    # disabled skills phase (e.g. skills already provisioned out of band)
    if not skills.enabled:
        return GenerationResult(
            artifacts=[],
            commands=[],
            notes=["skills phase disabled (skills.enabled=false); provisioned out of band"],
        )

    # 1) The .skills manifest (declarative install plan)
    manifest_obj = _build_skills_manifest(m)
    artifacts.append(
        GeneratedArtifact(name=".skills", content=json.dumps(manifest_obj, indent=2) + "\n")
    )

    # 2) tap custom registries (idempotent-ish; user is expected to dedupe)
    for tap in skills.registry.taps:
        commands.append(["skillkit", "tap", "add", tap])

    # 3) Install each source non-interactively.
    #    We emit per-source install commands so failures are attributable.
    for inst in skills.install:
        cmd = ["skillkit", "install", inst.source, "--yes"]
        if inst.provider:
            cmd += ["--provider", inst.provider]
        if inst.skills:
            cmd += ["--skills", ",".join(inst.skills)]
        agents = inst.agents or list(skills.agents) or [skills.translate.target_agent]
        for a in agents:
            cmd += ["--agent", a]
        commands.append(cmd)

    # 4) Translate the explicitly installed skills into the single target format.
    #    We translate by name (not --all) so unrelated global skills don't collide,
    #    and always pass --force so re-runs are idempotent.
    installed_names = []
    for inst in skills.install:
        installed_names.extend(inst.skills or [])
    if installed_names:
        for name in installed_names:
            translate_cmd = [
                "skillkit", "translate", name,
                "--to", skills.translate.target_agent,
                "--output", skills.translate.output_dir,
                "--force",
            ]
            commands.append(translate_cmd)
    else:
        # nothing explicit to translate — skip rather than --all (which would pull
        # in unrelated global skills and may collide)
        pass

    notes: list[str] = []
    if skills.translate.also_into_memory:
        notes.append(
            "after translate, mirror SKILL.md files into .loki/memory/skills/ "
            "(handled by sandbox mount of the same skills dir)"
        )
    if skills.in_vm:
        notes.append(
            "skills.in_vm=true: skillkit runs inside the microsandbox VM via "
            "msb exec; the orchestrator creates+bootstraps the VM first"
        )
        commands = [_wrap_in_vm(c, m) for c in commands]
    return GenerationResult(artifacts=artifacts, commands=commands, notes=notes)
