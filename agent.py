"""
OpsAgent-MCP — The Brain.
LangGraph reasoning graph: Investigate (tool-use loop) → Synthesize (RCA output).
"""
from __future__ import annotations

import asyncio
import os
from typing import Annotated, Optional

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

load_dotenv()

# ---------------------------------------------------------------------------
# System prompt — expert SRE persona
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert Site Reliability Engineer (SRE) AI acting as a first responder \
to CI/CD pipeline failures. Your sole mission is to perform a rapid, evidence-based \
Root Cause Analysis (RCA) using the tools available to you.

## Phase 1 — Log Triage
A deterministic pre-scan of the log is already provided in the initial message — use \
it to identify the root error immediately. Do NOT call `analyze_log_issues` (already done). \
Only call `read_build_log` if you need the full raw log to confirm a specific line number \
or surrounding context that the pre-scan summary does not include.
- The FIRST (earliest) error is the most likely root cause; cascading errors are symptoms.
- Note the exact error message, file name, and line number verbatim.

## Phase 2 — Code Correlation (START HERE)
1. Call `get_recent_commits` AND `get_git_diff` in the SAME response (they are independent).
2. If the error references a specific file, also add `get_git_blame` to that same batch.
3. Look for: dependency version bumps, changed environment variable names, \
deleted files or functions still referenced elsewhere.

## Phase 3 — Workspace Inspection (only if needed)
Call `list_workspace_files` only for "file not found" or "module not found" errors \
where the log evidence alone is insufficient.

## Phase 4 — RCA Synthesis
After gathering evidence, produce a structured RCA report in this exact format:

```
## Root Cause Analysis

**Root Cause:** <One-sentence statement of the primary failure cause>

**Severity:** <P1 | P2 | P3 | P4>
- P1: Service is down / data loss / security breach
- P2: Major feature broken, no workaround
- P3: Feature degraded, workaround exists
- P4: Minor issue, cosmetic or low impact

**Evidence:**
- Log line: `<exact error line from logs>`
- Commit: `<commit hash>` — `<commit message>` by `<author>`
- Changed file: `<filename>` — `<what changed>`

**Blast Radius:** <What services, users, or pipelines are affected>

**Recommended Fix:**
1. <Specific, actionable step>
2. <Next step>
3. <Verification step>

**Confidence:** <High | Medium | Low> — <One sentence explaining confidence level>
```

