"""Terminal scoreboard + breach report. Uses `rich` if present, else plain text."""
from __future__ import annotations

from playbook import OBJECTIVES

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    _RICH = True
    _console = Console()
except Exception:  # noqa: BLE001
    _RICH = False
    _console = None


def log(msg: str, style: str = "") -> None:
    if _RICH:
        _console.print(msg, style=style)
    else:
        print(msg)


def scoreboard(label: str, results: dict, metrics: dict) -> None:
    """results: name -> {'breached': bool, 'detail': str}."""
    if _RICH:
        t = Table(title=f"BREACH SCOREBOARD — target: {label}", expand=True)
        t.add_column("Objective", style="bold")
        t.add_column("Result", justify="center")
        t.add_column("Detail")
        for name in OBJECTIVES:
            r = results.get(name)
            if not r:
                continue
            if r["breached"]:
                t.add_row(OBJECTIVES[name][0], "[red]✗ BREACHED[/red]", r["detail"])
            else:
                t.add_row(OBJECTIVES[name][0], "[green]✓ held[/green]", r["detail"])
        _console.print(t)
        m = metrics
        _console.print(Panel.fit(
            f"requests sent: {m.get('requests', 0)}   "
            f"legit p95 latency: {m.get('p95_ms', 0)} ms   "
            f"error rate: {m.get('error_rate', 0)}%   "
            f"availability: {m.get('availability', '?')}",
            title="traffic under attack"))
    else:
        print(f"\n=== BREACH SCOREBOARD — target: {label} ===")
        for name in OBJECTIVES:
            r = results.get(name)
            if not r:
                continue
            tag = "BREACHED" if r["breached"] else "held"
            print(f"  [{tag:>8}] {OBJECTIVES[name][0]:<26} {r['detail']}")
        print(f"  traffic: requests={metrics.get('requests',0)} "
              f"p95={metrics.get('p95_ms',0)}ms err={metrics.get('error_rate',0)}% "
              f"availability={metrics.get('availability','?')}")


def headline(label: str, breached: int, total: int, llm_line: str | None) -> None:
    verdict = "FULLY COMPROMISED" if breached >= total - 1 else (
        "PARTIALLY BREACHED" if breached else "HELD THE LINE")
    color = "red" if breached >= total - 1 else ("yellow" if breached else "green")
    body = f"{breached}/{total} objectives breached on '{label}' — {verdict}"
    if llm_line:
        body += f'\n\n"{llm_line}"'
    if _RICH:
        _console.print(Panel(body, title="BREACH REPORT", border_style=color))
    else:
        print(f"\n##### BREACH REPORT: {body} #####\n")
