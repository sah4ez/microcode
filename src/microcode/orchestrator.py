"""Orchestrator: writes artifacts and drives runners in the planned order.

Phases of ``apply``:
1. validate environment (doctor)
2. generate plan
3. write artifacts into <state_dir>/artifacts/
4. skillkit (host): install + translate skills
5. sandbox (msb): create VM, inject bootstrap.sh, run init (± snapshot)
6. loki (msb exec): start loki inside the VM

``destroy`` tears down the VM and cleans generated state.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from microcode import config, logging_utils
from microcode.errors import DependencyError, RunnerError
from microcode.manifest import PlatformManifest
from microcode.planner import Plan, build_plan
from microcode.runners import LokiRunner, SandboxRunner, SkillkitRunner, which

# Guest path where the loki config lands (must match planner.GUEST_CONFIG).
GUEST_CONFIG = "/workspace/.microcode/artifacts/loki-config.yaml"


def write_artifacts(plan: Plan, artifacts_dir: Path) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for art in plan.artifacts:
        (artifacts_dir / art.name).write_text(art.content, encoding="utf-8")
    # also stage the cline node-shim asset (used by bootstrap on arm64 VMs
    # where cline's Bun binary crashes) so the sandbox runner can copy-file it.
    import shutil
    from microcode import config as _cfg
    shim_src = Path(_cfg.__file__).parent / "assets" / "cline-node-shim.cjs"
    if shim_src.exists():
        shutil.copy2(shim_src, artifacts_dir / "cline-node-shim.cjs")


def doctor(m: PlatformManifest | None = None) -> list[str]:
    """Return a list of human-readable status lines; raise on missing tools.

    ``msb`` is always required. ``skillkit`` is only required on the host when
    skills run on the host (``skills.in_vm=false``); when ``in_vm=true`` it is
    installed *inside* the VM by bootstrap.sh and need not exist on the host.
    """
    problems: list[str] = []
    # skillkit is a host dependency only in the host-skills mode.
    skillkit_on_host = not (m and m.skills.in_vm and m.skills.enabled)
    tools = ("msb", "skillkit") if skillkit_on_host else ("msb",)
    for tool in tools:
        path = which(tool)
        if path:
            logging_utils.ok(f"{tool}: {path}")
        else:
            problems.append(tool)
            logging_utils.error(f"{tool}: NOT FOUND")
    if problems:
        raise DependencyError("missing required tools: " + ", ".join(problems))
    return problems


def apply(
    m: PlatformManifest,
    *,
    root: Path,
    dry_run: bool = False,
    prd: str | None = None,
    skip_doctor: bool = False,
) -> Plan:
    artifacts_dir = config.artifacts_dir(root, m.project.state_dir)

    if not skip_doctor and not dry_run:
        logging_utils.step("Checking dependencies")
        doctor(m)

    logging_utils.step("Building plan")
    plan = build_plan(m, prd=prd)

    logging_utils.step("Writing artifacts")
    if dry_run:
        for art in plan.artifacts:
            logging_utils.info(f"  [dim](would write)[/dim] {artifacts_dir / art.name}")
    else:
        write_artifacts(plan, artifacts_dir)
        logging_utils.ok(f"artifacts written to {artifacts_dir}")

    # Phase ordering depends on where skillkit runs:
    #   * host (skills.in_vm=false): skills first, then sandbox, then loki.
    #   * in-VM (skills.in_vm=true):  the skillkit commands are already wrapped
    #     in `msb exec`, so the VM must exist+be bootstrapped first. We run
    #     sandbox, then skillkit (inside it), then loki.
    in_vm = m.skills.in_vm and m.skills.enabled

    if not in_vm:
        # 1) skillkit on host
        logging_utils.step("Provisioning skills (skillkit on host)")
        SkillkitRunner(cwd=str(root)).run(plan.skillkit_commands, dry_run=dry_run)

    # 2) sandbox: create + init (+ snapshot)
    # If booting from scratch (msb create, not --from-snapshot which already
    # has --replace), remove a stale same-name sandbox first so create doesn't
    # fail with "already exists".
    if not dry_run and plan.sandbox_commands and plan.sandbox_commands[0][:2] == ["msb", "create"]:
        logging_utils.step(f"Removing stale sandbox '{m.sandbox.name}' (if any)")
        try:
            SkillkitRunner(cwd=str(root)).run([["msb", "rm", "-f", m.sandbox.name]])
        except RunnerError:
            pass  # tolerate "not found"
        # Fallback: msb 0.6.8 may leave a hidden sandbox dir that msb rm/list
        # don't see but msb create rejects. Purge it directly.
        import os as _os, shutil as _sh
        stale = _os.path.expanduser(f"~/.microsandbox/sandboxes/{m.sandbox.name}")
        if _os.path.exists(stale):
            _sh.rmtree(stale, ignore_errors=True)
    logging_utils.step("Provisioning sandbox (microsandbox)")
    SandboxRunner(artifacts_dir=artifacts_dir, cwd=str(root)).run(
        plan.sandbox_commands, dry_run=dry_run
    )

    # When sync (git clone) is enabled, the workspace is populated by cloning the
    # remote — replacing BOTH the bind mount (build) and the tar-seed (apply).
    # Run the clone now, then chown so loki can write. Skip the tar-seed block
    # below entirely (the sync.dest mount was already suppressed in the argv).
    if not dry_run and m.sandbox.sync.enabled and plan.clone_commands:
        logging_utils.step(f"Cloning workspace from {m.sandbox.sync.remote_url}")
        runner = SkillkitRunner(cwd=str(root))
        try:
            runner.run(plan.clone_commands)
            # chown the cloned dest so the unprivileged loki user can write
            runner.run([[
                "msb", "exec", m.sandbox.name, "--user", "root", "--",
                "chown", "-R", "loki:loki", m.sandbox.sync.dest,
            ]])
        except RunnerError as e:
            logging_utils.warn(f"git clone for sync failed: {e}")

    # When booting from a snapshot, bind mounts become named volumes (msb can't
    # bind-mount with --from-snapshot). Seed each volume from its host dir so the
    # VM sees the same files as a normal bind mount would.
    #
    # We can't use `msb cp <dir> vm:/dest` directly: it ALWAYS nests the dir
    # inside /dest (-> /dest/<dir>), regardless of a trailing slash, which would
    # put host ./src at guest /workspace/src instead of /workspace. So we tar the
    # host dir CONTENTS (-C <dir> .), copy the single tarball via `msb cp`, and
    # untar it at the guest dest — a true merge, like a bind mount.
    #
    # Named volumes also PERSIST across applies (a real bind mount always shows
    # the current host state), so we clear the guest dest first — sparing any
    # nested mount points (other volumes mounted under this path).
    #
    # SKIPPED when sync is enabled: the sync.dest mount is suppressed and the
    # workspace was cloned above. Other mounts (e.g. /workspace/skills) are still
    # seeded here.
    elif not dry_run and m.sandbox.init.snapshot.from_snapshot:
        from microcode.generators.sandbox import from_snapshot_mount_map
        from pathlib import Path as _P
        import os as _os
        import tempfile as _tf

        runner = SkillkitRunner(cwd=str(root))
        mount_dests = [mt.dest for mt in m.sandbox.mounts]
        mounts = sorted(
            from_snapshot_mount_map(m),
            key=lambda t: t[2].count("/"),  # shallow mounts first
        )
        for host_path, vol, guest_dest in mounts:
            src = _P(root) / host_path if not _P(host_path).is_absolute() else _P(host_path)
            if not src.exists():
                continue
            # (1) clear the guest dest (children only) so the volume mirrors the
            #     host dir exactly, sparing nested mount points.
            nested = [d for d in mount_dests if d != guest_dest and d.startswith(guest_dest.rstrip("/") + "/")]
            logging_utils.step(f"Clearing {guest_dest} (mirrors {src})")
            try:
                prune = "".join(f" -path {nd} -prune -o" for nd in nested)
                runner.run([[
                    "msb", "exec", m.sandbox.name, "--user", "root", "--",
                    "bash", "-c",
                    f"find {guest_dest} -mindepth 1 -maxdepth 1{prune} -exec rm -rf {{}} +",
                ]])
            except RunnerError as e:
                logging_utils.warn(f"could not clear {guest_dest}: {e}")

            # (2) tar the host dir CONTENTS, msb cp the tarball, untar at the
            #     guest dest. COPYFILE_DISABLE avoids macOS xattr noise in the
            #     guest's GNU tar; --format=ustar keeps it portable.
            logging_utils.step(f"Seeding volume {guest_dest} from {src}")
            tarball = _P(_tf.mkstemp(suffix=".tgz")[1])
            try:
                import subprocess as _sp
                _env = dict(_os.environ, COPYFILE_DISABLE="1")
                _sp.run(
                    ["tar", "czf", str(tarball), "--format=ustar", "-C", str(src), "."],
                    check=True, env=_env,
                )
                guest_tar = "/tmp/.microcode-seed.tgz"
                runner.run([["msb", "cp", str(tarball), f"{m.sandbox.name}:{guest_tar}"]])
                runner.run([[
                    "msb", "exec", m.sandbox.name, "--user", "root", "--",
                    "bash", "-c",
                    f"tar xzf {guest_tar} -C {guest_dest}/ && rm -f {guest_tar}",
                ]])
                # named volumes are owned by root; chown to the unprivileged
                # user so skillkit/loki can write (.cline/skills, .loki/, etc.)
                runner.run([[
                    "msb", "exec", m.sandbox.name, "--user", "root", "--",
                    "chown", "-R", "loki:loki", guest_dest,
                ]])
            except RunnerError as e:
                logging_utils.warn(f"could not seed {guest_dest}: {e}")
            finally:
                try:
                    tarball.unlink()
                except OSError:
                    pass

    if in_vm:
        # skillkit commands are wrapped in `msb exec`; the VM now exists.
        logging_utils.step("Provisioning skills (skillkit inside the VM)")
        SkillkitRunner(cwd=str(root)).run(plan.skillkit_commands, dry_run=dry_run)

    # 3) loki inside VM
    logging_utils.step("Starting loki-mode inside the VM")
    config_host = str(artifacts_dir / config.LOKI_CONFIG_NAME)
    LokiRunner(
        m=m, config_guest=GUEST_CONFIG, config_host=config_host,
        prd=prd, cwd=str(root),
    ).run(dry_run=dry_run)

    if dry_run:
        logging_utils.warn("dry-run: nothing was executed")
    else:
        logging_utils.ok("apply complete")
    return plan


def destroy(m: PlatformManifest, *, root: Path, dry_run: bool = False) -> None:
    name = m.sandbox.name
    state = config.state_dir(root, m.project.state_dir)

    logging_utils.step(f"Tearing down sandbox '{name}'")
    teardown = [
        ["msb", "stop", name],
        ["msb", "rm", "-f", name],
    ]
    runner = SkillkitRunner(cwd=str(root))  # reuses shell + dry-run logic
    if not dry_run:
        # msb must exist; but tolerate already-removed sandboxes
        if which("msb") is None:
            logging_utils.warn("msb not found; skipping VM teardown")
        else:
            for argv in teardown:
                try:
                    runner.run([argv])
                except RunnerError as e:
                    logging_utils.warn(f"ignored: {e}")
    else:
        runner.run(teardown, dry_run=True)

    logging_utils.step("Removing generated state")
    if dry_run:
        logging_utils.info(f"  [dim](would remove)[/dim] {state}")
    else:
        if state.exists():
            shutil.rmtree(state)
            logging_utils.ok(f"removed {state}")
        else:
            logging_utils.info(f"  nothing to remove at {state}")

    if dry_run:
        logging_utils.warn("dry-run: nothing was executed")
    else:
        logging_utils.ok("destroy complete")


def dump_plan(plan: Plan, path: Path) -> None:
    """Persist the plan as JSON for inspection / re-runs."""
    payload = {
        "artifacts": [{"name": a.name} for a in plan.artifacts],
        "skillkit_commands": plan.skillkit_commands,
        "sandbox_commands": plan.sandbox_commands,
        "clone_commands": plan.clone_commands,
        "loki_command": plan.loki_command,
        "notes": plan.notes,
        "prd": plan.prd,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
