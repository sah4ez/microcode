"""Runner: invokes loki-mode *inside* the microsandbox VM via ``msb exec``.

The loki config and translated skills are mounted into the VM, so we only need
to exec the ``loki start`` command there with the generated config path.
"""

from __future__ import annotations

from microcode.manifest import PlatformManifest
from microcode.runners.base import ShellRunner, require


def loki_start_argv(m: PlatformManifest, config_guest: str, prd: str | None) -> list[str]:
    """Build ``msb exec <name> --user loki -- bash -lc '... loki start ...'``.

    Runs as the unprivileged ``loki`` user (created by bootstrap) so provider
    CLIs (claude/cline) accept ``--dangerously-skip-permissions`` (refused under
    root). We set PATH/HOME explicitly in the inner command because a non-root
    login shell may not source the bootstrap-written PATH.

    Provider auth env (GLM key, z.ai OAuth) is forwarded via ``-e`` so the cline
    node-shim's zai-coding-plan provider authenticates inside the VM.
    """
    from microcode.utils import expand_env

    node_ver = m.sandbox.init.packages.node_version
    prefix = (
        f"export PATH=/opt/npm-global/bin:/opt/node{node_ver}/bin:/usr/local/bin:/usr/bin:$PATH "
        f"&& export HOME=/home/loki "
        f"&& cd /workspace "
    )
    inner = (
        f"{prefix}&& loki start --config {config_guest} --provider {m.loki.provider}"
        + (" --api" if m.loki.dashboard else " --no-dashboard")
        + " --simple"
        + (f" {prd}" if prd else "")
    )
    argv = ["msb", "exec", m.sandbox.name, "--user", "loki"]
    # forward provider auth env (resolved from the host env via ${VAR} expansion)
    for var in ("GLM_API_KEY", "ZAI_BUSINESS_BASE_URL", "ZAI_OAUTH_CLIENT_ID", "ZAI_OAUTH_ORIGIN", "CLINE_API_KEY"):
        val = expand_env("${" + var + "}")
        if val:
            argv += ["-e", f"{var}={val}"]
    # cline node-shim reads CLINE_MODEL; loki's cline provider reads
    # LOKI_CLINE_MODEL. Forward both so the manifest-declared model wins.
    if m.loki.provider == "cline" and m.loki.model:
        argv += ["-e", f"CLINE_MODEL={m.loki.model}"]
        argv += ["-e", f"LOKI_CLINE_MODEL={m.loki.model}"]
    # external memory: loki reads LOKI_MEMORY_BASE_PATH and writes to the
    # mounted named volume (persists across VM destroy/recreate).
    if m.loki.memory.storage.enabled:
        argv += ["-e", f"LOKI_MEMORY_BASE_PATH={m.loki.memory.storage.dest}"]
    argv += ["--", "bash", "-lc", inner]
    return argv


class LokiRunner(ShellRunner):
    """Runs the loki start invocation inside the VM."""

    def __init__(
        self, m: PlatformManifest, config_guest: str, prd: str | None = None,
        cwd: str | None = None, config_host: str | None = None,
    ) -> None:
        super().__init__(cwd=cwd)
        self.m = m
        self.config_guest = config_guest
        self.prd = prd
        self.config_host = config_host

    def run(self, dry_run: bool = False) -> None:  # type: ignore[override]
        if not dry_run:
            require("msb")
        # The loki config is generated on the host (<state_dir>/artifacts/) but
        # may not be visible inside the VM (only ./src is mounted as /workspace).
        # Create the guest dir and copy the config in via `msb cp` before loki.
        cmds: list[list[str]] = []
        if self.config_host and not dry_run:
            import os
            guest_dir = os.path.dirname(self.config_guest)
            cmds.append([
                "msb", "exec", self.m.sandbox.name, "--user", self.m.sandbox.user,
                "--", "mkdir", "-p", guest_dir,
            ])
            cmds.append([
                "msb", "cp", self.config_host,
                f"{self.m.sandbox.name}:{self.config_guest}",
            ])
        cmds.append(loki_start_argv(self.m, self.config_guest, self.prd))
        super().run(cmds, dry_run=dry_run)
