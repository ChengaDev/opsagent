# OpsAgent

**AI-powered CI failure first responder.** Drops into any failing CI pipeline, reads build logs and git history directly from the runner, and delivers a structured Root Cause Analysis to your team — so you know exactly what broke and why without ever opening the runner logs.

[![CI](https://github.com/ChengaDev/opsagent/actions/workflows/ci.yml/badge.svg)](https://github.com/ChengaDev/opsagent/actions/workflows/ci.yml)
[![Release](https://github.com/ChengaDev/opsagent/actions/workflows/release.yml/badge.svg)](https://github.com/ChengaDev/opsagent/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Why OpsAgent?](docs/why-opsagent.md) · [Examples](docs/examples.md) · [Running locally](docs/running-locally.md) · [Contributing](docs/CONTRIBUTING.md)

---

## How it works

OpsAgent runs as the **last step** of any failing CI workflow (`if: failure()`). Because it executes inside the runner it has direct, local access to everything it needs:

- Build / deployment logs on disk
- The full git workspace, recent commits, and diffs
- Source files for git blame correlation

It follows a structured 4-phase SRE investigation protocol:

```
Log Triage → Code Correlation → Workspace Inspection → RCA Synthesis
```

```
GitHub Actions failure
        │
        ▼
  ┌─────────────┐   stdio / MCP    ┌──────────────────────────────┐
  │   cli.py    │ ────────────────▶│  workspace_server            │  read logs, list files
  │  (entry pt) │                  │  git_server                  │  diff, blame, log
  └──────┬──────┘                  │  notification_server         │  Slack, GitHub PR comments
         │                         └──────────────────────────────┘
         ▼
  ┌─────────────┐   tool calls
  │  LangGraph  │ ◀──────────────── MCP tools (8 total)
  │    graph    │
  │  Investigate│   log_analyzer pre-scan (deterministic, no LLM)
  │      ↓      │
  │  Synthesize │ ─────────────────▶  RCA report
  └─────────────┘                     ├── stdout
         │                            ├── Slack Block Kit message
         ▼                            ├── GitHub PR comment
   Claude / GPT / Gemini              └── file (--output)
```

| Failure domain | Example errors detected |
|---|---|
| **Build / compile** | Missing dependency, syntax error, Docker build failure |
| **Test** | Pytest / Jest / JUnit failures, coverage threshold |
| **Dependency** | pip version conflict, npm 404, peer dep missing |
| **Container** | OOMKilled, `docker push` auth failure, manifest unknown |
| **Kubernetes** | `CrashLoopBackOff`, `ImagePullBackOff`, readiness/liveness probe failures |
| **Helm** | `UPGRADE FAILED`, `INSTALL FAILED`, condition timeout |
| **Terraform** | Apply / plan errors, state lock, IAM permission errors |
| **Infrastructure** | CloudFormation `CREATE_FAILED`, stack rollback |
| **Health checks** | Readiness probe HTTP failures, service unhealthy |
| **General** | Process exit codes, timeouts, permission denied |

---

## Installation

### Option A — Pre-built executable (recommended, no Python required)

```bash
# Linux
curl -fsSL https://github.com/ChengaDev/opsagent/releases/latest/download/opsagent-linux-x86_64 \
  -o /usr/local/bin/opsagent && chmod +x /usr/local/bin/opsagent

# macOS (Apple Silicon)
curl -fsSL https://github.com/ChengaDev/opsagent/releases/latest/download/opsagent-macos-arm64 \
  -o /usr/local/bin/opsagent && chmod +x /usr/local/bin/opsagent

# macOS (Intel)
curl -fsSL https://github.com/ChengaDev/opsagent/releases/latest/download/opsagent-macos-x86_64 \
  -o /usr/local/bin/opsagent && chmod +x /usr/local/bin/opsagent

opsagent --help
```

### Option B — pip install

```bash
pip install git+https://github.com/ChengaDev/opsagent.git
opsagent --help
```

### Option C — From source

```bash
git clone https://github.com/ChengaDev/opsagent.git
cd opsagent
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## Quick start

```yaml
- name: Run tests
  run: |
    set -o pipefail
    pytest tests/ -v 2>&1 | tee "${{ runner.temp }}/test.log"

- name: Run OpsAgent RCA
  if: failure()
  uses: ChengaDev/opsagent@v0.1.0
  with:
    log-path: ${{ runner.temp }}/test.log
    workspace: ${{ github.workspace }}
    slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

See [docs/examples.md](docs/examples.md) for Python, Node.js, Helm, Terraform, GitLab CI, Jenkins, and more.

---

## Notifications

OpsAgent supports three outbound channels, all optional.

### Slack

Set `SLACK_WEBHOOK_URL` (or `--slack-webhook`). Sends a severity-coloured Block Kit message.

### Generic webhook

Set `WEBHOOK_URL` (or `--webhook-url`). Sends a JSON payload to any HTTPS endpoint — Discord, Microsoft Teams, PagerDuty, or a custom alerting service:

```json
{
  "event":        "opsagent.rca",
  "title":        "CI Failure: Build #42",
  "severity":     "P2",
  "rca":          "## Root Cause Analysis\n...",
  "pipeline_url": "https://github.com/...",
  "timestamp":    "2024-06-01T12:34:56Z"
}
```

**SSRF protection:** only `https://` URLs accepted. Requests to `localhost`, `127.*`, `0.0.0.0`, and cloud metadata endpoints are blocked.

### GitHub PR comment

Set `GITHUB_TOKEN` (or `--github-token`). Posts the full RCA as a comment on the pull request that triggered the pipeline.

---

## RCA output format

```
## Root Cause Analysis

**Root Cause:** Helm upgrade timed out because the new pods failed their readiness probe —
                the /health endpoint returns 503 due to a missing DATABASE_URL environment variable.

**Severity:** P2

**Evidence:**
- Log line: `Error: UPGRADE FAILED: timed out waiting for the condition`
- Log line: `Readiness probe failed: HTTP probe failed with statuscode: 503`
- Commit: `a3f91bc` — "remove deprecated env vars" by jane@example.com
- Changed file: `helm/values.yaml` — DATABASE_URL reference removed

**Blast Radius:** Production deployment blocked; previous release still running.

**Recommended Fix:**
1. Add DATABASE_URL back to helm/values.yaml or the Kubernetes secret
2. Run `helm rollback my-service` to unblock production immediately
3. Re-deploy after the environment variable is restored

**Confidence:** High — probe failure timing and commit diff align precisely.
```

---

## CLI reference

```
Usage: opsagent [OPTIONS]

Options:
  --log-path PATH          Path to the CI/CD build log file  [required]
  --workspace PATH         Path to the git workspace root  [required]
  --provider TEXT          LLM provider: anthropic (default), openai, google
  --api-key TEXT           API key for the chosen provider
  --model TEXT             Model for RCA synthesis  [default: per provider]
  --investigate-model TEXT Model for the investigation tool-call loop
  --slack-webhook TEXT     Slack Incoming Webhook URL
  --webhook-url TEXT       Generic HTTPS webhook URL
  --github-token TEXT      GitHub token for posting PR comments
  --output PATH            Write RCA report to a file (in addition to stdout)
  --quiet                  Suppress progress messages
  --help                   Show this message and exit.
```

| Provider | Synthesis default | Investigation default |
|---|---|---|
| `anthropic` | `claude-sonnet-4-6` | `claude-haiku-4-5-20251001` |
| `openai` | `o4-mini` | `o4-mini` |
| `google` | `gemini-2.5-pro` | `gemini-2.5-flash` |

Environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `SLACK_WEBHOOK_URL`, `WEBHOOK_URL`, `GITHUB_TOKEN`.

---

## License

MIT