Rules:
- Be precise and factual. Only assert what the evidence shows.
- Quote log lines verbatim — do not paraphrase error messages.
- Prioritize signal over noise: focus on root cause, not cascading failures.
- Batch independent tool calls into a single response whenever possible.
- If the cause is ambiguous, state confidence as Low and list alternative hypotheses.
- If a tool returns an error, try an alternative approach before giving up.
"""


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    log_path: str
    workspace_path: str
    slack_webhook_url: Optional[str]
    webhook_url: Optional[str]
    github_token: Optional[str]
    rca: Optional[str]


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def make_call_model_node(llm_with_tools):
    """Return a node that calls the LLM (with tools bound)."""
    async def call_model(state: AgentState) -> dict:
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}
    return call_model


def make_call_tools_node(tools_by_name: dict):
    """Return a node that executes all tool calls from the last AI message."""
    async def call_tools(state: AgentState) -> dict:
        last_message: AIMessage = state["messages"][-1]
        results = []
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            if tool_name not in tools_by_name:
                content = f"ERROR: Unknown tool '{tool_name}'"
            else:
                try:
                    content = str(await tools_by_name[tool_name].ainvoke(tool_args))
                except Exception as exc:
                    # Return only the exception type — not the message, which may
                    # contain file paths, tokens, or other sensitive details.
                    content = f"ERROR executing {tool_name}: {type(exc).__name__}"
            results.append(
                ToolMessage(content=content, tool_call_id=tool_call["id"])
            )
        return {"messages": results}
    return call_tools


def make_synthesize_node(llm_base):
    """Return a node that produces the final structured RCA (no tools)."""
    async def synthesize(state: AgentState) -> dict:
        synthesis_request = HumanMessage(
            content=(
                "Investigation complete. Now produce the final, structured Root Cause Analysis "
                "report using the exact format specified in the system prompt. "
                "Base it solely on the evidence you gathered above."
            )
        )
        messages = state["messages"] + [synthesis_request]
        response = await llm_base.ainvoke(messages)
        return {"messages": [response], "rca": response.content}
    return synthesize


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def route_after_model(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        return "call_tools"
    return "synthesize"


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

_PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "anthropic": ("claude-sonnet-4-6",  "claude-haiku-4-5-20251001"),
    "openai":    ("o4-mini",             "o4-mini"),
    "google":    ("gemini-2.5-pro",      "gemini-2.5-flash"),
}

_API_KEY_ENVVARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "google":    "GOOGLE_API_KEY",
}


def _build_llm(provider: str, model: str, api_key: str | None, max_tokens: int):
    """Instantiate a LangChain chat model for the given provider."""
    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "OpenAI provider requires: pip install langchain-openai"
            ) from exc
        return ChatOpenAI(model=model, max_tokens=max_tokens, api_key=api_key or None)
    elif provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "Google provider requires: pip install langchain-google-genai"
            ) from exc
        import logging
        logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)
        return ChatGoogleGenerativeAI(
            model=model, max_output_tokens=max_tokens,
            google_api_key=api_key or None,
        )
    else:
        return ChatAnthropic(model=model, max_tokens=max_tokens, api_key=api_key or None)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(llm_with_tools, llm_base, tools: list):
    tools_by_name = {t.name: t for t in tools}

    graph = StateGraph(AgentState)

    graph.add_node("call_model", make_call_model_node(llm_with_tools))
    graph.add_node("call_tools", make_call_tools_node(tools_by_name))
    graph.add_node("synthesize", make_synthesize_node(llm_base))

    graph.add_edge(START, "call_model")
    graph.add_conditional_edges(
        "call_model",
        route_after_model,
        {"call_tools": "call_tools", "synthesize": "synthesize"},
    )
    graph.add_edge("call_tools", "call_model")
    graph.add_edge("synthesize", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_agent(
    log_path: str,
    workspace_path: str,
    slack_webhook_url: str | None = None,
    webhook_url: str | None = None,
    github_token: str | None = None,
    api_key: str | None = None,
    provider: str = "anthropic",
    model: str | None = None,
    investigate_model: str | None = None,
    verbose: bool = True,
) -> str:
    """
    Run the OpsAgent-MCP investigation and return the RCA as a string.
    Connects to all three MCP tool servers via stdio transport.
    """
    # Resolve model names: use provider defaults when caller passes None
    _synth_default, _inv_default = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["anthropic"])
    model             = model             or _synth_default
    investigate_model = investigate_model or _inv_default

    # Resolve API key: explicit arg > env var for the chosen provider
    api_key = api_key or os.environ.get(_API_KEY_ENVVARS.get(provider, "ANTHROPIC_API_KEY"))

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "langchain-mcp-adapters is required. "
            "Install it with: pip install langchain-mcp-adapters"
        ) from exc

    import sys

    _quiet_env = {
        **os.environ,
        "FASTMCP_SHOW_SERVER_BANNER": "false",
        "FASTMCP_LOG_LEVEL": "WARNING",
    }

    # When bundled as a PyInstaller executable, `python -m mcp_tools.xxx` won't
    # work. Instead, the executable itself handles `--serve <name>` dispatch.
    _frozen = getattr(sys, "frozen", False)
    def _server_args(name: str) -> list[str]:
        if _frozen:
            return ["--serve", name]
        return ["-m", f"mcp_tools.{name}_server"]

    server_configs = {
        "workspace": {
            "command": sys.executable,
            "args": _server_args("workspace"),
            "transport": "stdio",
            "env": _quiet_env,
        },
        "git": {
            "command": sys.executable,
            "args": _server_args("git"),
            "transport": "stdio",
            "env": _quiet_env,
        },
        "notification": {
            "command": sys.executable,
            "args": _server_args("notification"),
            "transport": "stdio",
            "env": _quiet_env,
        },
    }

    # Pre-compute the deterministic issue pre-scan locally (fast, no LLM needed).
    # We do NOT pre-inject the full log — it would be resent with every subsequent
    # message, multiplying its token cost by the number of round trips.
    from mcp_tools.log_analyzer import summarize_issues
    pre_issues = summarize_issues(log_path)

    if verbose:
        print("[OpsAgent] Connecting to MCP tool servers…")

    mcp_client = MultiServerMCPClient(server_configs)
    tools = await mcp_client.get_tools()

    if verbose:
        print(f"[OpsAgent] Loaded {len(tools)} tools: {[t.name for t in tools]}")

    # Investigation loop uses a cheaper/faster model; synthesis uses the full model.
    llm_investigate = _build_llm(provider, investigate_model, api_key, max_tokens=4096)
    llm_synthesize  = _build_llm(provider, model,             api_key, max_tokens=4096)
    llm_with_tools  = llm_investigate.bind_tools(tools)

    graph = build_graph(llm_with_tools, llm_synthesize, tools)

    initial_user_message = (
        f"A CI/CD pipeline has failed. Please investigate and produce a Root Cause Analysis.\n\n"
        f"Build log path: {log_path}\n"
        f"Workspace path: {workspace_path}\n\n"
        f"--- DETECTED ISSUES (pre-scan) ---\n{pre_issues}\n"
    )

    initial_state: AgentState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=initial_user_message),
        ],
        "log_path": log_path,
        "workspace_path": workspace_path,
        "slack_webhook_url": slack_webhook_url,
        "webhook_url": webhook_url,
        "github_token": github_token,
        "rca": None,
    }

    if verbose:
        print("[OpsAgent] Starting investigation graph…")

    final_state = await graph.ainvoke(initial_state)

    rca = final_state.get("rca", "")
    if verbose:
        print("\n" + "=" * 70)
        print("ROOT CAUSE ANALYSIS")
        print("=" * 70)
        print(rca)
        print("=" * 70)

    # Dispatch notifications programmatically — no extra LLM call needed.
    if rca:
        import re as _re
        from pathlib import Path as _Path
        from mcp_tools.notification_server import (
            send_slack_notification,
            send_webhook_notification,
        )

        # Extract severity from the RCA text (e.g. "**Severity:** P2")
        _sev_match = _re.search(r"\*\*Severity:\*\*\s*(P[1-4])", rca)
        severity = _sev_match.group(1) if _sev_match else "P2"
        title = f"CI/CD Failure — {_Path(log_path).name}"

        if slack_webhook_url:
            result = send_slack_notification(
                title=title,
                rca_summary=rca,
                severity=severity,
            )
            if verbose:
                import json as _json
                status = _json.loads(result).get("status")
                print(f"[OpsAgent] Slack notification: {status}")

        if webhook_url:
            result = send_webhook_notification(
                title=title,
                rca_summary=rca,
                severity=severity,
            )
            if verbose:
                import json as _json
                status = _json.loads(result).get("status")
                print(f"[OpsAgent] Webhook notification: {status}")

    return rca
