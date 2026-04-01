# Contributing to OpsAgent

Contributions are very welcome — OpsAgent is a young project and there is a lot of room to grow. Please open an issue first for anything beyond a small bug fix so we can align on direction before you invest time in a PR.

## Requirements for every PR

- **Tests are mandatory.** Every change to behaviour must include tests. PRs without tests covering the new or changed code will not be merged.
- All existing tests must continue to pass (`pytest tests/ -v`).
- Keep new dependencies minimal — ask in an issue if you're unsure.

## Getting started

```bash
git clone https://github.com/ChengaDev/opsagent.git
cd opsagent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all-providers]"
pytest tests/ -v
```

---

## Most wanted contributions

### 🔔 New notification channels

This is the highest-impact area right now. OpsAgent currently supports Slack, generic webhooks, and GitHub PR comments. We'd love to add:

| Channel | Notes |
|---|---|
| **PagerDuty** | Create an incident via the Events API v2 |
| **Microsoft Teams** | Adaptive Card payload via Incoming Webhook |
| **Discord** | Embed payload via Discord webhook |
| **Opsgenie** | Create alert via Opsgenie REST API |
| **Datadog** | Post event to Datadog Events API |
| **Email** | SMTP or SendGrid for direct email delivery |
| **Telegram** | Bot API message to a chat or channel |

Each channel lives in `mcp_tools/notification_server.py` as a new MCP tool. Follow the pattern of `send_slack_notification` — accept a webhook URL or token via env var, build the payload, send it, return a success/error string.

### 🔍 New log patterns

Add to `_PATTERNS` in `mcp_tools/log_analyzer.py` with a matching fixture log and test. Common gaps:

- Ruby / Bundler errors
- Gradle / Maven build failures
- Go module errors
- Rust / Cargo compilation errors

### 🛠️ New MCP servers

- **Jira** — create or update a ticket from the RCA
- **Datadog** — fetch recent logs or metrics for a service
- **`kubectl`** — live pod state, describe, events

---

## Adding a new notification channel

1. Add a new `@mcp.tool()` function in `mcp_tools/notification_server.py`
2. Accept the target URL / token as a parameter (callers pass it from env)
3. Build the channel-specific payload and POST it with `httpx`
4. Return a plain string: `"✓ Sent"` or `"✗ Error: <message>"`
5. Add a test in `tests/test_notification_server.py` using `respx` to mock the HTTP call
6. Document the new env var in the README CLI reference table

## Adding a new log pattern

1. Add a `(regex, IssueKind, group_index)` entry to `_PATTERNS` in `mcp_tools/log_analyzer.py`
2. Add a realistic fixture log to `tests/fixtures/`
3. Add a test class in the appropriate test file following the existing pattern
4. Run `pytest tests/ -v` to confirm
