"""
OpsAgent-MCP CLI entry point.
Usage: python cli.py --log-path /path/to/build.log --workspace /path/to/repo
"""
import asyncio
import os
import sys

import click
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# MCP server dispatch (used by PyInstaller executable)
# ---------------------------------------------------------------------------
# When bundled as a single executable, subprocesses cannot run
# `python -m mcp_tools.xxx_server`. Instead, agent.py re-invokes the
# same executable with `--serve <name>`, and we dispatch here before
# Click even parses the rest of the arguments.

_SERVERS = {
    "workspace":    "mcp_tools.workspace_server",
    "git":          "mcp_tools.git_server",
    "notification": "mcp_tools.notification_server",
}

if len(sys.argv) == 3 and sys.argv[1] == "--serve":
    _server_name = sys.argv[2]
    if _server_name not in _SERVERS:
        sys.stderr.write(f"Unknown server: {_server_name}\n")
        sys.exit(1)
    import importlib
    _mod = importlib.import_module(_SERVERS[_server_name])
    _mod.mcp.run()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option(
    "--log-path",
    required=True,
    envvar="OPSAGENT_LOG_PATH",
    help="Path to the CI/CD build log file (e.g. /home/runner/work/build.log).",
    type=click.Path(exists=False),
)
@click.option(
    "--workspace",
    required=True,
    envvar="OPSAGENT_WORKSPACE",
    default=lambda: os.getcwd(),
    show_default="current directory",
    help="Path to the git workspace / source code root.",
    type=click.Path(exists=True, file_okay=False),
)
@click.option(
    "--api-key",
    default=None,
    help="API key for the chosen provider. Falls back to ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY env var depending on --provider.",
)
@click.option(
    "--slack-url",
    envvar="SLACK_WEBHOOK_URL",
    default=None,
    help="Slack Incoming Webhook URL for posting the RCA summary.",
)
@click.option(
    "--webhook-url",
    envvar="WEBHOOK_URL",
    default=None,
    help="Generic HTTPS webhook URL (Discord, Teams, PagerDuty, custom). Receives a JSON payload.",
)
@click.option(
    "--github-token",
    envvar="GITHUB_TOKEN",
    default=None,
    help="GitHub token for posting PR comments (optional).",
)
@click.option(
    "--provider",
    default="anthropic",
    show_default=True,
    type=click.Choice(["anthropic", "openai", "google"], case_sensitive=False),
    help="LLM provider. Defaults per provider — anthropic: claude-sonnet-4-6 / claude-haiku-4-5-20251001, openai: o4-mini / o4-mini, google: gemini-2.5-pro / gemini-2.5-flash.",
)
@click.option(
    "--model",
    default=None,
    help="Model for the final RCA synthesis step. Defaults to the provider's recommended model.",
)
@click.option(
    "--investigate-model",
    default=None,
    help="Model for the investigation tool-call loop. Defaults to the provider's fast/cheap model.",
)
@click.option(
    "--output",
    type=click.Path(writable=True),
    default=None,
    help="Optional file path to write the RCA report to (in addition to stdout).",
)
@click.option("--quiet", is_flag=True, default=False, help="Suppress progress messages.")
def main(
    log_path: str,
    workspace: str,
    api_key: str | None,
    slack_url: str | None,
    webhook_url: str | None,
    github_token: str | None,
    provider: str,
    model: str | None,
    investigate_model: str | None,
    output: str | None,
    quiet: bool,
) -> None:
    """
    OpsAgent-MCP — AI-powered CI/CD failure first responder.

    Analyzes build logs and recent git changes to produce a structured
    Root Cause Analysis (RCA), then optionally dispatches it to Slack or GitHub.

    Designed to run as the last step of a failing pipeline:

    \b
        - name: Run OpsAgent RCA
          if: failure()
          run: |
            opsagent --log-path "${{ runner.temp }}/build.log" \\
                     --workspace "${{ github.workspace }}"
          env:
            ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
            SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
    """
    from agent import _API_KEY_ENVVARS  # noqa: PLC0415
    _env_key = _API_KEY_ENVVARS.get(provider, "ANTHROPIC_API_KEY")
    resolved_api_key = api_key or os.environ.get(_env_key)

    if not resolved_api_key:
        click.echo(
            f"ERROR: API key is required for provider '{provider}'. "
            f"Set it via --api-key or the {_env_key} environment variable.",
            err=True,
        )
        sys.exit(1)

    verbose = not quiet

    if verbose:
        from banner import print_banner
        from agent import _PROVIDER_DEFAULTS  # noqa: PLC0415
        _sd, _id = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["anthropic"])
        print_banner(
            log_path=log_path,
            workspace=workspace,
            model=model or _sd,
            investigate_model=investigate_model or _id,
        )

    try:
        from agent import run_agent  # noqa: PLC0415

        rca = asyncio.run(
            run_agent(
                log_path=log_path,
                workspace_path=workspace,
                slack_webhook_url=slack_url,
                webhook_url=webhook_url,
                github_token=github_token,
                api_key=resolved_api_key,
                provider=provider,
                model=model,
                investigate_model=investigate_model,
                verbose=verbose,
            )
        )

        if output:
            with open(output, "w", encoding="utf-8") as fh:
                fh.write(rca)
            if verbose:
                click.echo(f"[OpsAgent] RCA written to: {output}")

    except KeyboardInterrupt:
        click.echo("\n[OpsAgent] Interrupted by user.", err=True)
        sys.exit(130)
    except Exception as exc:
        click.echo(f"[OpsAgent] FATAL ERROR: {exc}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
