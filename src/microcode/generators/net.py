"""Build microsandbox network CLI flags from ``NetworkConfig``.

Pure functions: manifest -> list of argv token-pairs. Kept separate so the
rule-token grammar (``<action>[:<direction>]@<target>[:<proto>[:<ports>]]``)
is unit-testable in isolation.

Reference grammar (microsandbox ``net_rule.rs``):
    <TOKEN>     := <action>[:<direction>]@<target>[:<proto>[:<ports>]]
    <action>    := allow | deny
    <direction> := egress | ingress | any       (default: egress)
    <target>    := any | dns | <group> | <ipv4> | [<ipv6>] | <cidr>
                 | <fqdn> | domain=<name> | suffix=<domain>
    <proto>     := any | tcp | udp | icmpv4 | icmpv6
    <ports>     := any | <port> | <lo>-<hi>

Important rules enforced here:
* Port never goes in the target slot — always ``:<proto>:<ports>``.
* A port without an explicit proto is meaningless (proto defaults to ``any``
  which carries no ports) — we require proto when a port is set.
* ``--net`` conflicts with ``--net-default*``; we emit exactly one mechanism.
"""

from __future__ import annotations

from microcode.manifest import NET_GROUPS, DnsConfig, NetworkConfig, NetRule


def rule_token(rule: NetRule) -> str:
    """Render a single NetRule into one ``--net-rule`` token body."""
    # target validation: groups / any / dns are bare; everything else as-is.
    target = rule.target
    if target not in NET_GROUPS:
        # leave domains / IPs / CIDRs / *.suffix / domain= / suffix= verbatim
        pass

    head = rule.action
    if rule.direction != "egress":
        head = f"{head}:{rule.direction}"
    token = f"{head}@{target}"

    has_port = rule.port is not None
    if has_port and rule.proto == "any":
        raise ValueError(
            f"a port requires an explicit proto (not 'any') for rule: {token}"
        )
    # only append proto/ports when meaningful
    if rule.proto != "any" or has_port:
        token += f":{rule.proto}"
        if has_port:
            token += f":{rule.port}"
    return token


def suffix_token(suffix: str) -> str:
    """Render a deny-domain-suffix as a ``deny@suffix=...`` token."""
    s = suffix.strip().lstrip("*.").lstrip(".")
    if not s or "." not in s:
        raise ValueError(
            f"deny_domain_suffixes must be >=2-label domains, got {suffix!r}"
        )
    return f"deny@suffix={s}"


def network_argv(net: NetworkConfig) -> list[str]:
    """Return the argv fragment implementing the network policy.

    Either ``--net <profiles>`` (mode=profile) or
    ``--net-default-egress <X>`` + repeated ``--net-rule`` tokens
    (mode=allowlist/denylist). The two mechanisms are mutually exclusive in msb.
    """
    argv: list[str] = []

    deny_suffix_tokens = [suffix_token(s) for s in net.deny_domain_suffixes]
    deny_domain_tokens = [f"deny@{d}" for d in net.deny_domains]

    if net.mode == "profile":
        if net.profile:
            argv += ["--net", ",".join(net.profile)]
        # convenience deny rules still apply on top of the profile
        for tok in deny_domain_tokens + deny_suffix_tokens:
            argv += ["--net-rule", tok]
        # DNS resolvers apply in all modes (msb --dns-nameserver etc.).
        argv += dns_argv(net.dns)
        return argv

    # allowlist / denylist: deny-default knob (conflicts with --net)
    argv += ["--net-default-egress", net.default_egress]

    tokens: list[str] = []
    if net.mode == "allowlist":
        tokens += [rule_token(r) for r in net.allow]
        # NOTE: microsandbox auto-provides narrow DNS resolution in allowlist
        # mode, so we do NOT emit an explicit dns rule (the `dns` CLI target is
        # rejected by msb 0.6.x and is unnecessary here).
        # black-list convenience still applies (explicit denies win by order)
        tokens += deny_domain_tokens + deny_suffix_tokens
    else:  # denylist
        tokens += deny_domain_tokens + deny_suffix_tokens
        tokens += [rule_token(r) for r in net.deny]

    for tok in tokens:
        argv += ["--net-rule", tok]

    # DNS resolvers (mode-independent; msb --dns-nameserver etc.). Use when the
    # host resolvers intermittently fail (e.g. bun.sh not resolving).
    argv += dns_argv(net.dns)
    return argv


def dns_argv(dns: DnsConfig) -> list[str]:
    """Render DNS flags: ``--dns-nameserver`` (repeatable), timeout, rebind."""
    argv: list[str] = []
    for ns in dns.nameservers:
        argv += ["--dns-nameserver", ns]
    if dns.query_timeout_ms is not None:
        argv += ["--dns-query-timeout-ms", str(dns.query_timeout_ms)]
    if dns.no_rebind_protection:
        argv += ["--no-dns-rebind-protection"]
    return argv
