"""Runner: drives microsandbox (``msb``) to provision and init the VM.

Responsibilities:
* Ensure ``bootstrap.sh`` exists on the host (written by the orchestrator) and
  is executable (mode is inherited by ``msb --copy-file``).
* Resolve the ``{BOOTSTRAP_NAME}`` placeholder produced by the sandbox
  generator into the real host artifact path before execution.
* Run create -> (optional init/snapshot) commands.
"""

from __future__ import annotations

import os
from pathlib import Path

from microcode import config, logging_utils
from microcode.runners.base import ShellRunner, require


class SandboxRunner(ShellRunner):
    def __init__(
        self,
        artifacts_dir: Path,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(cwd=cwd, env=env)
        self.artifacts_dir = Path(artifacts_dir)

    def run(self, commands: list[list[str]], dry_run: bool = False) -> None:
        if not dry_run:
            require("msb")
        # ensure bootstrap.sh is executable so the copied file inherits 0755
        bs = self.artifacts_dir / config.BOOTSTRAP_NAME
        if bs.exists():
            try:
                os.chmod(bs, 0o755)
            except OSError as e:  # pragma: no cover - best effort
                logging_utils.warn(f"could not chmod {bs}: {e}")

        # auto-create writable host mount directories before msb create/run.
        # msb bind-mounts require the host path to exist; otherwise it either
        # errors or creates it as root, which the unprivileged `loki` user then
        # can't write to (bootstrap chowns /workspace, loki writes results).
        if not dry_run:
            self._ensure_mount_dirs(commands)

        resolved = [self._resolve_placeholders(argv) for argv in commands]
        super().run(resolved, dry_run=dry_run)

    def _ensure_mount_dirs(self, commands: list[list[str]]) -> None:
        """Create host-side dirs for writable bind mounts (host:dest[:ro])."""
        from pathlib import Path

        cwd = Path(self.cwd) if self.cwd else Path.cwd()
        for argv in commands:
            if argv[:2] not in (("msb", "create"), ("msb", "run")):
                continue
            for i, tok in enumerate(argv):
                if tok != "-v" or i + 1 >= len(argv):
                    continue
                spec = argv[i + 1]
                # skip named volumes (bare name, no '/'), and readonly mounts
                if spec.endswith(":ro") or ":" not in spec:
                    continue
                host = spec.split(":", 1)[0]
                # resolve relative to cwd (same as _resolve_placeholders)
                p = Path(host)
                if not p.is_absolute():
                    p = (cwd / host)
                if not p.exists():
                    try:
                        p.mkdir(parents=True, exist_ok=True)
                    except OSError as e:  # pragma: no cover - best effort
                        logging_utils.warn(f"could not create mount dir {p}: {e}")

    def _resolve_placeholders(self, argv: list[str]) -> list[str]:
        host_bs = str(self.artifacts_dir / config.BOOTSTRAP_NAME)
        host_shim = str(self.artifacts_dir / "cline-node-shim.cjs")
        cwd = Path(self.cwd) if self.cwd else Path.cwd()
        out: list[str] = []
        for tok in argv:
            # the generator emits "--copy-file bootstrap.sh:/root/bootstrap.sh"
            if tok.startswith(f"{config.BOOTSTRAP_NAME}:"):
                tok = f"{host_bs}:{tok.split(':', 1)[1]}"
            # resolve relative host bind-mount paths to absolute (msb resolves
            # -v paths relative to its own cwd, which may differ from ours).
            # spec form: host:dest[:ro] ; only touch the host (first) segment.
            if tok == "-v" or tok == "--volume":
                pass  # handled below when we hit the value
            out.append(tok)
        # second pass: absolutize the value following each -v/--volume
        for i, tok in enumerate(out):
            if tok in ("-v", "--volume") and i + 1 < len(out):
                spec = out[i + 1]
                parts = spec.split(":")
                host = parts[0]
                # skip named volumes (bare name, no '/') and already-absolute
                if "/" in host and not host.startswith("/"):
                    parts[0] = str((cwd / host).resolve())
                    out[i + 1] = ":".join(parts)
        # inject the cline node-shim as an extra rootfs patch on the create cmd
        # (used by bootstrap on arm64 VMs where cline's Bun binary crashes).
        if (
            argv[:2] == ["msb", "create"]
            and "--copy-file" in out
            and Path(host_shim).exists()
            and "cline-node-shim.cjs" not in " ".join(out)
        ):
            i = out.index("--copy-file")
            # insert a second --copy-file pair right after the bootstrap one
            out[i + 2 : i + 2] = ["--copy-file", f"{host_shim}:/opt/cline-shim/cline-node-shim.cjs"]
        return out
