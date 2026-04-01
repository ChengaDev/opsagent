"""
Output Dispatcher MCP Server — sends RCA results to external notification channels.
Currently implements stubs for Slack webhooks and GitHub PR comments.
Run as: python -m mcp_tools.notification_server
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastmcp import FastMCP

mcp = FastMCP("notification-server")

# Allowlist: only real Slack webhook hostnames accepted
_SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/services/"

# Strict repo format: owner/repo (alphanumerics, hyphens, underscores, dots)
_REPO_RE = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.\-]+$")

_GITHUB_COMMENT_MAX_CHARS = 65_536   # GitHub API hard limit

# Hostnames that must never be targeted by a generic webhook (SSRF guard).
# Extend at runtime via WEBHOOK_BLOCKED_HOSTS="host1,host2" environment variable.
_BLOCKED_HOSTNAMES: set[str] = {
    "localhost",
    "0.0.0.0",
    "metadata.google.internal",  # GCP metadata service
    "169.254.169.254",           # AWS/Azure instance metadata
}
_BLOCKED_HOST_PREFIXES = ("127.", "::1")

_extra = os.environ.get("WEBHOOK_BLOCKED_HOSTS", "")
if _extra:
    _BLOCKED_HOSTNAMES.update(h.strip().lower() for h in _extra.split(",") if h.strip())

_WEBHOOK_BODY_MAX_CHARS = 65_536


@mcp.tool()
def send_slack_notification(
    title: str,
    rca_summary: str,
    severity: str = "P2",
    pipeline_url: str = "",
    webhook_url: str = "",
) -> str:
    """
    Send a formatted Root Cause Analysis notification to a Slack channel
    via an Incoming Webhook.

    The webhook URL is read from the SLACK_WEBHOOK_URL environment variable if
    not provided explicitly.

    Args:
        title: Short title for the notification (e.g. "CI Failure: Build #42").
        rca_summary: The RCA text to include in the message body.
        severity: Incident severity label (P1/P2/P3/P4). Default: P2.
        pipeline_url: Optional HTTPS URL to the failed pipeline run.
        webhook_url: Slack Incoming Webhook URL. Falls back to SLACK_WEBHOOK_URL env var.

    Returns:
        JSON string with status and Slack API response.
    """
    webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")

    # Stub / unconfigured check
    if not webhook_url or webhook_url.startswith(_SLACK_WEBHOOK_PREFIX + "xxx"):
        return json.dumps({
            "status": "skipped",
            "reason": "Slack webhook URL not configured (stub mode)",
        })

    # SSRF guard — only allow real Slack webhook URLs
    if not webhook_url.startswith(_SLACK_WEBHOOK_PREFIX):
        return json.dumps({
            "status": "error",
            "reason": "Invalid webhook_url: must start with https://hooks.slack.com/services/",
        })

    # Validate optional pipeline_url
    if pipeline_url and not pipeline_url.startswith(("https://", "http://")):
        return json.dumps({
            "status": "error",
            "reason": "Invalid pipeline_url: must be an http/https URL",
        })

    # Validate severity
    severity = severity.upper()
    if severity not in ("P1", "P2", "P3", "P4"):
        severity = "P2"

    SEVERITY_COLORS  = {"P1": "#FF0000", "P2": "#FF6600", "P3": "#FFCC00", "P4": "#36A64F"}
    SEVERITY_EMOJI   = {"P1": "🚨", "P2": "🔴", "P3": "🟡", "P4": "🟢"}
    SEVERITY_LABELS  = {"P1": "Critical", "P2": "High", "P3": "Medium", "P4": "Low"}
    color = SEVERITY_COLORS[severity]
    emoji = SEVERITY_EMOJI[severity]
    sev_label = SEVERITY_LABELS[severity]

    def _md(text: str) -> str:
        """Convert **bold** markdown to Slack *bold* mrkdwn."""
        return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    def _extract(pattern: str, text: str) -> str:
        """Extract a named RCA section and stop at the next section header."""
        m = re.search(pattern, text, re.DOTALL)
        if not m:
            return ""
        raw = m.group(1).strip()
        trimmed = re.split(r"\n(?=\*\*[A-Z]|##)", raw, maxsplit=1)[0].strip()
        return _md(trimmed)

    root_cause   = _extract(r"\*\*Root Cause:\*\*\s*(.+?)(?=\n\*\*|\Z)", rca_summary)
    evidence     = _extract(r"\*\*Evidence:\*\*\s*(.+?)(?=\n\*\*|\Z)", rca_summary)
    blast_radius = _extract(r"\*\*Blast Radius:\*\*\s*(.+?)(?=\n\*\*|\Z)", rca_summary)
    fix          = _extract(r"\*\*Recommended Fix:\*\*\s*(.+?)(?=\n\*\*|\Z)", rca_summary)
    confidence   = _extract(r"\*\*Confidence:\*\*\s*(.+?)(?=\n\*\*|\Z)", rca_summary)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🔔 CI/CD Pipeline Failure: {title[:110]}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity:*\n{emoji} {sev_label}"},
                {"type": "mrkdwn", "text": f"*Detected:*\n{now_str}"},
            ],
        },
        {"type": "divider"},
    ]

    if root_cause:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":mag: *Root Cause*\n{root_cause[:500]}"},
        })

    if evidence:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":memo: *Evidence*\n{evidence[:600]}"},
        })

    if blast_radius:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":boom: *Blast Radius*\n{blast_radius[:300]}"},
        })

    if fix:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":wrench: *Recommended Fix*\n{fix[:500]}"},
        })

    if confidence:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f":bar_chart: *Confidence:* {confidence[:200]}"}],
        })

    # Fallback: if no sections parsed, show the raw summary
    if not any([root_cause, evidence, blast_radius, fix]):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": _md(rca_summary[:2000])},
        })

    payload = {"attachments": [{"color": color, "blocks": blocks}]}

    if pipeline_url:
        payload["attachments"][0]["blocks"].append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Pipeline"},
                        "url": pipeline_url,
                        "style": "danger",
                    }
                ],
            }
        )

    try:
        response = httpx.post(webhook_url, json=payload, timeout=10)
        return json.dumps({
            "status": "sent" if response.status_code == 200 else "error",
            "http_status": response.status_code,
            "response_body": response.text[:500],
        })
    except httpx.RequestError:
        # Do not include exc details — they may contain the webhook URL
        return json.dumps({"status": "error", "error": "HTTP request to Slack failed"})


@mcp.tool()
def post_github_pr_comment(
    repo: str,
    pr_number: int,
    comment_body: str,
    github_token: str = "",
) -> str:
    """
    Post a Root Cause Analysis as a comment on a GitHub Pull Request.

    Args:
        repo: Repository in "owner/repo" format (e.g. "acme/my-service").
        pr_number: Pull Request number to comment on.
        comment_body: Markdown-formatted comment text.
        github_token: GitHub personal access token or Actions token (GITHUB_TOKEN).

    Returns:
        JSON string with status and GitHub API response.
    """
    # Validate repo format to prevent URL injection
    if not _REPO_RE.match(repo):
        return json.dumps({
            "status": "error",
            "reason": "Invalid repo format: expected 'owner/repo'",
        })

    # Validate PR number
    if not isinstance(pr_number, int) or pr_number < 1:
        return json.dumps({
            "status": "error",
            "reason": "Invalid pr_number: must be a positive integer",
        })

    # Validate comment body length (GitHub API limit)
    if len(comment_body) > _GITHUB_COMMENT_MAX_CHARS:
        return json.dumps({
            "status": "error",
            "reason": f"comment_body exceeds GitHub limit of {_GITHUB_COMMENT_MAX_CHARS:,} characters",
        })

    github_token = github_token or os.environ.get("GITHUB_TOKEN", "")

    if not github_token:
        return json.dumps({
            "status": "skipped",
            "reason": "GitHub token not provided (stub mode)",
            "would_post_to": f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
            "comment_preview": comment_body[:500],
        })

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {"body": comment_body}

    try:
        response = httpx.post(url, json=body, headers=headers, timeout=15)
        data = response.json() if response.content else {}
        return json.dumps({
            "status": "posted" if response.status_code == 201 else "error",
            "http_status": response.status_code,
            "comment_url": data.get("html_url", ""),
        })
    except httpx.RequestError:
        # Do not include exc details — they may contain the Authorization header value
        return json.dumps({"status": "error", "error": "HTTP request to GitHub API failed"})


@mcp.tool()
def send_webhook_notification(
    title: str,
    rca_summary: str,
    severity: str = "P2",
    pipeline_url: str = "",
    webhook_url: str = "",
) -> str:
    """
    Send a Root Cause Analysis as a JSON payload to any HTTPS webhook endpoint.

    Useful for Discord, Microsoft Teams, PagerDuty, custom alerting systems,
    or any service that accepts an incoming webhook.

    The webhook URL is read from the WEBHOOK_URL environment variable if not
    provided explicitly.

    The payload sent is:
        {
            "event":        "opsagent.rca",
            "title":        "<title>",
            "severity":     "<P1|P2|P3|P4>",
            "rca":          "<rca_summary>",
            "pipeline_url": "<pipeline_url>",
            "timestamp":    "<ISO-8601 UTC>"
        }

    Args:
        title: Short description of the failure (e.g. "CI Failure: Build #42").
        rca_summary: The RCA text to include in the payload.
        severity: Incident severity label (P1/P2/P3/P4). Default: P2.
        pipeline_url: Optional HTTPS URL to the failed pipeline run.
        webhook_url: HTTPS URL of the webhook endpoint. Falls back to WEBHOOK_URL env var.

    Returns:
        JSON string with status and HTTP response details.
    """
    webhook_url = webhook_url or os.environ.get("WEBHOOK_URL", "")

    if not webhook_url:
        return json.dumps({"status": "skipped", "reason": "webhook_url not provided"})

    # Require HTTPS
    if not webhook_url.startswith("https://"):
        return json.dumps({
            "status": "error",
            "reason": "Invalid webhook_url: must use https://",
        })

    # SSRF guard — reject known-internal hostnames
    try:
        parsed = urlparse(webhook_url)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return json.dumps({"status": "error", "reason": "Invalid webhook_url: could not parse"})

    if hostname in _BLOCKED_HOSTNAMES or any(hostname.startswith(p) for p in _BLOCKED_HOST_PREFIXES):
        return json.dumps({
            "status": "error",
            "reason": "Invalid webhook_url: internal/loopback addresses are not allowed",
        })

    # Validate optional pipeline_url
    if pipeline_url and not pipeline_url.startswith(("https://", "http://")):
        return json.dumps({
            "status": "error",
            "reason": "Invalid pipeline_url: must be an http/https URL",
        })

    # Validate severity
    severity = severity.upper()
    if severity not in ("P1", "P2", "P3", "P4"):
        severity = "P2"

    if len(rca_summary) > _WEBHOOK_BODY_MAX_CHARS:
        rca_summary = rca_summary[:_WEBHOOK_BODY_MAX_CHARS]

    payload = {
        "event": "opsagent.rca",
        "title": title[:500],
        "severity": severity,
        "rca": rca_summary,
        "pipeline_url": pipeline_url,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        response = httpx.post(webhook_url, json=payload, timeout=10)
        return json.dumps({
            "status": "sent" if response.status_code < 300 else "error",
            "http_status": response.status_code,
            "response_body": response.text[:500],
        })
    except httpx.RequestError:
        return json.dumps({"status": "error", "error": "HTTP request to webhook failed"})


if __name__ == "__main__":
    mcp.run()
