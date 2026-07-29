"""Common types for generators."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GeneratedArtifact:
    """A single generated file with a relative name and text content."""

    name: str
    content: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("artifact name must be non-empty")


@dataclass(frozen=True)
class GenerationResult:
    """Output of one generator: artifacts + a list of CLI command specs.

    Commands are represented as a list of argv tokens (not a shell string) so
    they can be displayed deterministically and executed safely via subprocess.
    """

    artifacts: list[GeneratedArtifact] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
