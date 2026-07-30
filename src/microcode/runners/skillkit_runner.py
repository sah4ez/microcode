"""Runner: executes skillkit commands.

Two shapes of commands are accepted, depending on ``skills.in_vm``:

* host mode  — argv starts with ``skillkit``; we ``require("skillkit")``.
* in-VM mode — argv starts with ``msb exec`` (the skillkit call is wrapped in a
  ``bash -lc``); we ``require("msb")`` instead, since ``skillkit`` lives inside
  the VM and need not be present on the host.
"""

from __future__ import annotations

from microcode.runners.base import ShellRunner, require


class SkillkitRunner(ShellRunner):
    def run(self, commands: list[list[str]], dry_run: bool = False) -> None:
        if not dry_run:
            first = commands[0][0] if commands else "skillkit"
            require(first if first == "msb" else "skillkit")
        super().run(commands, dry_run=dry_run)
