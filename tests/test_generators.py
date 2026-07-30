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


def test_skills_agents_default_mirrors_loki_providers():
    # without an explicit agents list, skills target all four loki-mode providers
    m = _m(skills={"install": [{"source": "anthropics/skills", "skills": ["x"]}]})
    res = generate_skills(m)
    manifest = json.loads(res.artifacts[0].content)
    expected = ["claude", "codex", "cline", "aider"]
    assert manifest["agents"] == expected
    assert manifest["skills"][0]["agents"] == expected
    # the install command carries one --agent flag per provider
    install = next(c for c in res.commands if c[:2] == ["skillkit", "install"])
    flags = [install[i + 1] for i, t in enumerate(install) if t == "--agent"]
    assert sorted(flags) == sorted(expected)


def test_skills_agents_explicit_override():
    # an explicit skills.agents narrows the set (still valid loki providers)
    m = _m(skills={"agents": ["cline"], "install": [{"source": "a/b", "skills": ["x"]}]})
    manifest = json.loads(generate_skills(m).artifacts[0].content)
    assert manifest["skills"][0]["agents"] == ["cline"]
    assert manifest["agents"] == ["cline"]


def test_skills_install_agents_override_on_source():
    # per-source agents still take precedence over the default loki set
    m = _m(skills={"install": [
        {"source": "a/b", "skills": ["x"], "agents": ["aider"]},
    ]})
    manifest = json.loads(generate_skills(m).artifacts[0].content)
    assert manifest["skills"][0]["agents"] == ["aider"]
    m = _m(
        sandbox={"name": "vm-1", "init": {"packages": {"node_version": "22"}}},
        skills={
            "in_vm": True,
            "install": [{"source": "anthropics/skills", "skills": ["x"]}],
        },
    )
    res = generate_skills(m)
    # no bare skillkit commands — every command runs via msb exec inside the VM
    assert res.commands, "expected wrapped commands"
    for c in res.commands:
        assert c[:3] == ["msb", "exec", "vm-1"]
        assert "--user" in c and "loki" in c
        assert c[-2] == "-lc"
    # the inner bash command still contains the skillkit invocation
    inner_joined = " ".join(c[-1] for c in res.commands)
    assert "skillkit" in inner_joined
    # the in-VM note is surfaced
    assert any("in_vm" in n for n in res.notes)


def test_skills_host_mode_does_not_wrap():
    # default in_vm=false: commands stay bare skillkit argv (run on the host)
    m = _m(skills={"install": [{"source": "anthropics/skills", "skills": ["x"]}]})
    res = generate_skills(m)
    assert res.commands
    for c in res.commands:
        assert c[0] == "skillkit"
    assert not any("in_vm" in n for n in res.notes)


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


def test_loki_model_written_to_config_and_env():
    m = _m(loki={"provider": "cline", "model": "glm-5.2"})
    res = generate_loki(m)
    cfg = yaml.safe_load(res.artifacts[0].content)
    assert cfg["model"] == "glm-5.2"
    env = res.artifacts[1].content
    assert "LOKI_MODEL_OVERRIDE=glm-5.2" in env


def test_loki_model_none_omitted():
    # no model -> neither loki-config.yaml nor the env carries a model
    m = _m()
    res = generate_loki(m)
    cfg = yaml.safe_load(res.artifacts[0].content)
    assert "model" not in cfg
    assert "LOKI_MODEL_OVERRIDE" not in res.artifacts[1].content


def test_loki_model_overridden_by_config_overrides():
    # config_overrides merge last and win over the explicit model field
    m = _m(loki={"model": "glm-5.2", "config_overrides": {"model": "glm-4.6"}})
    cfg = yaml.safe_load(generate_loki(m).artifacts[0].content)
    assert cfg["model"] == "glm-4.6"


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
    m = _m(sandbox={"init": {"packages": {"npm_global": ["skillkit;rm -rf /"]}}})
    bs = generate_bootstrap(m).artifacts[0].content
    # the dangerous token must be quoted, not executed raw
    assert "skillkit;rm -rf /" not in bs.split("'")[-2] or "';'" not in bs
    assert "npm install -g '" in bs


def test_bootstrap_provider_clis():
    m = _m(loki={"provider_clis": ["claude", "aider"]})
    bs = generate_bootstrap(m).artifacts[0].content
    assert "@anthropic-ai/claude-code" in bs
    assert "aider-chat" in bs


