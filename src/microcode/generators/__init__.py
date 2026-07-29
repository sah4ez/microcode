"""Generators turn a manifest into subsystem-specific artifacts (pure functions)."""

from microcode.generators.base import GeneratedArtifact, GenerationResult
from microcode.generators.bootstrap import generate_bootstrap
from microcode.generators.loki import generate_loki
from microcode.generators.net import network_argv, rule_token, suffix_token
from microcode.generators.sandbox import generate_sandbox
from microcode.generators.skills import generate_skills

__all__ = [
    "GeneratedArtifact",
    "GenerationResult",
    "generate_bootstrap",
    "generate_loki",
    "generate_sandbox",
    "generate_skills",
    "network_argv",
    "rule_token",
    "suffix_token",
]
