Objective: Initialize the project structure and core codebase for "OpsAgent-MCP", an open-source AI agent designed to troubleshoot CI/CD pipeline failures (specifically GitHub Actions initially) by running within the CI runner itself.

Architecture Reference: Please use the attached architecture diagram as the blueprint for this implementation.

Workflow Description:
The agent runs as a CLI tool as a final step in a failing pipeline (e.g., if: failure()). It acts as a "First Responder". It must remain in the pipeline's context to access local build logs, the source code workspace, and git state directly from the disk (without needing remote APIs for context gathering).

Tech Stack Requirements:

Language: Python (modern, 3.10+).

Orchestration: LangGraph (to manage the reasoning graph: Investigate -> Synthesize).

Intelligence: Anthropic Claude-3.5 Sonnet (via langchain-anthropic).

Tools Access: Model Context Protocol (MCP) using the fastmcp SDK. Tools must be implemented as modular MCP servers that the agent's graph consumes.

Modular Deliverables (Provide distinct files):

1. pyproject.toml (or requirements.txt): Including dependencies for langgraph, langchain-anthropic, fastmcp, click (for CLI), and python-dotenv.

2. mcp_tools/workspace_server.py (Local Context MCP Server):
Implement a tool using fastmcp to read local build logs from a specified path on the disk, and list files in the workspace. It should include basic logic to truncate large logs to fit LLM context.

3. mcp_tools/git_server.py (Git State MCP Server):
Implement a tool using fastmcp to execute local shell commands for git diff and git blame to gather code change context.

4. mcp_tools/notification_server.py (Output Dispatcher MCP Server):
Implement a tool to send JSON-formatted results to external channels. Currently, implement a stub for sending a Slack Webhook message.

5. agent.py (The Brain):
Build a LangGraph graph that initializes an Anthropic ChatModel, connects to the tools listed above via an MCP Client, and executes a loop that uses the tools to analyze the local environment based on a structured System Prompt.

6. cli.py (Entry Point):
A Click-based CLI that accepts arguments for log paths, workspace paths, and API keys, and triggers the agent.py execution.

7. System Prompt Requirement:
Please generate a concise, expert-level System Prompt that instructs the LLM on how to behave as an SRE (Site Reliability Engineer). It should prioritize checking logs for fatal errors first, then correlating them with recent code diffs to produce a Root Cause Analysis (RCA).
