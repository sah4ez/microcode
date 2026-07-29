"""Tests for manifest loading, defaults, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from microcode.errors import ManifestError, ManifestNotFoundError
from microcode.manifest import PlatformManifest, load_manifest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_defaults_apply_with_empty_doc():
    m = PlatformManifest.model_validate({"version": 1})
    assert m.sandbox.image == "debian"
    assert m.sandbox.tag == "bookworm-slim"
    assert m.sandbox.cpus == 2
    assert m.loki.provider == "claude"
    assert m.skills.translate.target_agent == "claude-code"


def test_load_minimal_example():
    m = load_manifest(EXAMPLES / "minimal.yaml")
    assert m.project.name == "minimal-app"
    assert m.sandbox.init.packages.node_version == "22"
    assert "loki-mode" in m.sandbox.init.packages.npm_global


def test_load_full_stack_example():
    m = load_manifest(EXAMPLES / "full-stack.yaml")
    assert m.sandbox.init.snapshot.enabled is True
    assert m.sandbox.max_memory == 16384
    assert m.skills.install[1].provider == "github"


def test_image_ref_property():
    m = PlatformManifest.model_validate({"version": 1})
    assert m.sandbox.image_ref == "debian:bookworm-slim"
    m2 = PlatformManifest.model_validate({"version": 1, "sandbox": {"tag": ""}})
    assert m2.sandbox.image_ref == "debian"


def test_invalid_provider_rejected():
    with pytest.raises(Exception):
        PlatformManifest.model_validate({"version": 1, "loki": {"provider": "wat"}})


def test_resize_limits_enforced():
    with pytest.raises(Exception):
        PlatformManifest.model_validate(
            {"version": 1, "sandbox": {"cpus": 4, "max_cpus": 2}}
        )


def test_extra_keys_rejected():
    with pytest.raises(Exception):
        PlatformManifest.model_validate({"version": 1, "nope": true})


def test_load_missing_file():
    with pytest.raises(ManifestNotFoundError):
        load_manifest("/nonexistent/platform.yaml")


def test_load_bad_yaml(tmp_path: Path):
    p = tmp_path / "platform.yaml"
    p.write_text("version: [1, }\n")
    with pytest.raises(ManifestError):
        load_manifest(p)
