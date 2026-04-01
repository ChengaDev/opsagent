"""
Git State MCP Server — runs git commands to gather code-change context.
Run as: python -m mcp_tools.git_server
"""
import re
import subprocess
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("git-server")

MAX_DIFF_CHARS = 40_000
MAX_COMMIT_COUNT = 100

# Safe characters for git refs (branch names, tags, SHAs, HEAD~N notation)
_REF_RE = re.compile(r"^[a-zA-Z0-9._/\-~^@{}]+$")


def _run_git(args: list[str], cwd: str) -> tuple[str, str, int]:
    """Run a git command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", "ERROR: git executable not found on PATH", 1
    except subprocess.TimeoutExpired:
        return "", "ERROR: git command timed out after 30 seconds", 1


@mcp.tool()
def get_git_diff(workspace_path: str, base_ref: str = "HEAD~1") -> str:
    """
    Return the unified diff of changes introduced in the current commit compared
    to base_ref. Useful for identifying which code changes triggered a failure.

    Args:
        workspace_path: Root of the git repository.
        base_ref: Git ref to diff against (default: HEAD~1, i.e. the last commit).

    Returns:
        Unified diff output as a string, truncated if very large.
    """
    root = Path(workspace_path)
    if not root.is_dir():
        return f"ERROR: workspace_path is not a directory: {workspace_path}"

    # Validate ref to prevent argument injection
    if not _REF_RE.match(base_ref):
        return f"ERROR: Invalid git ref format: {base_ref!r}"

    stdout, stderr, rc = _run_git(["diff", base_ref, "HEAD", "--stat"], cwd=str(root))
    if rc != 0:
        return f"ERROR running git diff --stat: {stderr.strip()}"
    stat_summary = stdout.strip()

    stdout, stderr, rc = _run_git(["diff", base_ref, "HEAD"], cwd=str(root))
    if rc != 0:
        return f"ERROR running git diff: {stderr.strip()}"

    diff_output = stdout
    if len(diff_output) > MAX_DIFF_CHARS:
        diff_output = diff_output[:MAX_DIFF_CHARS] + f"\n\n... [diff truncated at {MAX_DIFF_CHARS:,} chars] ..."

    return f"=== Diff stat ===\n{stat_summary}\n\n=== Full diff ===\n{diff_output}"


@mcp.tool()
def get_git_blame(file_path: str, start_line: int = 1, end_line: int = 50) -> str:
    """
    Run git blame on a specific line range of a file to identify who last
    modified those lines and in which commit.

    Args:
        file_path: Absolute path to the file inside the git repository.
        start_line: First line number to blame (1-indexed).
        end_line: Last line number to blame (inclusive, 1-indexed).

    Returns:
        git blame output for the specified line range.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        return f"ERROR: File not found: {file_path}"

    # Validate line numbers
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return "ERROR: start_line and end_line must be integers"
    if start_line < 1 or end_line < start_line:
        return "ERROR: Invalid line range: start_line must be >= 1 and <= end_line"

    # Determine the git root
    repo_root, stderr, rc = _run_git(
        ["rev-parse", "--show-toplevel"], cwd=str(path.parent)
    )
    if rc != 0:
        return f"ERROR: Could not determine git root: {stderr.strip()}"
    repo_root = Path(repo_root.strip()).resolve()

    # Path traversal guard: file must be inside the repo
    if not path.is_relative_to(repo_root):
        return f"ERROR: File path is outside the repository root"

    stdout, stderr, rc = _run_git(
        ["blame", f"-L{start_line},{end_line}", "--", str(path)],
        cwd=str(repo_root),
    )
    if rc != 0:
        return f"ERROR running git blame: {stderr.strip()}"

    return stdout if stdout else "No blame output returned (file may be untracked)."


@mcp.tool()
def get_recent_commits(workspace_path: str, count: int = 10) -> str:
    """
    Show the most recent git commits in a human-readable format.

    Args:
        workspace_path: Root of the git repository.
        count: Number of recent commits to return (default: 10, max: 100).

    Returns:
        Formatted git log output.
    """
    root = Path(workspace_path)
    if not root.is_dir():
        return f"ERROR: workspace_path is not a directory: {workspace_path}"

    # Validate count to prevent argument injection
    if not isinstance(count, int) or count < 1 or count > MAX_COMMIT_COUNT:
        return f"ERROR: count must be an integer between 1 and {MAX_COMMIT_COUNT}"

    stdout, stderr, rc = _run_git(
        ["log", f"-{count}", "--oneline", "--decorate", "--graph"],
        cwd=str(root),
    )
    if rc != 0:
        return f"ERROR running git log: {stderr.strip()}"

    return stdout if stdout else "No commits found."


if __name__ == "__main__":
    mcp.run()
