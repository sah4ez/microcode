"""Sync loki's workspace commits from the VM back to the host repository.

``apply`` seeds the VM's ``/workspace`` from a git remote (``sandbox.sync``).
loki then commits its work on top. ``microcode sync`` pulls those commits back:
it bundles the VM-side commits (those ahead of the cloned base branch) into a
git bundle, copies the bundle to the host, fetches it, and applies the new
commits onto the host branch — either via ``cherry-pick`` (linear history,
default) or ``merge`` (preserves the VM commit topology).

This is the reverse direction of ``sandbox.sync`` (host → VM clone): VM → host.

Public surface:
    - :func:`sync_from_vm` — the high-level entry point used by the CLI.
    - :func:`build_vm_bundle_argv` / :func:`build_host_apply_argv` — pure argv
      builders, factored out for unit testing.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from microcode import logging_utils
from microcode.errors import MicrocodeError, RunnerError
from microcode.manifest import PlatformManifest


# What counts as "the base": the ref the VM cloned from. Loki commits on top of
# this ref inside /workspace, so the range ``{base}..HEAD`` is exactly its work.
DEFAULT_BASE_REF = "origin/{branch}"

# The guest path the workspace is cloned into (sandbox.sync.dest, /workspace by
# default). Kept as a constant because the bundle command runs inside the VM and
# needs the guest path, not a host path.
DEFAULT_WORKSPACE_GUEST = "/workspace"


@dataclass
class SyncPlan:
    """The commands and refs that make up a VM → host sync.

    ``vm_cmds`` run inside the VM via ``msb exec`` (create + locate the bundle);
    ``cp_cmds`` run on the host via ``msb cp`` (transfer the bundle file);
    ``host_cmds`` run on the host (fetch + apply the fetched commits).
    """

    base_ref: str
    """The ref the VM cloned from; loki's commits are ``{base_ref}..HEAD``."""

    vm_cmds: list[list[str]] = field(default_factory=list)
    cp_cmds: list[list[str]] = field(default_factory=list)
    host_cmds: list[list[str]] = field(default_factory=list)


def _resolve_base_ref(m: PlatformManifest) -> str:
    """The base ref the VM cloned from, as seen inside the VM's /workspace.

    ``sandbox.sync.branch`` is the branch cloned (default ``main``); the clone
    records it as ``origin/{branch}``. Loki commits land on a per-VM branch
    (``vm/{name}`` or ``loki/session-*``) on top of it, so the work to sync is
    the range ``origin/{branch}..HEAD``.
    """
    branch = m.sandbox.sync.branch if m.sandbox.sync.enabled else "main"
    return DEFAULT_BASE_REF.format(branch=branch)


def build_vm_bundle_argv(name: str, base_ref: str, bundle_guest: str, workspace_guest: str) -> list[str]:
    """Build the ``msb exec`` argv that bundles VM-side commits into a file.

    Runs ``git bundle create {bundle_guest} {base_ref}..HEAD`` inside the VM's
    workspace. The ``base_ref..HEAD`` range captures exactly the commits loki
    made on top of the clone. We ``git rev-parse`` the base first so a missing
    base ref (e.g. branch renamed on the remote) fails loudly here, not as a
    cryptic bundle-verify error on the host.
    """
    script = (
        f"cd {workspace_guest} && "
        f"git rev-parse --verify {base_ref} >/dev/null 2>&1 || "
        f"{{ echo 'sync: base ref {base_ref} not found in VM git' >&2; exit 1; }} && "
        f"git bundle create {bundle_guest} {base_ref}..HEAD"
    )
    return ["msb", "exec", name, "--user", "loki", "--", "bash", "-c", script]


def build_cp_argv(name: str, bundle_guest: str, bundle_host: str) -> list[str]:
    """Build the ``msb cp`` argv that copies the bundle from VM to host."""
    return ["msb", "cp", f"{name}:{bundle_guest}", bundle_host]


def build_host_apply_argv(
    bundle_host: str,
    branch_host: str,
    strategy: str = "cherry-pick",
) -> list[list[str]]:
    """Build the host-side git argv to fetch the bundle and apply its commits.

    ``fetch`` materialises the bundle's ref under ``from-vm/*`` so we can
    reference it regardless of the VM branch name (which is a generated
    session id). Then:

    - ``cherry-pick`` (default): re-applies each VM commit onto the current host
      branch, giving a linear history. Best when the host branch has diverged
      independently (e.g. the user committed a config tweak on the host while
      loki worked in the VM).
    - ``merge``: preserves the VM commit SHAs and topology as a merge commit.
      Faster when there are many commits and the host branch hasn't moved.
    """
    # Fetch the bundle's commits under a from-vm/* namespace so the VM branch
    # name (a session id) doesn't pollute the host's refs. We fetch HEAD so the
    # tip of the VM branch is available, plus the range guarantees the base.
    fetch = ["git", "fetch", bundle_host, "HEAD:refs/heads/from-vm/sync"]
    if strategy == "merge":
        apply = ["git", "merge", "--no-edit", "from-vm/sync"]
    else:  # cherry-pick the whole range; FETCH_HEAD points at the bundle tip
        apply = ["git", "cherry-pick", "FETCH_HEAD...from-vm/sync"]
    # cherry-pick needs the commits, not the tip: use the fetched branch's
    # history. The simplest correct range is what the bundle carries; since we
    # only bundled base..HEAD, cherry-pick the fetched branch squashed is
    # risky. Instead, cherry-pick the explicit list of commits oldest-first.
    if strategy == "cherry-pick":
        # The bundle carries base..HEAD; after fetch, from-vm/sync == the tip.
        # The host may not share the base ref by the same name, so find the
        # merge-base dynamically and cherry-pick the range oldest-first.
        apply = [
            "bash", "-c",
            "base=$(git merge-base HEAD from-vm/sync) && "
            "git cherry-pick $base..from-vm/sync",
        ]
    return [fetch, apply]


def _run(argv: list[str], cwd: str | None = None) -> str:
    """Run *argv* and return stdout; raise RunnerError on non-zero exit."""
    line = " ".join(argv)
    try:
        result = subprocess.run(
            argv, cwd=cwd, check=True, capture_output=True, text=True,
        )
        return result.stdout
    except FileNotFoundError as e:
        raise RunnerError(f"command not found: {argv[0]}") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {e.returncode}"
        raise RunnerError(f"command failed ({tail}): {line}") from e


def sync_from_vm(
    m: PlatformManifest,
    root: Path,
    strategy: str = "cherry-pick",
    dry_run: bool = False,
) -> int:
    """Pull loki's workspace commits from the VM into the host repo at *root*.

    Returns the number of commits applied (0 if the VM has nothing new).

    Steps:
    1. Create a git bundle of ``{base}..HEAD`` inside the VM.
    2. ``msb cp`` the bundle to a host temp file.
    3. On the host: fetch the bundle, then cherry-pick (or merge) the commits.

    Skipped with a warning (returns 0) when ``sandbox.sync`` is disabled —
    without a clone there is no shared git history to bundle, and ``apply``
    would have tar-seeded the workspace instead.
    """
    from microcode.runners.base import require

    require("msb", "git")

    if not m.sandbox.sync.enabled:
        logging_utils.warn(
            "sandbox.sync is disabled — the VM workspace was tar-seeded, not "
            "git-cloned, so there is no shared history to sync. Skipping."
        )
        return 0

    name = m.sandbox.name
    base_ref = _resolve_base_ref(m)
    workspace_guest = m.sandbox.sync.dest.rstrip("/") or DEFAULT_WORKSPACE_GUEST

    with tempfile.TemporaryDirectory(prefix="microcode-sync-") as tmp:
        bundle_guest = f"{workspace_guest}/.microcode-sync.bundle"
        bundle_host = str(Path(tmp) / "sync.bundle")

        vm_cmd = build_vm_bundle_argv(name, base_ref, bundle_guest, workspace_guest)
        cp_cmd = build_cp_argv(name, bundle_guest, bundle_host)
        host_cmds = build_host_apply_argv(bundle_host, str(root), strategy)

        logging_utils.cmd(" ".join(vm_cmd[:6]) + " ...")
        logging_utils.cmd(" ".join(cp_cmd))
        for hc in host_cmds:
            logging_utils.cmd(" ".join(hc[:6]) if len(hc) > 6 else " ".join(hc))

        if dry_run:
            return 0

        # 1. bundle inside the VM
        logging_utils.step(f"Bundling VM commits ({base_ref}..HEAD)")
        _run(vm_cmd)

        # 2. copy bundle to host. An empty bundle means the VM has nothing new
        #    (loki hasn't committed on top of the clone). git bundle creates a
        #    valid but empty-ish bundle in that case; detect via bundle verify.
        logging_utils.step("Copying bundle to host")
        _run(cp_cmd)

        if not os.path.exists(bundle_host) or os.path.getsize(bundle_host) == 0:
            logging_utils.ok("VM has no new commits to sync (already up to date)")
            return 0

        # 3. fetch + apply on the host
        logging_utils.step(f"Applying commits to host ({strategy})")
        for hc in host_cmds:
            _run(hc, cwd=str(root))

        # Count applied commits for the summary.
        count_out = _run(
            ["git", "-C", str(root), "rev-list", "--count",
             f"{base_ref}..from-vm/sync"],
            cwd=str(root),
        )
        # origin/{branch} may not exist by that name on the host after a fresh
        # clone naming; fall back to merge-base counting.
        try:
            n = int(count_out.strip())
        except ValueError:
            mb = _run(
                ["git", "-C", str(root), "merge-base", "HEAD", "from-vm/sync"],
                cwd=str(root),
            ).strip()
            n_out = _run(
                ["git", "-C", str(root), "rev-list", "--count", f"{mb}..from-vm/sync"],
                cwd=str(root),
            )
            try:
                n = int(n_out.strip())
            except ValueError:
                n = 0

        logging_utils.ok(f"synced {n} commit(s) from VM to host")
        return n


def is_viable(m: PlatformManifest) -> bool:
    """True if ``microcode sync`` can work for this manifest.

    Requires ``sandbox.sync.enabled`` (shared git history) — the tar-seed path
    has no git history to bundle.
    """
    return bool(m.sandbox.sync.enabled)
