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
from microcode.manifest import PlatformManifest, SandboxConfig
from microcode import config
from microcode.generators.net import network_argv


def _active_mounts(s: SandboxConfig):
    """Mounts to actually emit as bind/volume flags.

    When ``sync`` is enabled, the sync destination (default /workspace) is
    populated by ``git clone`` instead of a bind mount / named-volume seed, so
    we suppress the mount entry whose ``dest`` matches ``sync.dest``. All other
    mounts (e.g. /workspace/skills) are unaffected.
    """
    if s.sync.enabled:
        return [mt for mt in s.mounts if mt.dest != s.sync.dest]
    return list(s.mounts)


def _create_argv(m: PlatformManifest, bootstrap_guest: str) -> list[str]:
    s = m.sandbox
    argv = ["msb", "create", s.image_ref, "--name", s.name]

    argv += ["--cpus", str(s.cpus)]
    argv += ["--memory", f"{s.memory}M"]
    if s.max_cpus is not None:
        argv += ["--max-cpus", str(s.max_cpus)]
    if s.max_memory is not None:
        argv += ["--max-memory", f"{s.max_memory}M"]
    if s.root_disk:
        argv += ["--root-disk", s.root_disk]

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

    # bind mounts (sync.dest is suppressed when sync clones into it instead)
    for mt in _active_mounts(s):
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
        "--from", m.sandbox.name, "--force",
    ]


def _stop_argv(m: PlatformManifest) -> list[str]:
    """Stop a running sandbox so a snapshot can be captured from it."""
    return ["msb", "stop", m.sandbox.name]


def _bind_to_volume_name(dest: str) -> str:
    """Derive a stable named-volume name from a guest dest path.

    e.g. /workspace -> mcd-workspace, /workspace/skills -> mcd-workspace-skills
    """
    cleaned = dest.strip("/").replace("/", "-") or "root"
    return f"mcd-{cleaned}"


def from_snapshot_mount_map(m: PlatformManifest) -> list[tuple[str, str, str]]:
    """Return [(host_path, volume_name, guest_dest)] for each bind mount.

    Used by the runner to seed named volumes via `msb cp` after booting from a
    snapshot (msb can't bind-mount host paths with --from-snapshot). Host paths
    are returned RAW; the caller resolves them against the project root.
    """
    return [(mt.host, _bind_to_volume_name(mt.dest), mt.dest) for mt in m.sandbox.mounts]


def _from_snapshot_argv(m: PlatformManifest) -> list[str]:
    """Boot a fresh sandbox from an existing snapshot via ``msb run``.

    Mirrors the resources/network/secrets/volumes/mounts/ports of ``_create_argv``
    but starts from the snapshot's filesystem (tools already installed) instead
    of the base image. ``--from-snapshot`` is mutually exclusive with the image
    positional and with ``--copy-file`` bootstrap, so neither is emitted.

    Bind mounts are converted to named volumes (msb can't bind-mount with
    --from-snapshot); the runner seeds them via `msb cp` after boot.
    """
    s = m.sandbox
    argv = ["msb", "run", "--from-snapshot", s.init.snapshot.from_snapshot]
    # --replace: if a sandbox with this name already exists (e.g. left over from
    # a previous build/apply), recreate it from the snapshot instead of silently
    # reusing the stale one (msb would otherwise ignore --from-snapshot).
    argv += ["--name", s.name, "--detach", "--replace"]

    argv += ["--cpus", str(s.cpus)]
    argv += ["--memory", f"{s.memory}M"]
    if s.max_cpus is not None:
        argv += ["--max-cpus", str(s.max_cpus)]
    if s.max_memory is not None:
        argv += ["--max-memory", f"{s.max_memory}M"]
    # NOTE: --root-disk is intentionally NOT emitted for --from-snapshot.
    # msb rejects it ("root_disk() requires an OCI image") because a snapshot
    # already pins the filesystem; the size was set when the snapshot was built
    # (via msb create --root-disk). Adding it here causes a hard error.

    argv += network_argv(s.network)

    for sec in s.secrets:
        argv += ["--secret", f"{sec.env}@{','.join(sec.allow_hosts)}"]

    for v in s.volumes:
        argv += ["-v", f"{v.name}:{v.dest}"]
    if m.loki.memory.storage.enabled:
        st = m.loki.memory.storage
        already = any(v.name == st.volume for v in s.volumes)
        if not already:
            argv += ["-v", f"{st.volume}:{st.dest}"]
    # bind mounts: msb does NOT support bind mounts with --from-snapshot
    # ("mount: Not a directory"). Convert each to a NAMED VOLUME and seed it
    # via `msb cp` in the runner. Volume name is derived from the dest path.
    # sync.dest is suppressed — it is populated by `git clone` instead.
    for mt in _active_mounts(s):
        vol_name = _bind_to_volume_name(mt.dest)
        argv += ["-v", f"{vol_name}:{mt.dest}"]

    for p in s.ports:
        argv += ["-p", p]

    from microcode.utils import expand_env
    for k, v in s.env.items():
        argv += ["-e", f"{k}={expand_env(v)}"]

    argv += ["--user", s.user]
    return argv


def generate_sandbox(
    m: PlatformManifest, bootstrap_guest: str = "/root/bootstrap.sh"
) -> GenerationResult:
    s = m.sandbox
    notes: list[str] = []

    # Booting from an existing snapshot: tools already installed, skip bootstrap.
    if s.init.snapshot.from_snapshot:
        commands: list[list[str]] = [_from_snapshot_argv(m)]
        notes.append(
            f"booting from snapshot '{s.init.snapshot.from_snapshot}'; "
            "bootstrap.sh skipped (tools already installed in the snapshot)"
        )
        return GenerationResult(commands=commands, notes=notes)

    commands = [_create_argv(m, bootstrap_guest)]

    if s.init.snapshot.enabled:
        # snapshot path: run init, STOP the VM, then snapshot. msb requires the
        # source sandbox to be stopped before capturing (running/draining/paused
        # are rejected by msb snapshot create).
        commands.append(_init_argv(m, bootstrap_guest))
        commands.append(_stop_argv(m))
        commands.append(_snapshot_argv(m))
        notes.append(
            f"snapshot caching enabled ({s.init.snapshot.name}); "
            "subsequent applies may start from the snapshot and skip init"
        )
    else:
        commands.append(_init_argv(m, bootstrap_guest))

    return GenerationResult(commands=commands, notes=notes)