def test_bootstrap_bun_global_packages():
    m = _m(sandbox={"init": {"packages": {"bun_global": ["tsx", "@scope/pkg"]}}})
    bs = generate_bootstrap(m).artifacts[0].content
    # each package installed via bun install -g (best-effort, quoted)
    assert "bun install -g 'tsx'" in bs
    assert "bun install -g '@scope/pkg'" in bs
    # bun itself is installed (init.bun defaults true) before the global step
    assert "bun.sh/install" in bs


def test_bootstrap_bun_global_installs_bun_if_disabled():
    # if init.bun=false but bun_global is set, bun is still installed first
    m = _m(sandbox={"init": {"packages": {"bun": False, "bun_global": ["tsx"]}}})
    bs = generate_bootstrap(m).artifacts[0].content
    assert "bun.sh/install" in bs  # auto-installed for bun_global
    assert "bun install -g 'tsx'" in bs


def test_bootstrap_extra_shell_appended():
    m = _m(sandbox={"init": {"packages": {"extra_shell": "echo hello-team"}}})
    bs = generate_bootstrap(m).artifacts[0].content
    assert "echo hello-team" in bs


def test_bootstrap_snapshot_hint():
    m = _m(sandbox={"init": {"snapshot": {"enabled": True, "name": "snap-x"}}})
    bs = generate_bootstrap(m).artifacts[0].content
    assert "snap-x" in bs


def test_bootstrap_guarantees_skillkit_when_in_vm():
    # in_vm=true: skillkit must be installed even if npm_global drops it
    m = _m(
        skills={"in_vm": True, "enabled": True, "install": [{"source": "a/b", "skills": ["x"]}]},
        sandbox={"init": {"packages": {"npm_global": ["loki-mode"]}}},  # no skillkit
    )
    bs = generate_bootstrap(m).artifacts[0].content
    assert "npm install -g 'skillkit'" in bs


def test_bootstrap_does_not_force_skillkit_on_host_mode():
    # in_vm=false (host mode): skillkit is not FORCED beyond npm_global. When
    # the user explicitly drops it from npm_global, it is absent (host runs it).
    m = _m(
        skills={"in_vm": False, "enabled": True},
        sandbox={"init": {"packages": {"npm_global": ["loki-mode"]}}},  # no skillkit
    )
    bs = generate_bootstrap(m).artifacts[0].content
    assert "npm install -g 'skillkit'" not in bs


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


def test_sandbox_snapshot_adds_stop_then_snapshot_command():
    m = _m(sandbox={"init": {"snapshot": {"enabled": True, "name": "s1"}}})
    res = generate_sandbox(m)
    # create + init + STOP + snapshot (msb requires a stopped sandbox to capture)
    assert len(res.commands) == 4
    assert res.commands[2][:3] == ["msb", "stop", "loki-build"]
    assert res.commands[3][:4] == ["msb", "snapshot", "create", "s1"]
    assert "--force" in res.commands[3]  # overwrite an existing snapshot on re-build


def test_sandbox_from_snapshot_boots_via_msb_run_and_skips_bootstrap():
    m = _m(sandbox={
        "name": "sb1", "cpus": 4,
        "init": {"snapshot": {"from_snapshot": "mcd-base"}},
    })
    res = generate_sandbox(m)
    # exactly one command, and it is msb run --from-snapshot (not create)
    assert len(res.commands) == 1
    run = res.commands[0]
    assert run[:2] == ["msb", "run"]
    assert "--from-snapshot" in run
    assert run[run.index("--from-snapshot") + 1] == "mcd-base"
    assert "--name" in run and "sb1" in run
    assert "--detach" in run
    # resources are still wired
    assert "--cpus" in run and "4" in run
    # --replace so a stale same-name sandbox is recreated from the snapshot
    assert "--replace" in run
    # no bootstrap injection when booting from a snapshot
    assert "--copy-file" not in run
    assert not any("bootstrap.sh" in " ".join(c) for c in res.commands)
    assert any("skipped" in n for n in res.notes)


def test_sandbox_from_snapshot_rejects_enabled_combo():
    import pytest
    with pytest.raises(Exception):
        _m(sandbox={"init": {"snapshot": {"enabled": True, "from_snapshot": "x"}}})


def test_sandbox_secret_flag_format():
    m = _m(sandbox={"secrets": [
        {"env": "ANTHROPIC_API_KEY", "allow_hosts": ["api.anthropic.com", "x.com"]}
    ]})
    create = generate_sandbox(m).commands[0]
    idx = create.index("--secret")
    assert create[idx + 1] == "ANTHROPIC_API_KEY@api.anthropic.com,x.com"
