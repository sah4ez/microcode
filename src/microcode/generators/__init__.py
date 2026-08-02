"""Generators turn a manifest into subsystem-specific artifacts (pure functions)."""

from microcode.generators.base import GeneratedArtifact, GenerationResult
from microcode.generators.bootstrap import generate_bootstrap
from microcode.generators.loki import generate_loki
from microcode.generators.net import dns_argv, network_argv, rule_token, suffix_token
from microcode.generators.sandbox import from_snapshot_mount_map, generate_sandbox
from microcode.generators.skills import generate_skills
from microcode.generators.sync import generate_sync, sync_egress_rules

__all__ = [
    "GeneratedArtifact",
    "GenerationResult",
    "generate_bootstrap",
    "generate_loki",
    "generate_sandbox",
    "from_snapshot_mount_map",
    "generate_skills",
    "generate_sync",
    "sync_egress_rules",
    "network_argv",
    "dns_argv",
    "rule_token",
    "suffix_token",
]
