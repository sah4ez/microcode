"""Runner: invokes loki-mode *inside* the microsandbox VM via ``msb exec``.

The loki config and translated skills are mounted into the VM, so we only need
to exec the ``loki start`` command there with the generated config path.
"""

from __future__ import annotations

from microcode.manifest import PlatformManifest
from microcode.runners.base import ShellRunner, require


def loki_start_argv(m: PlatformManifest, config_guest: str, prd: str | None) -> list[str]:
    """Build ``msb exec <name> -- loki start --config ... [prd]``."""
    argv = ["msb", "exec", m.sandbox.name, "--user", m.sandbox.user, "--"]
    cmd = ["loki", "start", "--config", config_guest, "--no-dashboard", "--simple"]
    if prd:
        cmd.append(prd)
    return argv + cmd


class LokiRunner(ShellRunner):
    """Runs the loki start invocation inside the VM."""

    def __init__(
        self, m: PlatformManifest, config_guest: str, prd: str | None = None,
        cwd: str | None = None,
    ) -> None:
        super().__init__(cwd=cwd)
        self.m = m
        self.config_guest = config_guest
        self.prd = prd

    def run(self, dry_run: bool = False) -> None:  # type: ignore[override]
        if not dry_run:
            require("msb")
        super().run([loki_start_argv(self.m, self.config_guest, self.prd)], dry_run=dry_run)
