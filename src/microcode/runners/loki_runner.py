"""Runner: invokes loki-mode *inside* the microsandbox VM via ``msb exec``.

The loki config and translated skills are mounted into the VM, so we only need
to exec the ``loki start`` command there with the generated config path.
"""

from __future__ import annotations

from microcode.manifest import PlatformManifest
from microcode.runners.base import ShellRunner, require


def _resolve_prd_guest_path(m: PlatformManifest, prd: str) -> str:
    """Translate a host-relative ``--prd`` path into the path loki sees in the VM.

    ``loki start`` runs after ``cd /workspace`` (see :func:`loki_start_argv`), so
    a bare ``PRD.md`` resolves to ``/workspace/PRD.md``. But the sandbox bind-mount
    maps the host working dir (e.g. ``./src``) onto ``/workspace`` — the host file
    ``./src/PRD.md`` is visible inside the VM at ``/workspace/PRD.md``, NOT at
    ``/workspace/src/PRD.md``. A user who naturally runs
    ``microcode apply ... --prd src/PRD.md`` therefore gets a "file not found",
    because ``src/PRD.md`` after ``cd /workspace`` points at the non-existent
    ``/workspace/src/PRD.md``.

    This helper finds the mount whose host dir contains the prd path and rewrites
    the prd to be relative to that mount's guest destination. With the only mount
    of ``./src → /workspace`` and ``prd="src/PRD-001.md"``, it returns
    ``PRD-001.md`` (i.e. ``/workspace/PRD-001.md`` after ``cd /workspace``).

    Absolute paths and paths that match no mount are returned unchanged (the
    caller may still pass an absolute guest path explicitly).
    """
    import os

    prd_norm = prd.strip()
    if not prd_norm or os.path.isabs(prd_norm):
        return prd_norm

    # Pick the longest host-prefix match so nested mounts win over shallow ones.
    best = None
    best_len = -1
    for mt in m.sandbox.mounts:
        host = os.path.normpath(mt.host)
        # prd may be given relative to the project root (e.g. "src/PRD.md") or
        # already relative to the mount host dir (e.g. "PRD.md"). Match either.
        if prd_norm == host or prd_norm.startswith(host + os.sep):
            rel = prd_norm[len(host):].lstrip(os.sep)
            if len(host) > best_len:
                best, best_len = (mt, rel), len(host)
        elif prd_norm == os.path.basename(host) or host.endswith(os.sep + prd_norm):
            # prd names the host dir itself or a single component under it.
            rel = prd_norm[len(os.path.dirname(host)):].lstrip(os.sep) if prd_norm.startswith(os.path.dirname(host)) else prd_norm
            if len(host) > best_len:
                best, best_len = (mt, rel), len(host)

    if best is None:
        return prd_norm
    mt, rel = best
    # The mount's guest dest is absolute (e.g. /workspace). loki runs from
    # /workspace, so emit a path relative to that CWD when possible to keep the
    # command readable; fall back to the absolute guest path otherwise.
    guest = mt.dest.rstrip("/")
    cwd_guest = "/workspace"
    if guest == cwd_guest:
        return rel or "."
    if guest.startswith(cwd_guest + "/"):
        return os.path.relpath(os.path.join(guest, rel), cwd_guest)
    return os.path.join(guest, rel)


def loki_start_argv(m: PlatformManifest, config_guest: str, prd: str | None) -> list[str]:
    """Build ``msb exec <name> --user loki -- bash -lc '... loki start ...'``.

    Runs as the unprivileged ``loki`` user (created by bootstrap) so provider
    CLIs (claude/cline) accept ``--dangerously-skip-permissions`` (refused under
    root). We set PATH/HOME explicitly in the inner command because a non-root
    login shell may not source the bootstrap-written PATH.

    Provider auth env (GLM key, z.ai OAuth) is forwarded via ``-e`` so the cline
    node-shim's zai-coding-plan provider authenticates inside the VM.

    ``prd`` is translated from a host-relative path to the path loki sees after
    ``cd /workspace`` (see :func:`_resolve_prd_guest_path`), so
    ``--prd src/PRD.md`` resolves to ``/workspace/PRD.md`` rather than the
    non-existent ``/workspace/src/PRD.md``.
    """
    from microcode.utils import expand_env

    node_ver = m.sandbox.init.packages.node_version
    prefix = (
        f"export PATH=/opt/npm-global/bin:/opt/node{node_ver}/bin:/usr/local/bin:/usr/bin:$PATH "
        f"&& export HOME=/home/loki "
        f"&& cd /workspace "
    )
    prd_arg = _resolve_prd_guest_path(m, prd) if prd else ""
    inner = (
        f"{prefix}&& loki start --config {config_guest} --provider {m.loki.provider}"
        + (" --api" if m.loki.dashboard else " --no-dashboard")
        + " --simple"
        + (f" {prd_arg}" if prd_arg else "")
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
    # enable HUMAN_INPUT.md reading so 'microcode steer' directives are picked
    # up on the next RARV iteration (off by default in loki).
    argv += ["-e", "LOKI_PROMPT_INJECTION=1"]
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
