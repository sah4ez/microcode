"""Generator: sync section -> git clone command specs.

When ``sandbox.sync`` is enabled, the workspace (``sync.dest``, default
``/workspace``) is populated by ``git clone`` from ``sync.remote_url`` instead
of a bind mount (build) or a tar+msb-cp seed (apply). This gives the VM a clone
with shared history, so loki commits on top of it and the host can fetch+merge
normally — no "unrelated histories" error.

Credentials are referenced by host env-var name (``auth.token_env`` /
``auth.ssh_key_env``) and resolved host-side via ``expand_env``; the real values
never enter the manifest. For HTTPS the token is injected into the clone URL
(visible to ``ps`` inside the isolated VM — acceptable for dev; for production
use a git credential helper instead).
"""

from __future__ import annotations

from urllib.parse import urlparse

from microcode.generators.base import GenerationResult
from microcode.manifest import PlatformManifest, SyncConfig, NetRule
from microcode.utils import expand_env


def _clone_url(sync: SyncConfig) -> str:
    """Build the clone URL with credentials resolved from the host env.

    HTTPS: inject the token as ``https://<token>@host/path``.
    SSH: return the URL verbatim; the key is passed via ``GIT_SSH_COMMAND``.
    """
    url = sync.remote_url
    if sync.auth is None:
        return url
    if sync.auth.method == "ssh":
        return url
    # https: embed the token (PAT) into the URL.
    token = expand_env("${" + sync.auth.token_env + "}") if sync.auth.token_env else ""
    if not token:
        return url  # public repo, no token needed
    parsed = urlparse(url)
    if parsed.scheme == "https":
        # https://github.com/o/r.git -> https://<token>@github.com/o/r.git
        return f"https://{token}@{parsed.netloc}{parsed.path}"
    return url


def _clone_argv(m: PlatformManifest) -> list[str]:
    """Emit the ``msb exec ... git clone`` argv that populates sync.dest.

    Clones into a temp dir, clears the dest (sparing nested mounts), then moves
    the clone's contents + ``.git`` into place. Runs as root (the dest may be
    root-owned from bootstrap); the caller chowns afterwards.
    """
    sync = m.sandbox.sync
    url = _clone_url(sync)
    branch = sync.branch
    dest = sync.dest
    depth_flag = f"--depth={sync.depth}" if sync.depth and sync.depth > 0 else ""
    # The VM's sandbox name becomes the per-VM branch prefix (vm/<name>).
    sandbox_name = m.sandbox.name

    # SSH: pass the key via GIT_SSH_COMMAND. The key path is resolved host-side
    # and forwarded as an env var; here we reference it by the same name so the
    # orchestrator/runner can inject it via `msb exec -e`.
    ssh_prefix = ""
    if sync.auth and sync.auth.method == "ssh" and sync.auth.ssh_key_env:
        key_path = expand_env("${" + sync.auth.ssh_key_env + "}")
        if key_path:
            ssh_prefix = (
                f'export GIT_SSH_COMMAND="ssh -i {key_path} '
                f'-o StrictHostKeyChecking=accept-new" && '
            )

    # Build the clone command. Clone to /tmp/ws-clone (empty target), then adopt
    # its .git + working tree into dest. Clear dest first (sparing nested mount
    # points like /workspace/skills) so the clone fully owns it.
    depth_arg = f"{depth_flag} " if depth_flag else ""
    script = (
        f"set -e; "
        f"{ssh_prefix}"
        f"rm -rf /tmp/ws-clone && "
        f"git clone {depth_arg}--branch {branch} '{url}' /tmp/ws-clone && "
        f"mkdir -p {dest} && "
        f"find {dest} -mindepth 1 -maxdepth 1 "
        f"-path {dest}/skills -prune -o -exec rm -rf {{}} + && "
        f"shopt -s dotglob && "
        f"mv /tmp/ws-clone/* {dest}/ && "
        f"rmdir /tmp/ws-clone && "
        f"cd {dest} && "
        f"git checkout -b vm/{sandbox_name} {branch} 2>/dev/null || git checkout vm/{sandbox_name} && "
        f'git config user.name "Loki" && '
        f'git config user.email "loki@local" && '
        f'echo "vm/{sandbox_name}" > {dest}/.loki/state/sync-branch.txt 2>/dev/null || true'
    )
    return [
        "msb", "exec", m.sandbox.name, "--user", "root", "--",
        "bash", "-lc", script,
    ]


def sync_egress_rules(sync: SyncConfig) -> list[NetRule]:
    """Network allow-rules for the git remote host (auto-egress).

    Parses ``sync.remote_url`` and returns the allow-rule(s) needed for the VM
    to reach the git server (tcp/443 for https, tcp/22 for ssh). The caller
    merges these into the sandbox network config so the user does not have to
    manually allowlist the git host.
    """
    if not sync.enabled or not sync.remote_url:
        return []
    parsed = urlparse(sync.remote_url)
    # ssh://host:port/path  OR  git@host:path (scp-like) OR  https://host/path
    if parsed.scheme in ("https", "http", "ssh") and parsed.hostname:
        host = parsed.hostname
        port = parsed.port
    elif "@" in sync.remote_url and ":" in sync.remote_url.split("@", 1)[1]:
        # scp-like: git@github.com:org/repo.git
        host = sync.remote_url.split("@", 1)[1].split(":", 1)[0]
        port = None
    else:
        return []
    if port is None:
        # Infer default port from the URL scheme (auth.method is optional and
        # may be unset for public repos). https → 443, ssh/scp-like → 22.
        if parsed.scheme == "https" or parsed.scheme == "http":
            port = 443
        else:
            port = 22
    return [
        NetRule(action="allow", target=host, port=port, proto="tcp"),
    ]


def generate_sync(m: PlatformManifest) -> GenerationResult:
    """Generate the git-clone command spec when sync is enabled.

    Returns an empty result (no commands) when sync is disabled, so the caller
    can unconditionally call this and branch on ``result.commands``.
    """
    sync = m.sandbox.sync
    if not sync.enabled:
        return GenerationResult()
    commands = [_clone_argv(m)]
    notes = [
        f"sync: git clone {sync.remote_url} (branch {sync.branch}) -> {sync.dest}",
        "sync.dest mount suppressed; workspace populated by clone instead",
    ]
    return GenerationResult(commands=commands, notes=notes)
