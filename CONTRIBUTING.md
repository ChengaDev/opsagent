# Contributing to OpsAgent

Contributions are welcome. Please open an issue first for anything beyond a small bug fix so we can align on direction before you invest time in a PR.

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

## Good first areas

- **New MCP servers** — Jira, PagerDuty, Datadog log fetcher, `kubectl` live pod state
- **New log patterns** — add to `_PATTERNS` in `mcp_tools/log_analyzer.py` with a matching fixture and test
- **Streaming output** — stream Claude's reasoning in real time

## Adding a new log pattern

1. Add a `(regex, IssueKind, group_index)` entry to `_PATTERNS` in `mcp_tools/log_analyzer.py`
2. Add a realistic fixture log to `tests/fixtures/`
3. Add a test class in the appropriate test file following the existing pattern
4. Run `pytest tests/ -v` to confirm
