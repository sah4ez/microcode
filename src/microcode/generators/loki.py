"""Generator: loki section -> loki-mode config file + env file.

Loki reads config via ``--config <path>`` / ``LOKI_CONFIG_FILE`` in YAML/JSON/env
format. We emit a YAML config plus a companion ``.env`` of the environment
variables the runtime needs (provider auth is referenced by name, not inlined).
"""

from __future__ import annotations

import yaml

from microcode.generators.base import GeneratedArtifact, GenerationResult
from microcode.manifest import PlatformManifest


def _loki_yaml(m: PlatformManifest) -> dict:
    l = m.loki
    cfg: dict = {
        "provider": l.provider,
        "effort": l.effort,
        "max_iterations": l.max_iterations,
        "max_budget_usd": l.max_budget_usd,
        "sdk_mode": l.sdk_mode,
        "quality_gates": {
            "enabled": l.quality_gates.enabled,
            "opt_out": list(l.quality_gates.opt_out),
        },
        "memory": {"enabled": l.memory.enabled, "managed": l.memory.managed},
        "proofs": {"enabled": l.proofs.enabled},
    }
    # explicit model override for the active provider
    if l.model:
        cfg["model"] = l.model
    # human-in-the-loop phase control
    if l.stop_after_phase:
        cfg["stop_after_phase"] = l.stop_after_phase
    if l.start_phase:
        cfg["start_phase"] = l.start_phase
    # merge user overrides last so they win
    if l.config_overrides:
        cfg.update(l.config_overrides)
    return cfg


def _loki_env(m: PlatformManifest) -> str:
    """Env vars loki-mode reads. Values are NOT inlined — they reference host env."""
    l = m.loki
    lines = [
        f"LOKI_PROVIDER={l.provider}",
        f"LOKI_SDK_MODE={l.sdk_mode}",
        f"LOKI_MAX_ITERATIONS={l.max_iterations}",
    ]
    if l.model:
        # loki-mode reads LOKI_MODEL_OVERRIDE to override any provider's model.
        lines.append(f"LOKI_MODEL_OVERRIDE={l.model}")
    if l.effort:
        lines.append(f"LOKI_COMPLEXITY={l.effort}")
    if l.memory.managed:
        lines.append("LOKI_MANAGED_MEMORY=true")
        lines.append("LOKI_MANAGED_AGENTS=true")
    if not l.proofs.enabled:
        lines.append("LOKI_PROOF=0")
    # provider auth is passed through as host env -> msb --secret; do not inline.
    if l.provider == "claude":
        lines.append("# ANTHROPIC_API_KEY injected via msb --secret (not inlined)")
    elif l.provider == "codex":
        lines.append("# OPENAI_API_KEY injected via msb --secret (not inlined)")
    # external (persistent) memory: point loki at a mounted named volume so
    # cross-project learnings survive VM destroy/recreate cycles.
    if l.memory.storage.enabled:
        lines.append(f"LOKI_MEMORY_BASE_PATH={l.memory.storage.dest}")
    return "\n".join(lines) + "\n"


def generate_loki(m: PlatformManifest) -> GenerationResult:
    artifacts = [
        GeneratedArtifact(
            name="loki-config.yaml",
            content=yaml.safe_dump(_loki_yaml(m), sort_keys=False, default_flow_style=False),
        ),
        GeneratedArtifact(name="loki.env", content=_loki_env(m)),
    ]
    return GenerationResult(artifacts=artifacts)
