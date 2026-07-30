"""Pydantic models for the unified ``platform.yaml`` manifest.

The manifest is the single source of truth. It has three top-level sections
matching the three subsystems:

* ``skills``  -> skillkit  (skill provisioning + translation)
* ``loki``    -> loki-mode (agent orchestration config)
* ``sandbox`` -> microsandbox (execution environment)

Generators are pure functions over these models; runners consume the
generated artifacts. Keep this module free of I/O so it is trivially testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from microcode import config
from microcode.errors import ManifestError, ManifestNotFoundError

# --------------------------------------------------------------------------- #
# skills (skillkit)
# --------------------------------------------------------------------------- #

Provider = Literal[
    "github", "gitlab", "bitbucket", "local", "gist", "marketplace"
]

# A representative subset of the 46 skillkit agents. Stored as ``str`` at the
# edges so unknown/future agents do not break validation; use the enum for
# documented, well-known targets.
KNOWN_AGENTS = {
    "claude-code", "codex", "cursor", "gemini-cli", "opencode", "cline",
    "github-copilot", "windsurf", "devin", "aider", "amazon-q", "goose",
    "universal",
}


class SkillInstall(BaseModel):
    """One skill source to install."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., description="owner/repo, local path, gist URL, or name")
    skills: list[str] = Field(default_factory=list, description="subset; empty = all")
    agents: list[str] = Field(
        default_factory=list,
        description=(
            "target agents for this source; empty (default) = inherit "
            "skills.agents (the loki-mode provider set: claude, codex, cline, aider)"
        ),
    )
    provider: Provider | None = Field(
        default=None, description="force a provider when autodetect fails"
    )


class SkillTranslate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_agent: str = Field(
        default="claude-code",
        description="single agent format to translate every skill into",
    )
    output_dir: str = Field(default="skills", description="where SKILL.md files land")
    also_into_memory: bool = Field(
        default=True,
        description="also mirror skills into .loki/memory/skills/ for loki",
    )
    force: bool = Field(default=False, description="overwrite collisions")

    @field_validator("target_agent")
    @classmethod
    def _check_agent(cls, v: str) -> str:
        if v not in KNOWN_AGENTS:
            # do not reject — just a documented set; allow forward-compat.
            pass
        return v


class SkillRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[str] = Field(default_factory=list, description="default registries")
    taps: list[str] = Field(default_factory=list, description="custom git registries")


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="skip the entire skills provisioning phase when false",
    )
    in_vm: bool = Field(
        default=False,
        description=(
            "run skillkit inside the microsandbox VM (via msb exec) instead of "
            "on the host. When true, the VM is created+bootstrapped first, then "
            "skillkit install/translate run inside it, so skills are provisioned "
            "in the exact environment loki will use. Default false (host)."
        ),
    )
    registry: SkillRegistry = Field(default_factory=SkillRegistry)
    install: list[SkillInstall] = Field(default_factory=list)
    translate: SkillTranslate = Field(default_factory=SkillTranslate)
    agents: list[str] = Field(
        default_factory=lambda: list(LOKI_AGENTS),
        description=(
            "fixed agent set skills are provisioned/translated for — mirrors "
            "loki-mode's provider set 1:1 (claude, codex, cline, aider). Use to "
            "constrain SkillInstall.agents / translate.target_agent so skills "
            "never target a provider loki-mode cannot run. Defaults to LOKI_AGENTS."
        ),
    )


# --------------------------------------------------------------------------- #
# loki (loki-mode)
# --------------------------------------------------------------------------- #

# Authoritative loki-mode provider set. loki-mode drives exactly these four CLI
# providers (see loki-mode docs/providers.md: claude, codex, cline, aider;
# gemini was deprecated in v7.5.18). This is the single source of truth that the
# skills section mirrors so translated skills target only providers loki can run.
LokiProvider = Literal["claude", "codex", "cline", "aider"]

# The fixed agent set the skills section should provision/translate for — mirrors
# LokiProvider 1:1 so skills never target a provider loki-mode cannot run.
LOKI_AGENTS: list[str] = ["claude", "codex", "cline", "aider"]


class QualityGates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    opt_out: list[str] = Field(default_factory=list)


