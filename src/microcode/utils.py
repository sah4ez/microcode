"""Small shared utilities."""

from __future__ import annotations

import os
import re

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: str) -> str:
    """Expand ``${VAR}`` references from the process environment.

    Unknown variables expand to an empty string. This is used to surface host
    secrets/paths into generated ``-e KEY=${VAR}`` flags without inlining the
    real values into the (public) manifest.
    """

    def _sub(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _VAR_RE.sub(_sub, value)
