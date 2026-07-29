"""Base runner utilities: subprocess execution + dependency checks."""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from microcode import logging_utils
from microcode.errors import DependencyError, RunnerError


def which(binary: str) -> str | None:
    """Return the absolute path to *binary* on PATH, or None."""
    return shutil.which(binary)


def require(*binaries: str) -> None:
    """Raise DependencyError if any binary is missing from PATH."""
    missing = [b for b in binaries if which(b) is None]
    if missing:
        raise DependencyError(
            "missing required tools on PATH: " + ", ".join(missing)
        )


class Runner(Protocol):
    """A runner applies a list of argv commands (optionally dry-run)."""

    def run(self, commands: list[list[str]], dry_run: bool = False) -> None: ...


class ShellRunner:
    """Run argv lists via subprocess, with dry-run support.

    ``cwd`` defaults to the current directory. ``env`` is merged into the
    process environment (used to surface host secrets to ``msb --secret``).
    """

    def __init__(self, cwd: str | None = None, env: dict[str, str] | None = None) -> None:
        self.cwd = cwd
        self.env = env

    # public --------------------------------------------------------------
    def run(self, commands: list[list[str]], dry_run: bool = False) -> None:
        for argv in commands:
            self._run_one(argv, dry_run=dry_run)

    # internal ------------------------------------------------------------
    def _run_one(self, argv: list[str], dry_run: bool) -> None:
        line = _argv_to_str(argv)
        if dry_run:
            logging_utils.cmd(line)
            return
        logging_utils.cmd(line)
        try:
            subprocess.run(argv, cwd=self.cwd, env=self._env(), check=True)
        except FileNotFoundError as e:
            raise DependencyError(f"command not found: {argv[0]}") from e
        except subprocess.CalledProcessError as e:
            raise RunnerError(f"command failed (exit {e.returncode}): {line}") from e

    def _env(self) -> dict[str, str] | None:
        import os

        if self.env is None:
            return None
        merged = dict(os.environ)
        merged.update(self.env)
        return merged


def _argv_to_str(argv: list[str]) -> str:
    """Render an argv list as a shell-ish string for display."""
    import shlex

    return " ".join(shlex.quote(a) for a in argv)
