# OpsAgent

**AI-powered CI failure first responder.** Drops into a failing GitHub Actions workflow, reads build logs and git history directly from the runner, and produces a structured Root Cause Analysis — no external log aggregator, no sidecar, no setup.

```
  OpsAgent  |  CI First Responder  |  LangGraph + MCP + Claude
```

---

## Is OpsAgent right for you?

OpsAgent works best for **teams** — where CI failures need to be triaged quickly, root causes aren't always obvious, and the investigation result needs to reach multiple people (Slack, webhooks).

**Good fit:**
- Multiple contributors pushing to the same repo
- CI failures that block the team and need fast triage
- Slack or on-call integration to route the RCA to the right person
- Complex dependency graphs where the root cause isn't immediately visible in the log

**Less useful for:**
- Solo projects where you read the Actions log directly
- Simple repos where failures are always obvious
- Repos with very infrequent CI failures

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
GitHub Actions failure  (CI or CD)
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
   Claude (Anthropic)                 └── file (--output)
```

### Works across all CI failure types

OpsAgent treats every CI log the same regardless of what the workflow does. Whether the failure is a broken build, a failing test suite, a missing dependency, or a Docker build error — if it produces a log file, OpsAgent can analyse it.

### Also supports CD failures

OpsAgent also handles deployment failures — Helm upgrades, Terraform applies, Kubernetes errors, and more. Point it at any log file and it will produce a structured RCA.

| Failure domain | Example errors detected |
|---|---|
| **Build / compile** | Missing dependency, syntax error, Docker build failure |
| **Test** | Pytest / Jest / JUnit failures, coverage threshold |
| **Dependency** | pip version conflict, npm 404, peer dep missing |
| **Container** | OOMKilled, `docker push` auth failure, manifest unknown |
| **Kubernetes** | `CrashLoopBackOff`, `ImagePullBackOff`, readiness/liveness probe failures, `FailedScheduling` |
| **Helm** | `UPGRADE FAILED`, `INSTALL FAILED`, condition timeout |
| **Terraform** | Apply / plan errors, state lock, IAM permission errors |
| **Infrastructure** | CloudFormation `CREATE_FAILED`, stack rollback |
| **Health checks** | Readiness probe HTTP failures, service unhealthy |
| **General** | Process exit codes, timeouts, permission denied |

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) |
| Intelligence | Anthropic (Claude), OpenAI (GPT / o-series), Google (Gemini) — provider-switchable |
| Tool protocol | [FastMCP](https://github.com/jlowin/fastmcp) + [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters) |
| CLI | [Click](https://click.palletsprojects.com/) |
| Distribution | PyInstaller single-file executable + GitHub Releases |

---

## Installation

### Option A — Pre-built executable (recommended, no Python required)

```bash
# Linux
curl -fsSL https://github.com/ChengaDev/opsagent-mcp/releases/latest/download/opsagent-linux-x86_64 \
  -o /usr/local/bin/opsagent && chmod +x /usr/local/bin/opsagent

# macOS (Apple Silicon)
curl -fsSL https://github.com/ChengaDev/opsagent-mcp/releases/latest/download/opsagent-macos-arm64 \
  -o /usr/local/bin/opsagent && chmod +x /usr/local/bin/opsagent

# macOS (Intel)
curl -fsSL https://github.com/ChengaDev/opsagent-mcp/releases/latest/download/opsagent-macos-x86_64 \
  -o /usr/local/bin/opsagent && chmod +x /usr/local/bin/opsagent

opsagent --help
```

### Option B — Install from GitHub (Python required)

```bash
pip install git+https://github.com/ChengaDev/opsagent-mcp.git
opsagent --help
```

### Option C — Clone and run from source

```bash
git clone https://github.com/ChengaDev/opsagent-mcp.git
cd opsagent-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## Running locally

### Mock mode — no API key needed

The `demo.py` script runs the **full LangGraph pipeline** with a mock LLM against realistic fixture logs. Real MCP servers start, real tools execute, only the LLM response is mocked.

```bash
python demo.py                                        # default: python import error (CI)
python demo.py --fixture oom_killed.log               # CI — OOM killed container
python demo.py --fixture test_failure.log             # CI — pytest failures
python demo.py --fixture k8s_crash_loop.log           # CD — Kubernetes CrashLoopBackOff
python demo.py --fixture helm_upgrade_failed.log      # CD — Helm upgrade timeout
python demo.py --fixture terraform_error.log          # CD — Terraform apply error
python demo.py --fixture registry_auth_error.log      # CD — Docker registry auth
python demo.py --fixture health_check_failed.log      # CD — readiness probe failure
python demo.py --list                                 # show all available fixtures
```

### Production mode — real LLM

```bash
cp .env.example .env
# add your API key to .env — ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY

# Anthropic (default)
python cli.py \
  --log-path tests/fixtures/k8s_crash_loop.log \
  --workspace .

# OpenAI
python cli.py --provider openai \
  --log-path tests/fixtures/k8s_crash_loop.log \
  --workspace .

# Google Gemini
python cli.py --provider google \
  --log-path tests/fixtures/k8s_crash_loop.log \
  --workspace .

# Custom models
python cli.py --provider anthropic \
  --model claude-opus-4-6 \
  --investigate-model claude-haiku-4-5-20251001 \
  --log-path tests/fixtures/k8s_crash_loop.log \
  --workspace .

# With Slack notification and saved report
python cli.py \
  --log-path tests/fixtures/helm_upgrade_failed.log \
  --workspace . \
  --slack-webhook "$SLACK_WEBHOOK_URL" \
  --output rca_report.md

# With a generic webhook (Discord, Teams, PagerDuty, custom endpoint)
python cli.py \
  --log-path tests/fixtures/helm_upgrade_failed.log \
  --workspace . \
  --webhook-url "$WEBHOOK_URL"
```

### Build executable locally

```bash
pip install -e ".[build]"
pyinstaller opsagent.spec
./dist/opsagent --log-path tests/fixtures/terraform_error.log --workspace .
```

---

## GitHub Actions integration

> **Tip:** Always use `set -o pipefail` before piping through `tee` — without it, the pipeline returns `tee`'s exit code (0) even when your command fails, so `if: failure()` never triggers.

### Python / pytest

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        run: |
          set -o pipefail
          pytest tests/ -v 2>&1 | tee "${{ runner.temp }}/pytest.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/pytest.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Node.js / npm

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install and build
        run: |
          npm ci
          set -o pipefail
          npm run build 2>&1 | tee "${{ runner.temp }}/build.log"

      - name: Run tests
        run: |
          set -o pipefail
          npm test 2>&1 | tee "${{ runner.temp }}/test.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Post RCA as a PR comment

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

OpsAgent posts the full RCA as a comment on the pull request that triggered the failure — no webhook configuration needed.

### Save the RCA to a file

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          output: ${{ runner.temp }}/rca.md
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Upload RCA report
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: rca-report
          path: ${{ runner.temp }}/rca.md
```

### Use a custom model

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          model: claude-opus-4-6
          investigate-model: claude-haiku-4-5-20251001
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Use a different provider

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          provider: google
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
```

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          provider: openai
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### CD pipeline (Helm deploy)