class LokiMemoryStorage(BaseModel):
    """External (persistent) memory storage for loki-mode.

    When enabled, loki's memory base path (``LOKI_MEMORY_BASE_PATH``) is pointed
    at a microsandbox named volume mounted into the VM. The volume persists
    across VM destroy/recreate cycles, so cross-project learnings survive.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="mount a named volume and point LOKI_MEMORY_BASE_PATH at it",
    )
    volume: str = Field(default="loki-memory", description="named volume name")
    dest: str = Field(
        default="/data/loki-memory",
        description="guest mount path = LOKI_MEMORY_BASE_PATH",
    )


class LokiMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    managed: bool = Field(default=True, description="LOKI_MANAGED_MEMORY")
    storage: LokiMemoryStorage = Field(default_factory=LokiMemoryStorage)


class LokiProofs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class LokiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LokiProvider = "claude"
    model: str | None = Field(
        default=None,
        description=(
            "model id for the active provider, e.g. 'claude-sonnet-4-5', "
            "'glm-5.2', 'gpt-5'. Written to loki-config.yaml as `model` and to "
            "the loki env as LOKI_MODEL_OVERRIDE. For provider=cline it is also "
            "forwarded into the VM as CLINE_MODEL (the node-shim reads it). "
            "None = provider default."
        ),
    )
    max_iterations: int = Field(default=20, ge=1)
    max_budget_usd: float = Field(default=10.0, ge=0)
    effort: Literal["low", "standard", "high"] = "high"
    sdk_mode: Literal["full", "minimal"] = "full"
    quality_gates: QualityGates = Field(default_factory=QualityGates)
    memory: LokiMemory = Field(default_factory=LokiMemory)
    proofs: LokiProofs = Field(default_factory=LokiProofs)
    # arbitrary extra keys written verbatim into loki-config.yaml
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    # CLI provider binaries to install in the VM via bootstrap.sh
    provider_clis: list[str] = Field(
        default_factory=lambda: ["claude"],
        description="provider CLIs to install (claude, codex, cline, aider)",
    )


# --------------------------------------------------------------------------- #
# sandbox (microsandbox)
# --------------------------------------------------------------------------- #

NetProfile = Literal["public", "private", "host", "all", "none"]
NetMode = Literal["profile", "allowlist", "denylist"]
NetAction = Literal["allow", "deny"]
NetDirection = Literal["egress", "ingress", "any"]
NetProto = Literal["any", "tcp", "udp", "icmpv4", "icmpv6"]

# Valid microsandbox rule target groups (from net_rule.rs grammar).
NET_GROUPS = {
    "public", "private", "loopback", "link-local", "meta", "multicast",
    "host", "any", "dns",
}


class NetRule(BaseModel):
    """A single allow/deny network rule. Maps 1:1 to an ``msb --net-rule`` token.

    Grammar (from microsandbox net_rule.rs):
    ``<action>[:<direction>]@<target>[:<proto>[:<ports>]]``
    """

    model_config = ConfigDict(extra="forbid")

    action: NetAction
    target: str = Field(
        ...,
        description="domain, IP, CIDR, *.suffix, or a group (public/private/host/.../any/dns)",
    )
    proto: NetProto = "any"
    port: int | str | None = Field(
        default=None,
        description="single port or 'lo-hi' range; requires proto != any to take effect",
    )
    direction: NetDirection = "egress"

    @field_validator("port")
    @classmethod
    def _check_port(cls, v):
        if v is None:
            return v
        if isinstance(v, int):
            if not 0 <= v <= 65535:
                raise ValueError("port out of range 0-65535")
            return v
        s = str(v).strip()
        if "-" in s:
            lo, _, hi = s.partition("-")
            if not (lo.isdigit() and hi.isdigit()):
                raise ValueError(f"port range must be numeric: {v!r}")
            if not (0 <= int(lo) <= int(hi) <= 65535):
                raise ValueError(f"port range out of order/range: {v!r}")
            return s
        if not s.isdigit():
            raise ValueError(f"port must be int or 'lo-hi': {v!r}")
        if not 0 <= int(s) <= 65535:
            raise ValueError("port out of range 0-65535")
        return int(s)

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("target must be non-empty")
        return v


class NetworkConfig(BaseModel):
    """Sandbox network policy.

    Three modes:

    * ``profile`` (default) — compose egress profiles via ``--net``. Backward
      compatible with the original ``profile``/``deny_domains`` fields.
    * ``allowlist`` — deny-by-default, only ``allow`` rules pass. Emits
      ``--net-default-egress deny`` + ``--net-rule allow@...``.
    * ``denylist`` — allow-by-default, ``deny`` rules block. Emits per-rule
      ``--net-rule deny@...`` (keeps the implicit ``allow@public``).
    """

    model_config = ConfigDict(extra="forbid")

    mode: NetMode = "profile"
    profile: list[NetProfile] = Field(
        default_factory=lambda: ["public"],
        description="egress profiles for mode=profile; e.g. ['public'] or ['public','host']",
    )
    # allowlist / denylist rules
    allow: list[NetRule] = Field(default_factory=list)
    deny: list[NetRule] = Field(default_factory=list)
    default_egress: Literal["allow", "deny"] = Field(
        default="deny",
        description="base egress policy for allowlist/denylist modes",
    )
    # convenience fields (map to deny rules), kept for brevity
    deny_domains: list[str] = Field(
        default_factory=list,
        description="exact domains to deny (mode-independent convenience)",
    )
    deny_domain_suffixes: list[str] = Field(
        default_factory=list,
        description="domain suffixes to deny, e.g. 'example.com' -> *.example.com",
    )

    @model_validator(mode="after")
    def _check_mode_rules(self) -> "NetworkConfig":
        if self.mode == "allowlist":
            if any(r.action != "allow" for r in self.allow):
                raise ValueError("in allowlist mode, all 'allow' rules must have action=allow")
            if self.deny:
                raise ValueError("in allowlist mode, use 'allow' rules only (deny is the default)")
        elif self.mode == "denylist":
            if any(r.action != "deny" for r in self.deny):
                raise ValueError("in denylist mode, all 'deny' rules must have action=deny")
            if self.allow:
                raise ValueError("in denylist mode, use 'deny' rules only (allow is the default)")
        return self


class InitPackages(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apt: list[str] = Field(
        # unzip is required by the bun installer; xz by some npm tarballs.
        default_factory=lambda: ["curl", "git", "ca-certificates", "python3", "python3-pip", "unzip"]
    )
    npm_global: list[str] = Field(
        default_factory=lambda: ["loki-mode", "@skillkit/cli"]
    )
    bun: bool = True
    node_version: str = "22"
    extra_shell: str = Field(default="", description="raw bash appended to bootstrap.sh")


class SnapshotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    name: str = "loki-prepared"


class InitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: InitPackages = Field(default_factory=InitPackages)
    snapshot: SnapshotConfig = Field(default_factory=SnapshotConfig)


class SecretRef(BaseModel):
    """A secret referenced by host env var name — the value never enters the VM."""

    model_config = ConfigDict(extra="forbid")

    env: str = Field(..., description="host env var name holding the real value")
    allow_hosts: list[str] = Field(..., description="hosts the secret may egress to")


class VolumeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dest: str
    kind: Literal["dir", "disk"] = "dir"
    size: str | None = None  # e.g. "10G", only for disk


class MountRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    dest: str
    readonly: bool = False


class SandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str = config.DEFAULT_IMAGE
    tag: str = config.DEFAULT_TAG
    name: str = "loki-build"
    cpus: int = Field(default=2, ge=1)
    memory: int = Field(default=2048, ge=128, description="MiB")
    max_cpus: int | None = None
    max_memory: int | None = Field(default=None, description="MiB; enables live resize")
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    init: InitConfig = Field(default_factory=InitConfig)
    secrets: list[SecretRef] = Field(default_factory=list)
    volumes: list[VolumeRef] = Field(default_factory=list)
    mounts: list[MountRef] = Field(default_factory=list)
    ports: list[str] = Field(
        default_factory=lambda: ["57374:57374"], description="host:guest"
    )
    env: dict[str, str] = Field(default_factory=dict)
    user: str = "root"

    @property
    def image_ref(self) -> str:
        return f"{self.image}:{self.tag}" if self.tag else self.image

    @model_validator(mode="after")
    def _check_resize(self) -> "SandboxConfig":
        if (self.max_cpus is not None and self.max_cpus < self.cpus) or (
            self.max_memory is not None and self.max_memory < self.memory
        ):
            raise ValueError("max_cpus/max_memory must be >= cpus/memory")
        return self


# --------------------------------------------------------------------------- #
# project + root
# --------------------------------------------------------------------------- #

class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "my-app"
    workdir: str = "/workspace"
    state_dir: str = config.DEFAULT_STATE_DIR


class PlatformManifest(BaseModel):
    """The root manifest."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    loki: LokiConfig = Field(default_factory=LokiConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #

def load_manifest(path: str | Path) -> PlatformManifest:
    """Read and validate a manifest file."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ManifestNotFoundError(f"manifest not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:  # pragma: no cover - defensive
        raise ManifestError(f"invalid YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be a mapping, got {type(raw).__name__}")
    try:
        return PlatformManifest.model_validate(raw)
    except Exception as e:
        raise ManifestError(f"invalid manifest {p}:\n{e}") from e


def find_manifest(start: str | Path | None = None) -> Path:
    """Locate platform.yaml walking up from *start*."""
    cur = Path(start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / config.DEFAULT_MANIFEST
        if candidate.exists():
            return candidate
    raise ManifestNotFoundError(
        f"no {config.DEFAULT_MANIFEST} found upward from {cur}"
    )
