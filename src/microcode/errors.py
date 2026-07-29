"""Exception hierarchy for microcode."""

from __future__ import annotations


class MicrocodeError(Exception):
    """Base class for all microcode errors."""


class ManifestError(MicrocodeError):
    """The platform manifest is missing, malformed, or invalid."""


class ManifestNotFoundError(ManifestError):
    """The manifest file does not exist."""


class GenerationError(MicrocodeError):
    """A generator failed to produce an artifact from the manifest."""


class RunnerError(MicrocodeError):
    """A runner failed while executing a planned action."""


class DependencyError(RunnerError):
    """A required external tool (msb, skillkit, loki) is missing or too old."""
