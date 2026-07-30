"""Generator: sandbox section -> msb (microsandbox) CLI command specs.

We emit argv lists (not shell strings) for deterministic display and safe
subprocess execution. Three phases:

1. ``create``  — boot the debian VM with rootfs-patch injecting bootstrap.sh,
                 plus resources / network / secrets / volumes / mounts / ports.
2. ``init``    — ``msb exec <name> -- bash /root/bootstrap.sh`` (skipped if a
                 cached snapshot is used).
3. ``snapshot``— optional ``msb snapshot create`` to cache the installed env.

The ``loki start`` invocation is emitted by the loki runner, not here.
"""

from __future__ import annotations

from microcode.generators.base import GeneratedArtifact, GenerationResult
from microcode.manifest import PlatformManifest
from microcode import config
from microcode.generators.net import network_argv


def _create_argv(m: PlatformManifest, bootstrap_guest: str) -> list[str]:
    s = m.sandbox
    argv = ["msb", "create", s.image_ref, "--name", s.name]

    argv += ["--cpus", str(s.cpus)]
    argv += ["--memory", f"{s.memory}M"]
    if s.max_cpus is not None:
        argv += ["--max-cpus", str(s.max_cpus)]
    if s.max_memory is not None:
        argv += ["--max-memory", f"{s.max_memory}M"]

    # network policy (profile OR allowlist/denylist; mutually exclusive in msb)
    argv += network_argv(s.network)

    # inject bootstrap.sh into rootfs (host path is filled by the runner; we use
    # a stable placeholder token so the planner can resolve it to the artifact path)
    argv += ["--copy-file", f"{config.BOOTSTRAP_NAME}:{bootstrap_guest}"]

    # secrets: ENV@host1,host2  (value resolved from host env by msb; never inlined)
    for sec in s.secrets:
        argv += ["--secret", f"{sec.env}@{','.join(sec.allow_hosts)}"]

    # named volumes
    for v in s.volumes:
        argv += ["-v", f"{v.name}:{v.dest}"]

    # auto-mount the loki external memory volume when enabled (so users only
    # configure it once under loki.memory.storage, not duplicated in volumes).
    if m.loki.memory.storage.enabled:
        st = m.loki.memory.storage
        already = any(v.name == st.volume for v in s.volumes)
        if not already:
            argv += ["-v", f"{st.volume}:{st.dest}"]

    # bind mounts
    for mt in s.mounts:
        spec = f"{mt.host}:{mt.dest}"
        if mt.readonly:
            spec += ":ro"
        argv += ["-v", spec]

    # ports
    for p in s.ports:
        argv += ["-p", p]

    # env — expand ${VAR} from the host environment (secrets/paths)
    from microcode.utils import expand_env

    for k, v in s.env.items():
        argv += ["-e", f"{k}={expand_env(v)}"]

    argv += ["--user", s.user]
    return argv


def _init_argv(m: PlatformManifest, bootstrap_guest: str) -> list[str]:
    return [
        "msb", "exec", m.sandbox.name,
        "--user", m.sandbox.user,
        "--", "bash", bootstrap_guest,
    ]


def _snapshot_argv(m: PlatformManifest) -> list[str]:
    return [
        "msb", "snapshot", "create", m.sandbox.init.snapshot.name,
        "--from", m.sandbox.name,
    ]


def generate_sandbox(
    m: PlatformManifest, bootstrap_guest: str = "/root/bootstrap.sh"
) -> GenerationResult:
    s = m.sandbox
    commands: list[list[str]] = [_create_argv(m, bootstrap_guest)]
    notes: list[str] = []

    if s.init.snapshot.enabled:
        # snapshot path: run init, then snapshot. (When re-applying from an
        # existing snapshot the runner would skip the init step instead.)
        commands.append(_init_argv(m, bootstrap_guest))
        commands.append(_snapshot_argv(m))
        notes.append(
            f"snapshot caching enabled ({s.init.snapshot.name}); "
            "subsequent applies may start from the snapshot and skip init"
        )
    else:
        commands.append(_init_argv(m, bootstrap_guest))

    return GenerationResult(commands=commands, notes=notes)
