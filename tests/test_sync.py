"""Tests for the git-sync (sandbox.sync) feature: SyncConfig, the clone command
generator, mount suppression, auto-egress, and plan integration."""

from __future__ import annotations

import os

import pytest

from microcode.generators import generate_sandbox, generate_sync, sync_egress_rules
from microcode.generators.sandbox import _active_mounts
from microcode.generators.sync import _clone_url
from microcode.manifest import PlatformManifest, SyncAuth, SyncConfig
from microcode.planner import build_plan


def _m(**over) -> PlatformManifest:
    base: dict = {"version": 1}
    base.update(over)
    return PlatformManifest.model_validate(base)


def _m_with_sync(**sync_over) -> PlatformManifest:
    sync = {"enabled": True, "remote_url": "https://github.com/o/r.git"}
    sync.update(sync_over)
    return _m(sandbox={"name": "sb1", "sync": sync})


# ---- SyncConfig validation ------------------------------------------------ #

def test_sync_config_defaults_disabled():
    s = SyncConfig()
    assert s.enabled is False
    assert s.remote_url == ""
    assert s.branch == "main"
    assert s.dest == "/workspace"
    assert s.depth == 1


def test_sync_config_enabled_requires_remote_url():
    with pytest.raises(Exception):
        SyncConfig(enabled=True)


def test_sync_config_enabled_with_remote_ok():
    s = SyncConfig(enabled=True, remote_url="https://github.com/o/r.git")
    assert s.enabled is True
    assert s.remote_url == "https://github.com/o/r.git"


def test_sync_auth_methods():
    a = SyncAuth(method="https", token_env="GH_TOKEN")
    assert a.method == "https"
    assert a.token_env == "GH_TOKEN"
    b = SyncAuth(method="ssh", ssh_key_env="SYNC_SSH_KEY")
    assert b.method == "ssh"
    assert b.ssh_key_env == "SYNC_SSH_KEY"


# ---- clone URL building --------------------------------------------------- #

def test_clone_url_https_injects_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_abc123")
    s = SyncConfig(enabled=True, remote_url="https://github.com/o/r.git",
                   auth=SyncAuth(method="https", token_env="GH_TOKEN"))
    assert _clone_url(s) == "https://ghp_abc123@github.com/o/r.git"


def test_clone_url_https_no_token_for_public_repo():
    s = SyncConfig(enabled=True, remote_url="https://github.com/o/r.git")
    # no auth → URL verbatim (public repo)
    assert _clone_url(s) == "https://github.com/o/r.git"


def test_clone_url_ssh_verbatim(monkeypatch):
    monkeypatch.setenv("SYNC_SSH_KEY", "/home/loki/.ssh/id")
    s = SyncConfig(enabled=True, remote_url="ssh://git@git.int:2222/r.git",
                   auth=SyncAuth(method="ssh", ssh_key_env="SYNC_SSH_KEY"))
    # SSH: URL unchanged; the key goes via GIT_SSH_COMMAND, not the URL
    assert _clone_url(s) == "ssh://git@git.int:2222/r.git"


# ---- auto-egress ---------------------------------------------------------- #

def test_egress_https_443():
    s = SyncConfig(enabled=True, remote_url="https://github.com/o/r.git")
    rules = sync_egress_rules(s)
    assert len(rules) == 1
    assert rules[0].target == "github.com"
    assert rules[0].port == 443
    assert rules[0].proto == "tcp"


def test_egress_ssh_custom_port():
    s = SyncConfig(enabled=True, remote_url="ssh://git@git.int:2222/r.git",
                   auth=SyncAuth(method="ssh"))
    rules = sync_egress_rules(s)
    assert rules[0].target == "git.int"
    assert rules[0].port == 2222


def test_egress_scp_like_url():
    s = SyncConfig(enabled=True, remote_url="git@github.com:o/r.git")
    rules = sync_egress_rules(s)
    assert rules[0].target == "github.com"
    assert rules[0].port == 22


