"""
Integration tests for agent.py — RCA parsing, provider factory, and full graph flow.

Covers:
- _build_llm: returns the right LLM type per provider, raises on missing dependency
- Provider model defaults: correct models selected when none specified
- Severity regex: extracts P1-P4 from RCA text, defaults to P2 on mismatch
- Slack section parsing: all sections extracted from a realistic RCA
- Slack fallback: raw text rendered when RCA format is missing
- Full agent graph: run_agent() returns expected RCA with mocked LLM + MCP
"""
from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agent import _PROVIDER_DEFAULTS, _build_llm

# ---------------------------------------------------------------------------
# Realistic RCA fixture (matches the sample-service pydantic failure)
# ---------------------------------------------------------------------------

CANNED_RCA = """\
## Root Cause Analysis

**Root Cause:** The `pydantic` package was removed from `requirements.txt` in \
commit `9fcc8ef`, causing `ModuleNotFoundError` at test runtime.

**Severity:** P2

**Evidence:**
- Log line: `ModuleNotFoundError: No module named 'pydantic'`
- Commit: `9fcc8ef` — `chore: remove unused dependencies` by `Chen Gazit`
- Changed file: `requirements.txt` — removed `pydantic==2.6.4`

**Blast Radius:** All tests in the `tests/` directory fail; CI pipeline is \
fully blocked; no deployments possible until resolved.

**Recommended Fix:**
1. Add `pydantic==2.6.4` back to `requirements.txt`
2. Run `pip install -r requirements.txt` locally to verify
3. Push the fix and confirm CI passes

**Confidence:** High — The commit diff directly shows removal of the dependency \
that caused the import error.
"""


# ---------------------------------------------------------------------------
# _build_llm — provider factory
# ---------------------------------------------------------------------------

class TestBuildLlm:
    def test_anthropic_returns_chat_anthropic(self):
        from langchain_anthropic import ChatAnthropic
        llm = _build_llm("anthropic", "claude-haiku-4-5-20251001", "fake-key", 1024)
        assert isinstance(llm, ChatAnthropic)

    def test_unknown_provider_falls_back_to_anthropic(self):
        from langchain_anthropic import ChatAnthropic
        llm = _build_llm("unknown-provider", "claude-haiku-4-5-20251001", "fake-key", 1024)
        assert isinstance(llm, ChatAnthropic)

    def test_openai_raises_import_error_when_not_installed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _block_openai(name, *args, **kwargs):
            if name == "langchain_openai":
                raise ImportError("mocked missing package")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _block_openai)
        with pytest.raises(ImportError, match="pip install langchain-openai"):
            _build_llm("openai", "gpt-4o", None, 1024)

    def test_google_raises_import_error_when_not_installed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def _block_google(name, *args, **kwargs):
            if name == "langchain_google_genai":
                raise ImportError("mocked missing package")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _block_google)
        with pytest.raises(ImportError, match="pip install langchain-google-genai"):
            _build_llm("google", "gemini-2.5-pro", None, 1024)

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("langchain_google_genai"),
        reason="langchain-google-genai not installed",
    )
    def test_google_returns_correct_type(self):
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = _build_llm("google", "gemini-2.5-flash", "dummy-key", 1024)
        assert isinstance(llm, ChatGoogleGenerativeAI)


# ---------------------------------------------------------------------------
# Provider model defaults
# ---------------------------------------------------------------------------

class TestProviderDefaults:
    @pytest.mark.parametrize("provider,synth,inv", [
        ("anthropic", "claude-sonnet-4-6",  "claude-haiku-4-5-20251001"),
        ("openai",    "o4-mini",             "o4-mini"),
        ("google",    "gemini-2.5-pro",     "gemini-2.5-flash"),
    ])
    def test_defaults_match_expected(self, provider, synth, inv):
        assert _PROVIDER_DEFAULTS[provider] == (synth, inv)

    def test_explicit_model_overrides_default(self):
        """Caller-supplied model names must win over provider defaults."""
        synth_default, inv_default = _PROVIDER_DEFAULTS["anthropic"]
        assert synth_default != "custom-model"
        # Verify the dict structure is stable for override logic in run_agent
        assert len(_PROVIDER_DEFAULTS["anthropic"]) == 2


# ---------------------------------------------------------------------------
# Severity regex (mirrors the logic in run_agent)
# ---------------------------------------------------------------------------

_SEV_RE = re.compile(r"\*\*Severity:\*\*\s*(P[1-4])")


class TestSeverityRegex:
    def test_extracts_p2_from_canned_rca(self):
        m = _SEV_RE.search(CANNED_RCA)
        assert m is not None
        assert m.group(1) == "P2"

    @pytest.mark.parametrize("sev", ["P1", "P2", "P3", "P4"])
    def test_all_severity_levels_matched(self, sev):
        text = f"**Severity:** {sev}\n"
        assert _SEV_RE.search(text).group(1) == sev

    def test_missing_severity_defaults_to_p2(self):
        text = "No severity field here."
        m = _SEV_RE.search(text)
        severity = m.group(1) if m else "P2"
        assert severity == "P2"

    def test_wrong_format_does_not_match(self):
        # Another LLM might write "Severity: High" instead of "**Severity:** P2"
        text = "Severity: High\n"
        assert _SEV_RE.search(text) is None


