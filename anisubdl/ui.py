"""Terminal UI helpers using Rich with automatic plain-text fallback."""

from __future__ import annotations

from typing import List, Optional, Sequence

from .models import ProviderHealth

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table

    HAS_RICH = True
except ImportError:  # pragma: no cover
    HAS_RICH = False
    Console = None  # type: ignore


console = Console() if HAS_RICH else None


def print_banner(version: str) -> None:
    if HAS_RICH and console:
        console.print(
            Panel.fit(
                f"[bold cyan]AniSubDl v{version}[/bold cyan] — Multi-Provider Anime Subtitle Downloader\n"
                "[dim]Providers: Anime Tosho NEW (animetosho.net) • TsukiHime (tsukihime.org) • Kitsunekko[/dim]",
                border_style="cyan",
            )
        )
    else:
        print(f"\n=== AniSubDl v{version} — Multi-Provider Anime Subtitle Downloader ===")


def info(msg: str) -> None:
    if HAS_RICH and console:
        console.print(f"[cyan]ℹ[/cyan] {msg}")
    else:
        print(f"[INFO] {msg}")


def success(msg: str) -> None:
    if HAS_RICH and console:
        console.print(f"[bold green]✓[/bold green] {msg}")
    else:
        print(f"[OK] {msg}")


def warn(msg: str) -> None:
    if HAS_RICH and console:
        console.print(f"[bold yellow]⚠[/bold yellow] {msg}")
    else:
        print(f"[WARN] {msg}")


def error(msg: str) -> None:
    if HAS_RICH and console:
        console.print(f"[bold red]✗[/bold red] {msg}")
    else:
        print(f"[ERROR] {msg}")


def select_from_list(
    items: Sequence[str],
    prompt: str,
    annotations: Optional[Sequence[str]] = None,
    default_index: Optional[int] = None,
) -> Optional[int]:
    """
    Display a numbered table/list and return the 0-based index chosen by the user,
    or None if cancelled / empty.
    """
    if not items:
        warn(f"No items available for: {prompt}")
        return None

    if HAS_RICH and console:
        table = Table(title=prompt, show_header=True, header_style="bold magenta", border_style="dim")
        table.add_column("#", style="cyan", justify="right", width=4)
        table.add_column("Option", style="white")
        if annotations:
            table.add_column("Info", style="green")
        for idx, item in enumerate(items, 1):
            note = annotations[idx - 1] if annotations and idx - 1 < len(annotations) else ""
            if annotations:
                table.add_row(str(idx), item, note)
            else:
                table.add_row(str(idx), item)
        console.print(table)
    else:
        print(f"\n{prompt}")
        for idx, item in enumerate(items, 1):
            note = f" ({annotations[idx - 1]})" if annotations and idx - 1 < len(annotations) and annotations[idx - 1] else ""
            print(f"  {idx}. {item}{note}")

    default_hint = f" [default: {default_index + 1}]" if default_index is not None else ""
    while True:
        try:
            raw = input(f"Select a number (1-{len(items)}, or 'q' to cancel){default_hint}: ").strip()
        except EOFError:
            return default_index

        if not raw and default_index is not None:
            return default_index
        if raw.lower() in ("q", "quit", "exit"):
            return None
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(items):
                return choice - 1
        warn(f"Please enter a valid number between 1 and {len(items)}.")


def confirm_prompt(prompt: str, default: bool = True) -> bool:
    suffix = "(Y/n)" if default else "(y/N)"
    while True:
        try:
            ans = input(f"{prompt} {suffix}: ").strip().lower()
        except EOFError:
            return default
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        warn("Please enter 'y' or 'n'.")


def render_provider_health(reports: List[ProviderHealth]) -> None:
    """Display ecosystem health table for --check-providers."""
    if HAS_RICH and console:
        table = Table(
            title="Anime Tosho Ecosystem & Subtitle Provider Status",
            header_style="bold cyan",
            border_style="cyan",
        )
        table.add_column("Service", style="bold white")
        table.add_column("URL", style="dim")
        table.add_column("Status", justify="center")
        table.add_column("Subtitles?", justify="center")
        table.add_column("CLI Flag", style="magenta")
        table.add_column("Notes")

        for r in reports:
            status_str = (
                f"[green]Online ({r.latency_ms}ms)[/green]"
                if r.online and r.latency_ms is not None
                else ("[green]Online[/green]" if r.online else "[red]Offline / Unreachable[/red]")
            )
            sub_str = "[green]Yes[/green]" if r.has_subtitles else "[yellow]No[/yellow]"
            flag_str = f"-p {r.slug}" if r.supported_in_tool else "—"
            table.add_row(r.name, r.url, status_str, sub_str, flag_str, r.notes)
        console.print(table)
    else:
        print("\n--- Provider Status ---")
        for r in reports:
            st = f"Online ({r.latency_ms}ms)" if r.online else "Offline"
            subs = "Subs: YES" if r.has_subtitles else "Subs: NO"
            flag = f"[-p {r.slug}]" if r.supported_in_tool else ""
            print(f"- {r.name} ({r.url}): {st} | {subs} {flag} — {r.notes}")


def make_progress():
    """Return a Rich Progress context manager or None when Rich is unavailable."""
    if not HAS_RICH:
        return None
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )
