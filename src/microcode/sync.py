"""Sync loki's workspace commits from the VM back to the host repository.

``apply`` seeds the VM's ``/workspace`` from a git remote (``sandbox.sync``).
loki then commits its work on top. ``microcode sync`` pulls those commits back:
it bundles the VM-side commits (those ahead of the cloned base branch) into a
git bundle, copies the bundle to the host, fetches it, and applies the new
commits onto the host branch — either via ``cherry-pick`` (linear history,
default) or ``merge`` (preserves the VM commit topology).

This is the reverse direction of ``sandbox.sync`` (host → VM clone): VM → host.

The sync is robust against the three common failure modes:
    1. VM has no new commits → "already up to date" (no error).
    2. VM commits already on the host → detected via ``git cherry`` (patch-id
       aware) so re-running sync is idempotent (no "empty cherry-pick" crash).
    3. VM commits conflict with the host → clean abort with an actionable hint.

Public surface:
    - :func:`sync_from_vm` — the high-level entry point used by the CLI.
    - :func:`build_vm_bundle_argv` / :func:`build_host_fetch_argv` /
      :func:`build_host_apply_argv` — pure argv builders, factored out for
      unit testing.
    - :func:`_new_commits` — cherry-aware count of genuinely-new commits.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
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

# Namespace under which the fetched VM tip is materialised on the host, so the
# VM's generated branch name (a session id) doesn't pollute the host refs.
VM_REF = "from-vm/sync"


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


def build_host_fetch_argv(bundle_host: str) -> list[str]:
    """Build the ``git fetch`` argv that materialises the bundle on the host.

    Fetches the bundle's HEAD under the :data:`VM_REF` namespace so the VM
    branch name (a generated session id) doesn't pollute the host refs.
    """
    return ["git", "fetch", bundle_host, f"HEAD:refs/heads/{VM_REF}"]


def build_host_apply_argv(
    bundle_host: str,
    branch_host: str,  # noqa: ARG001 — kept for backwards compat with tests
    strategy: str = "cherry-pick",
) -> list[list[str]]:
    """Build the host-side git argv to fetch the bundle and apply its commits.

    Kept for backwards compatibility with the unit tests; :func:`sync_from_vm`
    uses the decomposed :func:`build_host_fetch_argv` plus an explicit
    cherry-pick/merge so it can detect an empty range (VM already in sync)
    BEFORE attempting an apply that would fail with a cryptic error.
    """
    fetch = build_host_fetch_argv(bundle_host)
    if strategy == "merge":
        apply: list[str] = ["git", "merge", "--no-edit", VM_REF]
    else:
        # Find the shared ancestor and cherry-pick the range oldest-first.
        apply = [
            "bash", "-c",
            f"base=$(git merge-base HEAD {VM_REF}) && "
            f"git cherry-pick $base..{VM_REF}",
        ]
    return [fetch, apply]


def _run(argv: list[str], cwd: str | None = None) -> str:
    """Run *argv* and return stdout; raise RunnerError on non-zero exit.

    ``argv[0]`` may be ``bash`` (for the cherry-pick wrapper) — that's fine, it
    resolves via PATH.
    """
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


def _new_commits(root: str, vm_ref: str = VM_REF) -> int:
    """Count commits in *vm_ref* not already present in HEAD (cherry-aware).

    Uses ``git cherry HEAD <vm_ref>`` which lists ``-`` for commits already in
    HEAD (by patch-id) and ``+`` for genuinely-new ones. This makes sync
    idempotent: commits already cherry-picked onto the host are not re-applied,
    so re-running sync after a previous successful run reports 0 and exits
    cleanly instead of crashing on an empty cherry-pick range.

    Returns 0 when the VM branch is fully contained in HEAD.
    """
    out = _run(["git", "-C", root, "cherry", "HEAD", vm_ref], cwd=root)
    return sum(1 for line in out.splitlines() if line.startswith("+ "))


def sync_from_vm(
    m: PlatformManifest,
    root: Path,
    strategy: str = "cherry-pick",
    dry_run: bool = False,
) -> int:
    """Pull loki's workspace commits from the VM into the host repo at *root*.

    Returns the number of commits applied (0 if the VM has nothing new, or if
    the host already has all of them).

    Steps:
    1. Create a git bundle of ``{base}..HEAD`` inside the VM.
    2. ``msb cp`` the bundle to a host temp file.
    3. On the host: fetch the bundle, count genuinely-new commits (cherry-aware),
       and — if any — cherry-pick (or merge) them onto the current branch.

    Robustness:
    - Empty VM (no commits ahead of base) → bundle step fails → "up to date".
    - VM commits already on host → ``_new_commits`` returns 0 → "up to date".
    - Conflict during apply → clean abort (``cherry-pick --abort`` /
      ``merge --abort``) with an actionable message.

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
        fetch_cmd = build_host_fetch_argv(bundle_host)

        logging_utils.cmd(" ".join(vm_cmd[:6]) + " ...")
        logging_utils.cmd(" ".join(cp_cmd))
        logging_utils.cmd(" ".join(fetch_cmd[:6]) + " ...")

        if dry_run:
            return 0

        # 1. bundle inside the VM. git bundle fails (non-zero) when the range
        #    {base}..HEAD is empty, i.e. the VM has no commits ahead of the
        #    cloned base — that is the "already up to date" case.
        logging_utils.step(f"Bundling VM commits ({base_ref}..HEAD)")
        try:
            _run(vm_cmd)
        except RunnerError:
            logging_utils.ok(
                "VM has no new commits to sync (nothing ahead of "
                f"{base_ref}); host is already up to date"
            )
            return 0

        # 2. copy bundle to host
        logging_utils.step("Copying bundle to host")
        _run(cp_cmd)

        if not os.path.exists(bundle_host) or os.path.getsize(bundle_host) == 0:
            logging_utils.ok("VM bundle is empty — already up to date")
            return 0

        # 3. fetch the bundle into from-vm/sync
        logging_utils.step(f"Fetching bundle into {VM_REF}")
        _run(fetch_cmd, cwd=str(root))

        # 4. Count commits that the VM branch has but HEAD does NOT already
        #    contain (cherry-aware: commits already applied to the host are
        #    excluded by their patch-id). This avoids the most common failure —
        #    re-applying commits that are already on the host → empty
        #    cherry-pick range → cryptic error.
        new_commits = _new_commits(str(root))
        if new_commits == 0:
            logging_utils.ok("VM commits are already on the host (up to date)")
            return 0

        # 5. apply the genuinely-new commits
        logging_utils.step(
            f"Applying {new_commits} new commit(s) to host ({strategy})"
        )
        try:
            if strategy == "merge":
                _run(["git", "merge", "--no-edit", VM_REF], cwd=str(root))
            else:
                # cherry-pick the range oldest-first; merge-base is the shared
                # ancestor between the host HEAD and the VM branch.
                _run(
                    [
                        "bash", "-c",
                        f"base=$(git merge-base HEAD {VM_REF}) && "
                        f"git cherry-pick $base..{VM_REF}",
                    ],
                    cwd=str(root),
                )
        except RunnerError as e:
            # A conflict leaves the repo mid-cherry-pick / mid-merge. Abort so
            # the working tree is clean and the user can retry after resolving
            # divergence manually (e.g. via git checkout of specific files).
            # `--abort` is a no-op when no cherry-pick/merge is in progress.
            _run_safe_abort(["git", "cherry-pick", "--abort"], str(root))
            _run_safe_abort(["git", "merge", "--abort"], str(root))
            raise MicrocodeError(
                f"VM commits conflict with the host branch ({new_commits} new "
                f"commit(s)). Sync aborted, working tree restored.\n"
                f"  Cause: {e}\n"
                f"To resolve: inspect 'git log {VM_REF}' and apply the commits "
                f"manually, or re-run with '-s merge'."
            ) from e

        logging_utils.ok(f"synced {new_commits} commit(s) from VM to host")
        return new_commits


def _run_safe_abort(argv: list[str], root: str) -> None:
    """Run an abort command, ignoring any error (it's best-effort cleanup)."""
    try:
        subprocess.run(argv, cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        pass


def is_viable(m: PlatformManifest) -> bool:
    """True if ``microcode sync`` can work for this manifest.

    Requires ``sandbox.sync.enabled`` (shared git history) — the tar-seed path
    has no git history to bundle.
    """
    return bool(m.sandbox.sync.enabled)
