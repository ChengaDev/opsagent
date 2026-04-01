# Running OpsAgent Locally

## Setup

```bash
git clone https://github.com/ChengaDev/opsagent.git
cd opsagent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all-providers]"
cp .env.example .env
# Add your API key to .env
```

## Mock mode — no API key needed

The `demo.py` script runs the **full LangGraph pipeline** with a mock LLM against realistic fixture logs. Real MCP servers start, real tools execute, only the LLM response is mocked.

```bash
python demo.py                                        # default: python import error
python demo.py --fixture oom_killed.log               # OOM killed container
python demo.py --fixture test_failure.log             # pytest failures
python demo.py --fixture k8s_crash_loop.log           # Kubernetes CrashLoopBackOff
python demo.py --fixture helm_upgrade_failed.log      # Helm upgrade timeout
python demo.py --fixture terraform_error.log          # Terraform apply error
python demo.py --fixture registry_auth_error.log      # Docker registry auth failure
python demo.py --fixture health_check_failed.log      # readiness probe failure
python demo.py --list                                 # show all available fixtures
```

## Production mode — real LLM

```bash
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
  --slack-url "$SLACK_WEBHOOK_URL" \
  --output rca_report.md

# With a generic webhook (Discord, Teams, PagerDuty)
python cli.py \
  --log-path tests/fixtures/helm_upgrade_failed.log \
  --workspace . \
  --webhook-url "$WEBHOOK_URL"
```

## Running tests

```bash
pytest tests/ -v
```

## Build executable locally

```bash
pip install -e ".[build]"
pyinstaller opsagent.spec
./dist/opsagent --log-path tests/fixtures/terraform_error.log --workspace .
```
