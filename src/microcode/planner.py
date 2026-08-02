"""Planner: turns a manifest into an ordered, deterministic execution plan.

The plan groups actions by phase and is pure (no I/O). The orchestrator writes
artifacts to disk and hands the command groups to the runners in order.

Determinism matters: the same manifest always yields the same plan, which makes
``plan`` reproducible and ``apply`` safe to re-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from microcode.generators import (
    GeneratedArtifact,
    generate_bootstrap,
    generate_loki,
    generate_sandbox,
    generate_skills,
    generate_sync,
)
from microcode.manifest import PlatformManifest

# Guest paths inside the VM (must match the sandbox mount of the state dir).
GUEST_CONFIG = "/workspace/.microcode/artifacts/loki-config.yaml"
GUEST_STATE = "/workspace/.microcode"


@dataclass(frozen=True)
class Plan:
    """A fully resolved, ordered plan."""

    artifacts: list[GeneratedArtifact] = field(default_factory=list)
    # ordered command groups; each is executed by one runner
    skillkit_commands: list[list[str]] = field(default_factory=list)
    sandbox_commands: list[list[str]] = field(default_factory=list)
    # git clone commands — run after boot when sandbox.sync is enabled, replacing
    # the bind mount (build) / tar-seed (apply) for the sync.dest workspace.
    clone_commands: list[list[str]] = field(default_factory=list)
    loki_command: list[str] | None = None
    notes: list[str] = field(default_factory=list)
    prd: str | None = None

    def all_commands(self) -> list[list[str]]:
        out: list[list[str]] = [*self.skillkit_commands, *self.sandbox_commands]
        out.extend(self.clone_commands)
        if self.loki_command:
            out.append(self.loki_command)
        return out


def build_plan(m: PlatformManifest, prd: str | None = None) -> Plan:
    skills = generate_skills(m)
    loki = generate_loki(m)
    bootstrap = generate_bootstrap(m)
    sandbox = generate_sandbox(m)
    sync = generate_sync(m)

    artifacts = [
        *skills.artifacts,
        *loki.artifacts,
        *bootstrap.artifacts,
    ]

    notes = [*skills.notes, *sandbox.notes, *sync.notes]
    # Run loki as the unprivileged 'loki' user (created by bootstrap) so
    # claude/cline accept --dangerously-skip-permissions (refused under root).
    # Set PATH/HOME explicitly — a non-root login shell may not source the
    # bootstrap-written PATH.
    node_ver = m.sandbox.init.packages.node_version
    prefix = (
        f"export PATH=/opt/npm-global/bin:/opt/node{node_ver}/bin:/usr/local/bin:/usr/bin:$PATH "
        f"&& export HOME=/home/loki && cd /workspace"
    )
    loki_inner = (
        f"{prefix} && loki start --config {GUEST_CONFIG}"
        + (" --api" if m.loki.dashboard else " --no-dashboard")
        + " --simple"
        + (f" {prd}" if prd else "")
    )
    loki_cmd = (
        # always run loki as the unprivileged 'loki' user (created by bootstrap),
        # regardless of sandbox.user (which governs create/init). Provider CLIs
        # (claude/cline) refuse --dangerously-skip-permissions under root.
        ["msb", "exec", m.sandbox.name, "--user", "loki", "--",
         "bash", "-lc", loki_inner]
    )

    return Plan(
        artifacts=artifacts,
        skillkit_commands=skills.commands,
        sandbox_commands=sandbox.commands,
        clone_commands=sync.commands,
        loki_command=loki_cmd,
        notes=notes,
        prd=prd,
    )
