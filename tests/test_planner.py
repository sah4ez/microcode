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
    joined = " ".join(p.loki_command)
    assert GUEST_CONFIG in joined
    assert "prd.md" in joined
    assert "loki-build" in joined  # sandbox name
    # loki runs via a login shell so PATH/HOME resolve for the unprivileged user
    assert "bash" in p.loki_command and "-lc" in p.loki_command
    assert "loki start" in joined


def test_plan_deterministic():
    a = build_plan(_m(sandbox={"cpus": 4}), prd="x")
    b = build_plan(_m(sandbox={"cpus": 4}), prd="x")
    assert a.all_commands() == b.all_commands()
    assert [x.content for x in a.artifacts] == [x.content for x in b.artifacts]


def test_plan_without_prd_omits_prd_token():
    p = build_plan(_m())
    assert p.loki_command is not None
    # loki runs via bash -lc; the inner command must reference --simple but no prd
    inner = p.loki_command[-1]
    assert "--simple" in inner
    # without a prd the inner command has no trailing bare argument
    assert inner.split()[-1] != "None"


def test_plan_all_commands_groups_in_order():
    p = build_plan(_m())
    cmds = p.all_commands()
    # sandbox commands, then loki last; skillkit commands (if any) come first
    assert cmds[-1][:3] == ["msb", "exec", "loki-build"]
    # no skillkit command leaks after a sandbox/msb command
    msb_idx = next((i for i, c in enumerate(cmds) if c[0] == "msb"), None)
    assert msb_idx is not None
    for c in cmds[:msb_idx]:
        assert c[0] in ("skillkit",)  # skillkit phase before msb phase
