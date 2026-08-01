"""Tests for the loki runner argv builder (pure function, no VM)."""

from __future__ import annotations

from microcode.manifest import PlatformManifest
from microcode.runners.loki_runner import _resolve_prd_guest_path, loki_start_argv


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


def test_loki_dashboard_enabled_by_default():
    m = _m(loki={"provider": "cline"})
    argv = loki_start_argv(m, "/workspace/cfg.yaml", None)
    joined = " ".join(argv)
    assert "--api" in joined
    assert "--no-dashboard" not in joined


def test_loki_dashboard_disabled():
    m = _m(loki={"provider": "cline", "dashboard": False})
    argv = loki_start_argv(m, "/workspace/cfg.yaml", None)
    joined = " ".join(argv)
    assert "--no-dashboard" in joined
    assert "--api" not in joined


# --- _resolve_prd_guest_path: host-relative -> guest-relative translation -----

def _m_with_src_mount(**over):
    base = {
        "version": 1,
        "sandbox": {
            "mounts": [
                {"host": "./src", "dest": "/workspace", "readonly": False},
            ],
        },
    }
    base.update(over)
    return PlatformManifest.model_validate(base)


def test_prd_src_prefix_stripped_to_workspace_root():
    # ./src mounts AT /workspace, so host src/PRD-001.md == guest /workspace/PRD-001.md.
    # After `cd /workspace` loki must see "PRD-001.md", not "src/PRD-001.md".
    m = _m_with_src_mount()
    assert _resolve_prd_guest_path(m, "src/PRD-001.md") == "PRD-001.md"


def test_prd_already_relative_to_mount_unchanged():
    # PRD-001.md given directly (no src/ prefix) already resolves under /workspace.
    m = _m_with_src_mount()
    assert _resolve_prd_guest_path(m, "PRD-001.md") == "PRD-001.md"


def test_prd_absolute_path_passed_through():
    m = _m_with_src_mount()
    assert _resolve_prd_guest_path(m, "/workspace/PRD-001.md") == "/workspace/PRD-001.md"


def test_prd_no_matching_mount_unchanged():
    # No mount contains the prd path -> leave it for loki as-is (no false rewrite).
    m = _m_with_src_mount()
    assert _resolve_prd_guest_path(m, "docs/PRD.md") == "docs/PRD.md"


def test_prd_nested_mount_guest_relpath():
    # A mount onto a non-/workspace guest dest -> emit a relpath from /workspace.
    m = _m(
        sandbox={
            "mounts": [{"host": "./skills", "dest": "/workspace/skills", "readonly": True}],
        }
    )
    assert _resolve_prd_guest_path(m, "skills/api.md") == "skills/api.md"


def test_loki_start_uses_resolved_prd_arg():
    # End-to-end: `--prd src/PRD-001.md` reaches the inner command as `PRD-001.md`.
    m = _m_with_src_mount(loki={"provider": "cline", "dashboard": False})
    argv = loki_start_argv(m, "/workspace/cfg.yaml", "src/PRD-001.md")
    joined = " ".join(argv)
    assert "PRD-001.md" in joined
    assert "src/PRD-001.md" not in joined
