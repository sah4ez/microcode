"""Tests for the loki runner argv builder (pure function, no VM)."""

from __future__ import annotations

from microcode.manifest import PlatformManifest
from microcode.runners.loki_runner import loki_start_argv


def _m(**over):
    base = {"version": 1}
    base.update(over)
    return PlatformManifest.model_validate(base)


def _flag_pairs(argv, flag):
    """Return [value] after each occurrence of `flag` in argv."""
    return [argv[i + 1] for i, t in enumerate(argv) if t == flag]


def test_cline_model_forwarded_only_for_cline():
    m = _m(loki={"provider": "cline", "model": "glm-5.2"})
    argv = loki_start_argv(m, "/workspace/.microcode/artifacts/loki-config.yaml", None)
    envs = _flag_pairs(argv, "-e")
    assert "CLINE_MODEL=glm-5.2" in envs


def test_cline_model_not_forwarded_for_other_providers():
    # claude uses the loki-config model, not CLINE_MODEL
    m = _m(loki={"provider": "claude", "model": "claude-sonnet-4-5"})
    argv = loki_start_argv(m, "/workspace/cfg.yaml", None)
    envs = _flag_pairs(argv, "-e")
    assert not any(e.startswith("CLINE_MODEL=") for e in envs)


def test_cline_model_not_forwarded_when_unset():
    m = _m(loki={"provider": "cline"})  # model=None -> shim default glm-4.6
    argv = loki_start_argv(m, "/workspace/cfg.yaml", None)
    envs = _flag_pairs(argv, "-e")
    assert not any(e.startswith("CLINE_MODEL=") for e in envs)


def test_loki_start_runs_as_loki_user_with_provider_flag():
    m = _m(loki={"provider": "cline", "model": "glm-5.2"})
    argv = loki_start_argv(m, "/workspace/cfg.yaml", "prd.md")
    joined = " ".join(argv)
    assert "msb exec" in joined
    assert "--user loki" in joined
    # provider + config + prd wired into the inner bash command
    assert "--provider cline" in joined
    assert "/workspace/cfg.yaml" in joined
    assert "prd.md" in joined