```yaml
      - name: Deploy
        run: |
          set -o pipefail
          helm upgrade --install my-service ./charts/my-service \
            --namespace production \
            --set image.tag=${{ github.sha }} \
            --wait --timeout 5m 2>&1 | tee "${{ runner.temp }}/deploy.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/deploy.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
          webhook-url: ${{ secrets.WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### CD pipeline (Terraform)

```yaml
      - name: Terraform apply
        run: |
          set -o pipefail
          terraform apply -auto-approve 2>&1 | tee "${{ runner.temp }}/tf.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/tf.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
          webhook-url: ${{ secrets.WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### GitLab CI / Jenkins / other CI systems

Any CI system with Python available can run OpsAgent directly:

```bash
pip install "git+https://github.com/ChengaDev/opsagent-mcp.git[all-providers]"
opsagent --log-path build.log --workspace .
```

**GitLab CI example:**

```yaml
rca:
  stage: .post
  when: on_failure
  script:
    - pip install "git+https://github.com/ChengaDev/opsagent-mcp.git[all-providers]"
    - opsagent --log-path build.log --workspace .
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

**Jenkins example (declarative pipeline):**

```groovy
post {
  failure {
    sh '''
      pip install "git+https://github.com/ChengaDev/opsagent-mcp.git[all-providers]"
      opsagent --log-path build.log --workspace .
    '''
  }
}
```

---

## Notifications

OpsAgent supports three outbound notification channels, all optional and independently configurable.

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

**SSRF protection:** only `https://` URLs are accepted. Requests to `localhost`, `127.*`, `0.0.0.0`, and cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`) are blocked by default.

To extend the blocklist with your own internal hosts, set `WEBHOOK_BLOCKED_HOSTS` (comma-separated):

```bash
# In .env or as an environment variable
WEBHOOK_BLOCKED_HOSTS=internal.corp.com,10.0.0.1
```

In GitHub Actions:

```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  WEBHOOK_URL: ${{ secrets.WEBHOOK_URL }}
  WEBHOOK_BLOCKED_HOSTS: "internal.corp.com,10.0.0.1"
```

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

## Log analyzer — deterministic pre-scan

Before calling the LLM, OpsAgent runs a fast regex-based scan (`log_analyzer.py`) to extract structured issues from the log. This gives Claude a head start and makes the tool useful even without an API key.

### CI issue kinds

| Kind | Detects |
|---|---|
| `missing_dependency` | `ModuleNotFoundError`, `Cannot find module` |
| `dependency_version_error` | pip version conflicts, npm 404 |
| `python_exception` | Tracebacks, `ImportError` |
| `test_failure` | Pytest `FAILED`, unittest `FAIL:`, `N failed` |
| `oom_killed` | `OOMKilled`, `out of memory`, `Killed process` |
| `docker_build_error` | Docker build / solve failures |
| `syntax_error` | Python `SyntaxError` |
| `timeout` | `timed out`, `DeadlineExceeded`, `ETIMEDOUT` |
| `permission_error` | `Permission denied`, `EACCES` |
| `process_exit_error` | Non-zero exit codes |
| `fatal_error` | `FATAL:` log lines |

### CD issue kinds

| Kind | Detects |
|---|---|
| `kubernetes_error` | `CrashLoopBackOff`, `ImagePullBackOff`, `ErrImagePull`, `FailedScheduling`, `Evicted`, deployment deadline exceeded |
| `helm_error` | `UPGRADE FAILED`, `INSTALL FAILED`, `ROLLBACK FAILED`, resource conflicts, condition timeout |
| `terraform_error` | Terraform box-format errors (`│ Error:`), `Apply failed!`, state lock |
| `registry_error` | `denied: access forbidden`, `unauthorized`, `manifest unknown` |
| `health_check_failed` | Readiness/liveness probe failures, health check endpoints, service unhealthy |
| `infra_error` | CloudFormation `CREATE_FAILED` / `UPDATE_FAILED`, stack rollback |

---

## MCP tools reference

| Server | Tool | Description |
|---|---|---|
| `workspace` | `read_build_log` | Reads a log file; smart head+tail truncation for large logs (10 MB limit) |
| `workspace` | `list_workspace_files` | Lists files in the workspace, skipping `.git`, `node_modules`, etc. |
| `workspace` | `analyze_log_issues` | Deterministic regex pre-scan — structured issue list before LLM |
| `git` | `get_git_diff` | Unified diff since a base ref (default: `HEAD~1`) |
| `git` | `get_git_blame` | Git blame for a specific line range in a file |
| `git` | `get_recent_commits` | Recent commit log with graph decoration |
| `notifications` | `send_slack_notification` | Severity-coloured Block Kit message to a Slack webhook |
| `notifications` | `send_webhook_notification` | Generic JSON payload to any HTTPS webhook (Discord, Teams, PagerDuty, custom) |
| `notifications` | `post_github_pr_comment` | Posts the RCA as a comment on a GitHub PR |

---

---

## CLI reference

```
Usage: opsagent [OPTIONS]

Options:
  --log-path PATH          Path to the CI/CD build log file  [required]
  --workspace PATH         Path to the git workspace root  [required]
  --provider TEXT          LLM provider: anthropic (default), openai, google
  --api-key TEXT           API key for the chosen provider. Falls back to
                           ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY
  --model TEXT             Model for RCA synthesis  [default: per provider]
  --investigate-model TEXT Model for the investigation tool-call loop  [default: per provider]
  --slack-webhook TEXT     Slack Incoming Webhook URL
  --webhook-url TEXT       Generic HTTPS webhook URL (Discord, Teams, PagerDuty, custom)
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

Environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `SLACK_WEBHOOK_URL`, `WEBHOOK_URL`, `GITHUB_TOKEN`, `OPSAGENT_LOG_PATH`, `OPSAGENT_WORKSPACE`.

`WEBHOOK_BLOCKED_HOSTS` — comma-separated hostnames/IPs added to the SSRF blocklist for the generic webhook tool (e.g. `WEBHOOK_BLOCKED_HOSTS=internal.corp.com,10.0.0.1`).

---

## Contributing

Contributions are welcome. Some good first areas:

- **New MCP servers** — Jira, PagerDuty, Datadog log fetcher, `kubectl` live pod state
- **New log patterns** — add to `_PATTERNS` in `log_analyzer.py` with a matching fixture and test
- **GitHub Actions step summary** — write the RCA to `$GITHUB_STEP_SUMMARY`
- **Streaming output** — stream Claude's reasoning in real time

To add a new issue pattern:

1. Add a `(regex, IssueKind, group_index)` entry to `_PATTERNS` in `mcp_tools/log_analyzer.py`
2. Add a realistic fixture log to `tests/fixtures/`
3. Add a test class in the appropriate test file following the existing pattern
4. Run `pytest tests/ -v` to confirm

---

## License

MIT
