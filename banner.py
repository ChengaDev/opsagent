"""Shared banner for OpsAgent-MCP CLI and demo."""
import click

_WIDTH = 70

_BANNER = "  OpsAgent  ·  From red pipeline to root cause in seconds."

_TAGLINE = "  Investigating your pipeline failure. Hang tight…"


def print_banner(log_path: str, workspace: str, model: str, investigate_model: str = "") -> None:
    click.echo(click.style("─" * _WIDTH, fg="cyan"))
    click.echo(click.style(_BANNER, fg="cyan", bold=True))
    click.echo(click.style("─" * _WIDTH, fg="cyan"))
    click.echo(f"  Log       : {log_path}")
    click.echo(f"  Workspace : {workspace}")
    if investigate_model and investigate_model != model:
        click.echo(f"  Investigate: {investigate_model}")
        click.echo(f"  Synthesize : {model}")
    else:
        click.echo(f"  Model     : {model}")
    click.echo(click.style("─" * _WIDTH, fg="cyan"))
    click.echo(click.style(_TAGLINE, fg="yellow"))
    click.echo()
