"""Tests for the VM → host sync command (microcode.sync).

These cover the pure argv builders (build_vm_bundle_argv, build_cp_argv,
build_host_apply_argv), the base-ref resolution, and the viability check.
The end-to-end bundle/copy/apply flow needs a live VM and is exercised
manually against test-todo2 instead.
"""

from __future__ import annotations

import pytest

from microcode.manifest import PlatformManifest, SyncConfig
from microcode.sync import (
    DEFAULT_BASE_REF,
    build_cp_argv,
    build_host_apply_argv,
    build_vm_bundle_argv,
    is_viable,
    _resolve_base_ref,
)


def _m(**over) -> PlatformManifest:
    base: dict = {"version": 1}
    base.update(over)
    return PlatformManifest.model_validate(base)


def _m_with_sync(**sync_over) -> PlatformManifest:
    sync = {"enabled": True, "remote_url": "https://github.com/o/r.git"}
    sync.update(sync_over)
    return _m(sandbox={"name": "notes-build", "sync": sync})


# ---- base ref resolution -------------------------------------------------- #

def test_resolve_base_ref_uses_sync_branch():
    m = _m_with_sync(branch="master")
    assert _resolve_base_ref(m) == "origin/master"


def test_resolve_base_ref_defaults_to_main_when_not_set():
    m = _m_with_sync()
    assert _resolve_base_ref(m) == "origin/main"


def test_resolve_base_ref_falls_back_to_main_when_sync_disabled():
    m = _m(sandbox={"name": "x"})
    assert _resolve_base_ref(m) == "origin/main"


def test_default_base_ref_template_formats():
    assert DEFAULT_BASE_REF.format(branch="trunk") == "origin/trunk"


# ---- viability ------------------------------------------------------------ #

def test_is_viable_true_when_sync_enabled():
    assert is_viable(_m_with_sync()) is True


def test_is_viable_false_when_sync_disabled():
    assert is_viable(_m(sandbox={"name": "x"})) is False


# ---- vm bundle argv ------------------------------------------------------- #

def test_build_vm_bundle_argv_uses_msb_exec_loki_user():
    argv = build_vm_bundle_argv(
        "notes-build", "origin/master",
        "/workspace/.microcode-sync.bundle", "/workspace",
    )
    assert argv[0] == "msb"
    assert argv[1] == "exec"
    assert argv[2] == "notes-build"
    assert "--user" in argv and "loki" in argv
    assert argv[-2] == "bash" and argv[-1] == "-c" or argv[-1].startswith("cd ")


def test_build_vm_bundle_argv_script_bundles_base_dot_dot_head():
    argv = build_vm_bundle_argv(
        "sb", "origin/master", "/tmp/b.bundle", "/workspace",
    )
    script = argv[-1]
    assert "git bundle create /tmp/b.bundle origin/master..HEAD" in script
    assert "cd /workspace" in script


def test_build_vm_bundle_argv_validates_base_ref_exists():
    argv = build_vm_bundle_argv(
        "sb", "origin/master", "/tmp/b.bundle", "/workspace",
    )
    script = argv[-1]
    assert "git rev-parse --verify origin/master" in script
    assert "exit 1" in script


def test_build_vm_bundle_argv_respects_custom_workspace():
    argv = build_vm_bundle_argv(
        "sb", "origin/main", "/data/b.bundle", "/data/ws",
    )
    script = argv[-1]
    assert "cd /data/ws" in script
    assert "git bundle create /data/b.bundle" in script


# ---- cp argv -------------------------------------------------------------- #

def test_build_cp_argv_copies_guest_to_host():
    argv = build_cp_argv("notes-build", "/workspace/.microcode-sync.bundle", "/tmp/sync.bundle")
    assert argv == [
        "msb", "cp",
        "notes-build:/workspace/.microcode-sync.bundle",
        "/tmp/sync.bundle",
    ]


# ---- host apply argv ------------------------------------------------------ #

def test_build_host_apply_argv_cherry_pick_default():
    cmds = build_host_apply_argv("/tmp/s.bundle", "/repo", strategy="cherry-pick")
    assert len(cmds) == 2
    fetch = cmds[0]
    assert fetch[0] == "git" and fetch[1] == "fetch"
    assert "/tmp/s.bundle" in fetch
    assert any("from-vm/sync" in a for a in fetch)
    # cherry-pick strategy uses a bash wrapper that finds the merge-base
    cp = cmds[1]
    assert cp[0] == "bash"
    assert "merge-base" in cp[2]
    assert "cherry-pick" in cp[2]


def test_build_host_apply_argv_merge_strategy():
    cmds = build_host_apply_argv("/tmp/s.bundle", "/repo", strategy="merge")
    assert len(cmds) == 2
    merge = cmds[1]
    assert merge[0] == "git"
    assert merge[1] == "merge"
    assert "--no-edit" in merge
    assert any("from-vm/sync" in a for a in merge)


def test_build_host_apply_argv_fetch_uses_head_ref():
    cmds = build_host_apply_argv("/tmp/s.bundle", "/repo")
    fetch = cmds[0]
    assert "HEAD:refs/heads/from-vm/sync" in fetch
