"""Runner: executes skillkit commands on the host."""

from __future__ import annotations

from microcode.runners.base import ShellRunner, require


class SkillkitRunner(ShellRunner):
    def run(self, commands: list[list[str]], dry_run: bool = False) -> None:
        if not dry_run:
            require("skillkit")
        super().run(commands, dry_run=dry_run)