def test_egress_disabled_returns_empty():
    s = SyncConfig()
    assert sync_egress_rules(s) == []


# ---- mount suppression ---------------------------------------------------- #

def test_active_mounts_suppresses_sync_dest_when_enabled():
    m = _m(sandbox={
        "name": "sb1",
        "mounts": [
            {"host": "./src", "dest": "/workspace"},
            {"host": "./skills", "dest": "/workspace/skills"},
        ],
        "sync": {"enabled": True, "remote_url": "https://github.com/o/r.git"},
    })
    dests = [mt.dest for mt in _active_mounts(m.sandbox)]
    # /workspace suppressed (cloned instead); /workspace/skills kept
    assert "/workspace" not in dests
    assert "/workspace/skills" in dests


def test_active_mounts_keeps_all_when_sync_disabled():
    m = _m(sandbox={
        "name": "sb1",
        "mounts": [
            {"host": "./src", "dest": "/workspace"},
            {"host": "./skills", "dest": "/workspace/skills"},
        ],
    })
    dests = [mt.dest for mt in _active_mounts(m.sandbox)]
    assert dests == ["/workspace", "/workspace/skills"]


def test_create_argv_omits_sync_dest_mount():
    m = _m(sandbox={
        "name": "sb1",
        "mounts": [{"host": "./src", "dest": "/workspace"}],
        "sync": {"enabled": True, "remote_url": "https://github.com/o/r.git"},
    })
    res = generate_sandbox(m)
    create = res.commands[0]
    vols = [create[i + 1] for i, t in enumerate(create) if t == "-v"]
    # no -v entry mounts ./src:/workspace (clone replaces it)
    assert not any(v.startswith("./src") for v in vols)


# ---- generate_sync -------------------------------------------------------- #

def test_generate_sync_empty_when_disabled():
    m = _m(sandbox={"name": "sb1"})
    res = generate_sync(m)
    assert res.commands == []
    assert res.notes == []


def test_generate_sync_emits_clone_command(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_test")
    m = _m_with_sync(auth={"method": "https", "token_env": "GH_TOKEN"})
    res = generate_sync(m)
    assert len(res.commands) == 1
    cmd = res.commands[0]
    assert cmd[:2] == ["msb", "exec"]
    assert cmd[1] != "msb" or cmd[3] == "sb1"  # sandbox name in argv
    script = " ".join(cmd)
    assert "git clone" in script
    assert "ghp_test" in script  # token injected
    assert "vm/sb1" in script    # per-VM branch


def test_generate_sync_ssh_uses_key_env(monkeypatch):
    monkeypatch.setenv("SYNC_SSH_KEY", "/home/loki/.ssh/id_ed25519")
    m = _m_with_sync(
        remote_url="ssh://git@git.int:2222/r.git",
        auth={"method": "ssh", "ssh_key_env": "SYNC_SSH_KEY"},
    )
    res = generate_sync(m)
    script = " ".join(res.commands[0])
    assert "GIT_SSH_COMMAND" in script
    assert "/home/loki/.ssh/id_ed25519" in script


# ---- plan integration ----------------------------------------------------- #

def test_plan_has_clone_commands_when_sync_enabled():
    m = _m_with_sync()
    plan = build_plan(m)
    assert len(plan.clone_commands) == 1
    assert plan.clone_commands[0][:2] == ["msb", "exec"]


def test_plan_no_clone_commands_when_sync_disabled():
    m = _m(sandbox={"name": "sb1"})
    plan = build_plan(m)
    assert plan.clone_commands == []


def test_plan_all_commands_includes_clone():
    m = _m_with_sync()
    plan = build_plan(m)
    all_cmds = plan.all_commands()
    # clone command appears somewhere in the full sequence
    assert any("git clone" in " ".join(c) for c in all_cmds)
