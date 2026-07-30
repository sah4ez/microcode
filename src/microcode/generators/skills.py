"""Generator: skills section -> skillkit ``.skills`` manifest + CLI commands.

Produces:
* ``.skills``           — skillkit team-share manifest (install plan)
* ``skills-install``    — a sequence of ``skillkit`` argv lists to execute

The translated ``SKILL.md`` files are written by skillkit itself into
``skills.translate.output_dir`` (then mounted into the VM).
"""

from __future__ import annotations

import json

from microcode.generators.base import GeneratedArtifact, GenerationResult
from microcode.manifest import PlatformManifest


def _build_skills_manifest(m: PlatformManifest) -> dict:
    skills = m.skills
    agents_default = [skills.translate.target_agent]
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
        agents = inst.agents or [skills.translate.target_agent]
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
    return GenerationResult(artifacts=artifacts, commands=commands, notes=notes)
