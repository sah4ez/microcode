"""Tests for network rule generation (allowlist / denylist / profile modes)."""

from __future__ import annotations

import pytest

from microcode.generators.net import network_argv, rule_token, suffix_token
from microcode.manifest import NetworkConfig, NetRule


# ---- rule_token ------------------------------------------------------------ #

def test_rule_token_basic_allow_domain():
    r = NetRule(action="allow", target="api.anthropic.com")
    assert rule_token(r) == "allow@api.anthropic.com"


def test_rule_token_with_proto_and_port():
    r = NetRule(action="allow", target="api.anthropic.com", proto="tcp", port=443)
    assert rule_token(r) == "allow@api.anthropic.com:tcp:443"


def test_rule_token_port_range():
    r = NetRule(action="allow", target="example.com", proto="tcp", port="8000-8100")
    assert rule_token(r) == "allow@example.com:tcp:8000-8100"


def test_rule_token_direction_non_egress():
    r = NetRule(action="deny", target="private", direction="ingress")
    assert rule_token(r) == "deny:ingress@private"


def test_rule_token_group_target():
    r = NetRule(action="allow", target="host")
    assert rule_token(r) == "allow@host"


def test_rule_token_cidr():
    r = NetRule(action="deny", target="10.0.0.0/8")
    assert rule_token(r) == "deny@10.0.0.0/8"


def test_rule_token_port_requires_proto():
    # proto defaults to 'any'; a port without explicit proto is meaningless
    r = NetRule(action="allow", target="x.com", port=443)
    with pytest.raises(ValueError, match="explicit proto"):
        rule_token(r)


def test_netrule_rejects_bad_port():
    with pytest.raises(Exception):
        NetRule(action="allow", target="x.com", proto="tcp", port=99999)


def test_netrule_rejects_empty_target():
    with pytest.raises(Exception):
        NetRule(action="allow", target="   ")


# ---- suffix_token ---------------------------------------------------------- #

def test_suffix_token_strips_wildcard_and_dot():
    assert suffix_token("*.example.com") == "deny@suffix=example.com"
    assert suffix_token(".example.com") == "deny@suffix=example.com"
    assert suffix_token("example.com") == "deny@suffix=example.com"


def test_suffix_token_requires_two_labels():
    with pytest.raises(ValueError):
        suffix_token("com")


# ---- network_argv: profile mode ------------------------------------------- #

def test_profile_mode_emits_net_flag():
    net = NetworkConfig(mode="profile", profile=["public"])
    assert network_argv(net) == ["--net", "public"]


def test_profile_mode_composes_and_keeps_deny_domains():
    net = NetworkConfig(
        mode="profile", profile=["public", "host"],
        deny_domains=["evil.example.com"],
    )
    argv = network_argv(net)
    assert "--net" in argv and argv[argv.index("--net") + 1] == "public,host"
    assert "--net-rule" in argv
    assert "deny@evil.example.com" in argv


def test_profile_mode_deny_suffix():
    net = NetworkConfig(mode="profile", profile=["public"], deny_domain_suffixes=["ads.example.com"])
    argv = network_argv(net)
    assert "deny@suffix=ads.example.com" in argv


# ---- network_argv: allowlist mode ----------------------------------------- #

def test_allowlist_mode_is_deny_by_default_plus_allows_and_dns():
    net = NetworkConfig(
        mode="allowlist",
        allow=[
            {"action": "allow", "target": "api.anthropic.com", "proto": "tcp", "port": 443},
            {"action": "allow", "target": "host"},
        ],
    )
    argv = network_argv(net)
    assert "--net-default-egress" in argv
    assert argv[argv.index("--net-default-egress") + 1] == "deny"
    # no --net (mutually exclusive)
    assert "--net" not in argv
    rules = [argv[i + 1] for i, t in enumerate(argv) if t == "--net-rule"]
    assert "allow@api.anthropic.com:tcp:443" in rules
    assert "allow@host" in rules
    # DNS must be allowed so names resolve
    assert "allow@dns" in rules


def test_allowlist_mode_appends_explicit_denies():
    net = NetworkConfig(
        mode="allowlist",
        allow=[{"action": "allow", "target": "api.anthropic.com"}],
        deny_domains=["telemetry.example.com"],
    )
    argv = network_argv(net)
    assert "deny@telemetry.example.com" in argv


def test_allowlist_rejects_deny_rules():
    with pytest.raises(Exception):
        NetworkConfig(mode="allowlist", deny=[{"action": "deny", "target": "x.com"}])


# ---- network_argv: denylist mode ------------------------------------------ #

def test_denylist_mode_keeps_default_allow_plus_denies():
    net = NetworkConfig(
        mode="denylist",
        default_egress="allow",
        deny=[{"action": "deny", "target": "10.0.0.0/8"}],
        deny_domains=["malicious.example.com"],
    )
    argv = network_argv(net)
    assert "--net-default-egress" in argv
    assert argv[argv.index("--net-default-egress") + 1] == "allow"
    assert "deny@10.0.0.0/8" in argv
    assert "deny@malicious.example.com" in argv
    # denylist does NOT inject allow@dns (default already allows public)
    assert "allow@dns" not in argv


def test_denylist_rejects_allow_rules():
    with pytest.raises(Exception):
        NetworkConfig(mode="denylist", allow=[{"action": "allow", "target": "x.com"}])
