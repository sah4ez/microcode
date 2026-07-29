"""Rich-based console output helpers."""

from __future__ import annotations

from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def info(msg: str) -> None:
    console.print(msg)


def step(title: str) -> None:
    console.print(f"\n[bold cyan]▶ {title}[/bold cyan]")


def ok(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]! {msg}[/yellow]")


def error(msg: str) -> None:
    err_console.print(f"[red]✗ {msg}[/red]")


def cmd(line: str) -> None:
    console.print(f"  [dim]$[/dim] [blue]{line}[/blue]")