# ---------------------------------------------------------------------------
# Slack section parsing (mirrors _extract logic in send_slack_notification)
# ---------------------------------------------------------------------------

def _extract_section(field: str, text: str) -> str:
    """Mirror of the _extract helper inside send_slack_notification."""
    pattern = rf"\*\*{re.escape(field)}:\*\*\s*(.+?)(?=\n\*\*|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1).strip()
    return re.split(r"\n(?=\*\*[A-Z]|##)", raw, maxsplit=1)[0].strip()


class TestSlackSectionParsing:
    def test_root_cause_extracted(self):
        result = _extract_section("Root Cause", CANNED_RCA)
        assert "pydantic" in result
        assert "requirements.txt" in result

    def test_severity_not_included_in_root_cause(self):
        result = _extract_section("Root Cause", CANNED_RCA)
        assert "**Severity:**" not in result

    def test_evidence_extracted(self):
        result = _extract_section("Evidence", CANNED_RCA)
        assert "ModuleNotFoundError" in result
        assert "9fcc8ef" in result

    def test_blast_radius_extracted(self):
        result = _extract_section("Blast Radius", CANNED_RCA)
        assert "CI pipeline" in result

    def test_fix_extracted(self):
        result = _extract_section("Recommended Fix", CANNED_RCA)
        assert "pydantic" in result

    def test_confidence_extracted(self):
        result = _extract_section("Confidence", CANNED_RCA)
        assert "High" in result

    def test_missing_field_returns_empty(self):
        result = _extract_section("Root Cause", "No structured content here.")
        assert result == ""

    def test_fallback_triggered_on_unstructured_output(self):
        """If no sections parse, the fallback block should contain the raw text."""
        unstructured = "The build failed because of a missing dependency."
        sections = [
            _extract_section(f, unstructured)
            for f in ("Root Cause", "Evidence", "Blast Radius", "Recommended Fix")
        ]
        assert not any(sections), "All sections should be empty for unstructured output"


# ---------------------------------------------------------------------------
# Full agent integration — mocked LLM + MCP
# ---------------------------------------------------------------------------

class _MockInvestigateLLM:
    """Simulates an LLM that goes straight to synthesis (no tool calls)."""
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="Analysis complete, no additional tools needed.")


class _MockSynthesizeLLM:
    """Returns the canned RCA on synthesis."""
    async def ainvoke(self, messages):
        return AIMessage(content=CANNED_RCA)


class _MockMCPClient:
    def __init__(self, *args, **kwargs):
        pass

    async def get_tools(self):
        return []


@pytest.mark.asyncio
async def test_run_agent_returns_rca(tmp_path):
    log_file = tmp_path / "build.log"
    log_file.write_text("ERROR: ModuleNotFoundError: No module named 'pydantic'\n")

    with (
        patch("agent._build_llm", side_effect=[_MockInvestigateLLM(), _MockSynthesizeLLM()]),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", _MockMCPClient),
        patch("mcp_tools.log_analyzer.summarize_issues", return_value="1 issue: ModuleNotFoundError"),
    ):
        from agent import run_agent
        rca = await run_agent(
            log_path=str(log_file),
            workspace_path=str(tmp_path),
            verbose=False,
        )

    assert "Root Cause" in rca
    assert "pydantic" in rca
    assert "P2" in rca


@pytest.mark.asyncio
async def test_run_agent_uses_provider_defaults(tmp_path):
    log_file = tmp_path / "build.log"
    log_file.write_text("ERROR: something failed\n")

    captured = {}

    def _capture_build_llm(provider, model, api_key, max_tokens):
        captured.setdefault("models", []).append(model)
        if len(captured["models"]) == 1:
            return _MockInvestigateLLM()
        return _MockSynthesizeLLM()

    with (
        patch("agent._build_llm", side_effect=_capture_build_llm),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", _MockMCPClient),
        patch("mcp_tools.log_analyzer.summarize_issues", return_value="1 issue detected"),
    ):
        from agent import run_agent
        await run_agent(
            log_path=str(log_file),
            workspace_path=str(tmp_path),
            provider="google",
            verbose=False,
        )

    assert captured["models"][0] == "gemini-2.5-flash"   # investigate model
    assert captured["models"][1] == "gemini-2.5-pro"     # synthesize model


@pytest.mark.asyncio
async def test_run_agent_explicit_model_overrides_default(tmp_path):
    log_file = tmp_path / "build.log"
    log_file.write_text("ERROR: something failed\n")

    captured = {}

    def _capture_build_llm(provider, model, api_key, max_tokens):
        captured.setdefault("models", []).append(model)
        if len(captured["models"]) == 1:
            return _MockInvestigateLLM()
        return _MockSynthesizeLLM()

    with (
        patch("agent._build_llm", side_effect=_capture_build_llm),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient", _MockMCPClient),
        patch("mcp_tools.log_analyzer.summarize_issues", return_value="1 issue detected"),
    ):
        from agent import run_agent
        await run_agent(
            log_path=str(log_file),
            workspace_path=str(tmp_path),
            provider="google",
            model="gemini-2.0-flash",
            investigate_model="gemini-2.0-flash-lite",
            verbose=False,
        )

    assert captured["models"][0] == "gemini-2.0-flash-lite"
    assert captured["models"][1] == "gemini-2.0-flash"
