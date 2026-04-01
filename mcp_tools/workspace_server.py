"""
Local Context MCP Server — reads CI build logs and lists workspace files.
Run as: python -m mcp_tools.workspace_server
"""
from pathlib import Path

from fastmcp import FastMCP
from mcp_tools.log_analyzer import summarize_issues

mcp = FastMCP("workspace-server")

MAX_LOG_CHARS = 50_000
HEAD_CHARS = 10_000  # keep beginning of log for context
TAIL_CHARS = 40_000  # keep end of log where errors usually live
MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB hard limit before reading

SKIP_DIRS = {".git", ".github", "node_modules", "__pycache__", ".venv", "venv", ".tox", "dist", "build"}


@mcp.tool()
def read_build_log(log_path: str) -> str:
    """
    Read a CI/CD build log file from disk.
    Large logs are truncated to fit LLM context: the first 10 000 chars
    and the last 40 000 chars are kept with a truncation notice in between.

    Args:
        log_path: Absolute or relative path to the log file.

    Returns:
        The log contents as a string, possibly truncated.
    """
    path = Path(log_path)
    if not path.exists():
        return f"ERROR: Log file not found at path: {log_path}"
    if not path.is_file():
        return f"ERROR: Path is not a file: {log_path}"

    # Guard against reading enormous files (e.g. /dev/zero)
    try:
        size = path.stat().st_size
    except OSError as exc:
        return f"ERROR: Could not stat log file: {exc}"
    if size > MAX_LOG_BYTES:
        return f"ERROR: Log file exceeds maximum allowed size of {MAX_LOG_BYTES // 1_048_576} MB"

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"ERROR: Could not read log file: {exc}"

    total = len(content)
    if total <= MAX_LOG_CHARS:
        return content

    head = content[:HEAD_CHARS]
    tail = content[-TAIL_CHARS:]
    omitted = total - HEAD_CHARS - TAIL_CHARS
    notice = (
        f"\n\n... [{omitted:,} characters omitted — log truncated to fit context] ...\n\n"
    )
    return head + notice + tail


@mcp.tool()
def list_workspace_files(workspace_path: str, pattern: str = "**/*") -> str:
    """
    List files in the CI workspace directory matching a glob pattern.
    Hidden directories (.git, .github, node_modules, __pycache__, .venv)
    are excluded by default. The pattern must not traverse outside the workspace.

    Args:
        workspace_path: Root directory of the workspace.
        pattern: Glob pattern relative to workspace_path (default: **/*).

    Returns:
        Newline-separated list of relative file paths, or an error message.
    """
    root = Path(workspace_path).resolve()
    if not root.exists():
        return f"ERROR: Workspace path not found: {workspace_path}"
    if not root.is_dir():
        return f"ERROR: Path is not a directory: {workspace_path}"

    # Reject patterns that attempt directory traversal
    if ".." in pattern:
        return "ERROR: Pattern must not contain '..'"
    if pattern.startswith("/"):
        return "ERROR: Pattern must be relative, not absolute"

    matches = []
    try:
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            # Containment guard: ensure the resolved path is inside the workspace
            try:
                resolved = p.resolve()
                if not resolved.is_relative_to(root):
                    continue
                rel = resolved.relative_to(root)
            except ValueError:
                continue
            # Skip unwanted directories
            if set(rel.parts).isdisjoint(SKIP_DIRS):
                matches.append(str(rel))
    except Exception as exc:
        return f"ERROR: Failed to list workspace files: {type(exc).__name__}"

    if not matches:
        return f"No files found matching pattern '{pattern}' in {workspace_path}"

    matches.sort()
    return "\n".join(matches)


@mcp.tool()
def analyze_log_issues(log_path: str) -> str:
    """
    Parse a CI/CD build log and return a structured plain-text summary of all
    detected issues (errors, exceptions, test failures, OOM kills, etc.) ordered
    by line number.  Use this before or alongside read_build_log to quickly
    surface the most relevant signal without sending the entire log to the LLM.

    Args:
        log_path: Absolute or relative path to the log file.

    Returns:
        Plain-text issue summary, or an error message if the file cannot be read.
    """
    path = Path(log_path)
    if not path.exists():
        return f"ERROR: Log file not found at path: {log_path}"
    if not path.is_file():
        return f"ERROR: Path is not a file: {log_path}"

    try:
        size = path.stat().st_size
    except OSError as exc:
        return f"ERROR: Could not stat log file: {exc}"
    if size > MAX_LOG_BYTES:
        return f"ERROR: Log file exceeds maximum allowed size of {MAX_LOG_BYTES // 1_048_576} MB"

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"ERROR: Could not read log file: {exc}"

    return summarize_issues(content)


if __name__ == "__main__":
    mcp.run()
