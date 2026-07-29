"""Paths, version, and runtime configuration for microcode."""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.1.0"

# Directory names produced/consumed by microcode.
DEFAULT_STATE_DIR = ".microcode"
DEFAULT_MANIFEST = "platform.yaml"

# Sub-paths inside the state dir.
ARTIFACTS_DIR = "artifacts"
LOKI_CONFIG_NAME = "loki-config.yaml"
LOKI_ENV_NAME = "loki.env"
SKILLS_MANIFEST_NAME = ".skills"
BOOTSTRAP_NAME = "bootstrap.sh"
PLAN_NAME = "plan.json"

# Default image used when the manifest does not pin one.
DEFAULT_IMAGE = "debian"
DEFAULT_TAG = "bookworm-slim"


def project_root(start: Path | None = None) -> Path:
    """Return the directory containing the manifest search root.

    Currently the CWD; kept as a function so callers can override in tests.
    """
    return Path(start or os.getcwd()).resolve()


def state_dir(root: Path | str | None = None, explicit: str | None = None) -> Path:
    """Resolve the generated-state directory for a project root."""
    base = Path(root) if root is not None else project_root()
    rel = explicit or DEFAULT_STATE_DIR
    return (base / rel).resolve()


def artifacts_dir(root: Path | str | None = None, explicit: str | None = None) -> Path:
    return state_dir(root, explicit) / ARTIFACTS_DIR


def artifact_path(
    name: str, root: Path | str | None = None, explicit_state: str | None = None
) -> Path:
    return artifacts_dir(root, explicit_state) / name
