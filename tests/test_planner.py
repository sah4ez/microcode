"""Tests for the planner: determinism, ordering, and guest path wiring."""

from __future__ import annotations

from microcode.manifest import PlatformManifest
from microcode.planner import GUEST_CONFIG, build_plan


def _m(**over):
    base = {"version": 1}
    base.update(over)
    return PlatformManifest.model_validate(base)


def test_plan_order_is_skill_then_sandbox_then_loki():
    p = build_plan(_m(), prd="prd.md")
    # artifacts collected from all generators
    names = {a.name for a in p.artifacts}
    assert {".skills", "loki-config.yaml", "loki.env", "bootstrap.sh"} <= names

    # loki command references the guest config path and the prd
    assert p.loki_command is not None
    assert GUEST_CONFIG in p.loki_command
    assert "prd.md" in p.loki_command
    assert "loki-build" in p.loki_command  # sandbox name


def test_plan_deterministic():
    a = build_plan(_m(sandbox={"cpus": 4}), prd="x")
    b = build_plan(_m(sandbox={"cpus": 4}), prd="x")
    assert a.all_commands() == b.all_commands()
    assert [x.content for x in a.artifacts] == [x.content for x in b.artifacts]


def test_plan_without_prd_omits_prd_token():
    p = build_plan(_m())
    assert p.loki_command is not None
    assert p.loki_command[-1] != ""  # no trailing empty prd
    # the loki command should not contain a stray prd
    assert "--simple" in p.loki_command


def test_plan_all_commands_groups_in_order():
    p = build_plan(_m())
    cmds = p.all_commands()
    # first skillkit commands, then sandbox, then loki
    assert cmds[0][:1] == ["skillkit"]
    assert cmds[-1][:3] == ["msb", "exec", "loki-build"]
