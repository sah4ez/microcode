"""Tests for the generators (pure manifest -> artifact functions)."""

from __future__ import annotations

import json

import yaml

from microcode.generators import (
    generate_bootstrap,
    generate_loki,
    generate_sandbox,
    generate_skills,
)
from microcode.manifest import PlatformManifest

MIN = {"version": 1, "sandbox": {"name": "loki-build"}}


def _m(**over):
    base = {"version": 1}
    base.update(over)
    return PlatformManifest.model_validate(base)


# ---- skills --------------------------------------------------------------- #

def test_skills_generates_manifest_and_install_and_translate():
    m = _m(skills={"install": [{"source": "anthropics/skills", "skills": ["x"]}]})
    res = generate_skills(m)
    names = [a.name for a in res.artifacts]
    assert ".skills" in names
    manifest = json.loads(res.artifacts[0].content)
    assert manifest["skills"][0]["source"] == "anthropics/skills"
    # install command + translate command present
    assert any(c[:2] == ["skillkit", "install"] for c in res.commands)
    assert any(c[:2] == ["skillkit", "translate"] for c in res.commands)


def test_skills_translate_targets_named_skills_with_force():
    m = _m(skills={
        "install": [{"source": "anthropics/skills", "skills": ["a", "b"]}],
        "translate": {"target_agent": "cursor", "output_dir": "out"},
    })
    res = generate_skills(m)
    trs = [c for c in res.commands if c[:2] == ["skillkit", "translate"]]
    # one translate per named skill, with --force and target/output
    assert len(trs) == 2
    for tr in trs:
        assert "--to" in tr and "cursor" in tr
        assert "--output" in tr and "out" in tr
        assert "--force" in tr
    names = {tr[2] for tr in trs}
    assert names == {"a", "b"}


def test_skills_translate_skipped_without_named_skills():
    m = _m(skills={"translate": {"target_agent": "cursor", "output_dir": "out"}})
    res = generate_skills(m)
    assert not any(c[:2] == ["skillkit", "translate"] for c in res.commands)


def test_skills_disabled_emits_nothing():
    m = _m(skills={"enabled": False, "install": [{"source": "x/y", "skills": ["z"]}]})
    res = generate_skills(m)
    assert res.artifacts == []
    assert res.commands == []


def test_skills_tap_commands_emitted():
    m = _m(skills={"registry": {"taps": ["myorg/internal"]}})
    res = generate_skills(m)
    assert ["skillkit", "tap", "add", "myorg/internal"] in res.commands


# ---- loki ----------------------------------------------------------------- #

def test_loki_emits_config_and_env():
    m = _m(loki={"provider": "codex", "max_iterations": 7})
    res = generate_loki(m)
    cfg = yaml.safe_load(res.artifacts[0].content)
    assert cfg["provider"] == "codex"
    assert cfg["max_iterations"] == 7
    env = res.artifacts[1].content
    assert "LOKI_PROVIDER=codex" in env
    assert "LOKI_MAX_ITERATIONS=7" in env


def test_loki_env_does_not_inline_secrets():
    m = _m()
    env = generate_loki(m).artifacts[1].content
    # no literal key value should appear; only a comment referencing injection
    assert "ANTHROPIC_API_KEY=sk-" not in env
    assert "injected via msb --secret" in env


def test_loki_overrides_win():
    m = _m(loki={"config_overrides": {"custom_key": 42}})
    cfg = yaml.safe_load(generate_loki(m).artifacts[0].content)
    assert cfg["custom_key"] == 42


# ---- bootstrap ------------------------------------------------------------ #

def test_bootstrap_is_bash_with_set_e_and_packages():
    m = _m(
        sandbox={"init": {"packages": {
            "apt": ["curl"], "npm_global": ["loki-mode"], "bun": True, "node_version": "22",
        }}}
    )
    bs = generate_bootstrap(m).artifacts[0].content
    assert bs.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in bs
    assert "apt-get install -y 'curl'" in bs
    assert "npm install -g 'loki-mode'" in bs
    # node: bootstrap via debian nodejs + npm tarball, then upgrade via `n`
    assert "apt-get install -y nodejs" in bs
    assert "registry.npmjs.org/npm/-/npm-10.9.0.tgz" in bs
    assert "n install 22" in bs
    # unprivileged user (provider CLIs refuse --dangerously-skip-permissions under root)
    assert "useradd -m -s /bin/bash loki" in bs
    assert "/opt/npm-global" in bs
    assert "bun.sh/install" in bs


def test_bootstrap_quotes_scary_package_names():
    m = _m(sandbox={"init": {"packages": {"npm_global": ["@skillkit/cli;rm -rf /"]}}})
    bs = generate_bootstrap(m).artifacts[0].content
    # the dangerous token must be quoted, not executed raw
    assert "@skillkit/cli;rm -rf /" not in bs.split("'")[-2] or "';'" not in bs
    assert "npm install -g '" in bs


def test_bootstrap_provider_clis():
    m = _m(loki={"provider_clis": ["claude", "aider"]})
    bs = generate_bootstrap(m).artifacts[0].content
    assert "@anthropic-ai/claude-code" in bs
    assert "aider-chat" in bs


def test_bootstrap_extra_shell_appended():
    m = _m(sandbox={"init": {"packages": {"extra_shell": "echo hello-team"}}})
    bs = generate_bootstrap(m).artifacts[0].content
    assert "echo hello-team" in bs


def test_bootstrap_snapshot_hint():
    m = _m(sandbox={"init": {"snapshot": {"enabled": True, "name": "snap-x"}}})
    bs = generate_bootstrap(m).artifacts[0].content
    assert "snap-x" in bs


# ---- sandbox -------------------------------------------------------------- #

def test_sandbox_create_has_image_resources_and_bootstrap():
    m = _m(sandbox={"image": "debian", "tag": "bookworm-slim", "cpus": 3, "memory": 1024})
    res = generate_sandbox(m)
    create = res.commands[0]
    assert create[:3] == ["msb", "create", "debian:bookworm-slim"]
    assert "--cpus" in create and "3" in create
    assert "--memory" in create
    assert "--copy-file" in create
    idx = create.index("--copy-file")
    assert create[idx + 1].endswith(":/root/bootstrap.sh")


def test_sandbox_init_executed_after_create():
    m = _m()
    res = generate_sandbox(m)
    assert len(res.commands) == 2
    init = res.commands[1]
    assert init[:3] == ["msb", "exec", "loki-build"]
    assert "bash" in init and "/root/bootstrap.sh" in init


def test_sandbox_snapshot_adds_snapshot_command():
    m = _m(sandbox={"init": {"snapshot": {"enabled": True, "name": "s1"}}})
    res = generate_sandbox(m)
    assert len(res.commands) == 3
    assert res.commands[2][:4] == ["msb", "snapshot", "create", "s1"]


def test_sandbox_secret_flag_format():
    m = _m(sandbox={"secrets": [
        {"env": "ANTHROPIC_API_KEY", "allow_hosts": ["api.anthropic.com", "x.com"]}
    ]})
    create = generate_sandbox(m).commands[0]
    idx = create.index("--secret")
    assert create[idx + 1] == "ANTHROPIC_API_KEY@api.anthropic.com,x.com"
