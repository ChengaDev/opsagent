"""
Log analysis utilities — deterministic pattern matching to extract structured
issue information from CI/CD build logs before handing off to the LLM.

Exposed as an MCP tool via workspace_server.py and importable directly for testing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class IssueKind(str, Enum):
    # --- CI patterns ---
    MISSING_DEPENDENCY = "missing_dependency"
    DEPENDENCY_VERSION = "dependency_version_error"
    PYTHON_EXCEPTION = "python_exception"
    TEST_FAILURE = "test_failure"
    OOM_KILLED = "oom_killed"
    PROCESS_EXIT = "process_exit_error"
    DOCKER_BUILD = "docker_build_error"
    TIMEOUT = "timeout"
    PERMISSION = "permission_error"
    SYNTAX_ERROR = "syntax_error"
    FATAL = "fatal_error"
    GENERIC_ERROR = "generic_error"
    # --- CD patterns ---
    KUBERNETES_ERROR = "kubernetes_error"      # CrashLoopBackOff, ImagePullBackOff, probe failures
    HELM_ERROR = "helm_error"                  # Helm install/upgrade failures, rollbacks
    TERRAFORM_ERROR = "terraform_error"        # Terraform plan/apply errors
    REGISTRY_ERROR = "registry_error"          # Image push/pull auth and manifest errors
    HEALTH_CHECK_FAILED = "health_check_failed" # Readiness/liveness probes, smoke tests
    INFRA_ERROR = "infra_error"                # CloudFormation, general infrastructure errors


@dataclass
class LogIssue:
    kind: IssueKind
    line_number: int          # 1-indexed line where the issue was found
    line: str                 # the raw log line
    detail: str               # extracted detail (e.g. module name, test name)
    context: list[str] = field(default_factory=list)  # surrounding lines for context


# ---------------------------------------------------------------------------
# Pattern registry — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

# Each entry: (compiled_regex, IssueKind, detail_group_index)
# detail_group_index=0 means use the full match as detail.
_PATTERNS: list[tuple[re.Pattern, IssueKind, int]] = [
    # ------------------------------------------------------------------ CD --
    # Kubernetes pod / workload errors (check before generic OOM)
    (re.compile(r"CrashLoopBackOff", re.IGNORECASE), IssueKind.KUBERNETES_ERROR, 0),
    (re.compile(r"ImagePullBackOff|ErrImagePull", re.IGNORECASE), IssueKind.KUBERNETES_ERROR, 0),
    (re.compile(r"Back-off restarting failed container", re.IGNORECASE), IssueKind.KUBERNETES_ERROR, 0),
    (re.compile(r"Readiness probe failed:\s*(.+)", re.IGNORECASE), IssueKind.HEALTH_CHECK_FAILED, 1),
    (re.compile(r"Liveness probe failed:\s*(.+)", re.IGNORECASE), IssueKind.HEALTH_CHECK_FAILED, 1),
    (re.compile(r"FailedScheduling[:\s]+(.+)", re.IGNORECASE), IssueKind.KUBERNETES_ERROR, 1),
    (re.compile(r"Evicted:\s*(.+)", re.IGNORECASE), IssueKind.KUBERNETES_ERROR, 1),
    (re.compile(r"Error from server[:\s]+(.+)", re.IGNORECASE), IssueKind.KUBERNETES_ERROR, 1),
    (re.compile(r"error: deployment .+ exceeded its progress deadline", re.IGNORECASE), IssueKind.KUBERNETES_ERROR, 0),

    # Helm deployment errors
    (re.compile(r"Error:\s+UPGRADE FAILED:\s*(.+)", re.IGNORECASE), IssueKind.HELM_ERROR, 1),
    (re.compile(r"Error:\s+INSTALL FAILED:\s*(.+)", re.IGNORECASE), IssueKind.HELM_ERROR, 1),
    (re.compile(r"Error:\s+ROLLBACK FAILED:\s*(.+)", re.IGNORECASE), IssueKind.HELM_ERROR, 1),
    (re.compile(r"rendered manifests contain a resource that already exists", re.IGNORECASE), IssueKind.HELM_ERROR, 0),
    (re.compile(r"timed out waiting for the condition", re.IGNORECASE), IssueKind.HELM_ERROR, 0),

    # Terraform errors (1.x box format and legacy)
    (re.compile(r"│\s+Error:\s+(.+)"), IssueKind.TERRAFORM_ERROR, 1),
    (re.compile(r"Error:\s+(.+)\s*\n.*on\s+\S+\.tf\s+line", re.MULTILINE), IssueKind.TERRAFORM_ERROR, 1),
    (re.compile(r"Apply failed!|Plan failed\.", re.IGNORECASE), IssueKind.TERRAFORM_ERROR, 0),
    (re.compile(r"Error acquiring the state lock", re.IGNORECASE), IssueKind.TERRAFORM_ERROR, 0),

    # Container registry errors
    (re.compile(r"denied:\s*(access forbidden|requested access to the resource is denied)", re.IGNORECASE), IssueKind.REGISTRY_ERROR, 1),
    (re.compile(r"unauthorized:\s*(authentication required|[^\n]+)", re.IGNORECASE), IssueKind.REGISTRY_ERROR, 1),
    (re.compile(r"manifest (unknown|not found)", re.IGNORECASE), IssueKind.REGISTRY_ERROR, 0),
    (re.compile(r"repository does not exist or may require .docker login.", re.IGNORECASE), IssueKind.REGISTRY_ERROR, 0),

    # Generic health check / smoke test failures
    (re.compile(r"health.?check (failed|unhealthy)", re.IGNORECASE), IssueKind.HEALTH_CHECK_FAILED, 0),
    (re.compile(r"service (is )?unhealthy", re.IGNORECASE), IssueKind.HEALTH_CHECK_FAILED, 0),

    # CloudFormation / general infrastructure
    (re.compile(r"(CREATE|UPDATE|DELETE)_FAILED[:\s]+(.+)", re.IGNORECASE), IssueKind.INFRA_ERROR, 2),
    (re.compile(r"ROLLBACK_COMPLETE|ROLLBACK_IN_PROGRESS", re.IGNORECASE), IssueKind.INFRA_ERROR, 0),
    (re.compile(r"Stack:\s*\S+\s+is in (ROLLBACK|FAILED) state", re.IGNORECASE), IssueKind.INFRA_ERROR, 0),

    # ------------------------------------------------------------------ CI --
    # OOM / container killed
    (re.compile(r"OOMKilled|out of memory|Killed\s+process|oom-kill-container", re.IGNORECASE), IssueKind.OOM_KILLED, 0),

    # Timeout — negative lookbehind for -- to avoid matching CLI flags like --timeout=300s
    (re.compile(r"(?<!--)timed?\s*out|DeadlineExceeded|ETIMEDOUT|connection timed out", re.IGNORECASE), IssueKind.TIMEOUT, 0),

    # Missing Python/Node module
    (re.compile(r"ModuleNotFoundError:\s*No module named '([^']+)'"), IssueKind.MISSING_DEPENDENCY, 1),
    (re.compile(r"Cannot find module '([^']+)'"), IssueKind.MISSING_DEPENDENCY, 1),
    (re.compile(r"ImportError:\s*(.+)"), IssueKind.PYTHON_EXCEPTION, 1),

    # Dependency version / resolution errors
    (re.compile(r"Could not find a version that satisfies the requirement (\S+)", re.IGNORECASE), IssueKind.DEPENDENCY_VERSION, 1),
    (re.compile(r"No matching distribution found for (\S+)", re.IGNORECASE), IssueKind.DEPENDENCY_VERSION, 1),
    (re.compile(r"npm ERR! 404 Not Found[^\n]*'([^']+)'", re.IGNORECASE), IssueKind.DEPENDENCY_VERSION, 1),
    (re.compile(r"peer dep missing:\s*(.+)", re.IGNORECASE), IssueKind.DEPENDENCY_VERSION, 1),

    # Python syntax errors
    (re.compile(r"SyntaxError:\s*(.+)"), IssueKind.SYNTAX_ERROR, 1),

    # Python exceptions (generic)
    (re.compile(r"Traceback \(most recent call last\)"), IssueKind.PYTHON_EXCEPTION, 0),

    # Pytest / unittest failures
    (re.compile(r"FAILED\s+(\S+::\S+)"), IssueKind.TEST_FAILURE, 1),
    (re.compile(r"FAIL:\s+(\S+)\s+\("), IssueKind.TEST_FAILURE, 1),
    (re.compile(r"\d+ failed"), IssueKind.TEST_FAILURE, 0),

    # Docker build errors
    (re.compile(r"ERROR: (failed to build|failed to solve|dockerfile parse error)", re.IGNORECASE), IssueKind.DOCKER_BUILD, 1),
    (re.compile(r"error building image", re.IGNORECASE), IssueKind.DOCKER_BUILD, 0),

    # Permission errors
    (re.compile(r"Permission denied|EACCES|EPERM", re.IGNORECASE), IssueKind.PERMISSION, 0),

    # Non-zero exit codes
    (re.compile(r"exit(?:ed with)? (?:code\s+)?(\d+)|Process exited with code (\d+)", re.IGNORECASE), IssueKind.PROCESS_EXIT, 1),

    # FATAL lines
    (re.compile(r"^FATAL[:\s](.+)", re.IGNORECASE | re.MULTILINE), IssueKind.FATAL, 1),

    # Generic ERROR lines (catch-all, low priority)
    (re.compile(r"^ERROR[:\s](.+)", re.IGNORECASE | re.MULTILINE), IssueKind.GENERIC_ERROR, 1),
]

_CONTEXT_LINES = 3   # lines before/after to capture for context
_MAX_ISSUES = 50     # cap to avoid flooding on pathological logs


def analyze_log_for_issues(log_content: str) -> list[LogIssue]:
    """
    Scan log content and return a list of :class:`LogIssue` objects ordered by
    line number (earliest first).

    Each issue captures:
    - the kind of problem (IssueKind enum)
    - the 1-indexed line number where it was found
    - the raw log line
    - an extracted detail string (e.g. module name, test ID)
    - up to 3 lines of surrounding context

    Duplicate lines (same line matched by multiple patterns) are de-duplicated;
    only the most specific match (earliest pattern in _PATTERNS) is kept.
    """
    lines = log_content.splitlines()
    # line_num -> LogIssue (keeps first/most-specific match per line)
    seen: dict[int, LogIssue] = {}

    for pattern, kind, group_idx in _PATTERNS:
        for match in pattern.finditer(log_content):
            if len(seen) >= _MAX_ISSUES:
                break
            # Determine which line this match starts on
            start_pos = match.start()
            line_num = log_content[:start_pos].count("\n") + 1  # 1-indexed

            if line_num in seen:
                continue  # already captured a more-specific match for this line

            raw_line = lines[line_num - 1] if line_num <= len(lines) else match.group(0)

            # Extract detail
            try:
                detail = match.group(group_idx).strip() if group_idx > 0 else match.group(0).strip()
            except IndexError:
                detail = match.group(0).strip()

            # Surrounding context
            ctx_start = max(0, line_num - 1 - _CONTEXT_LINES)
            ctx_end = min(len(lines), line_num + _CONTEXT_LINES)
            context = lines[ctx_start:ctx_end]

            seen[line_num] = LogIssue(
                kind=kind,
                line_number=line_num,
                line=raw_line.strip(),
                detail=detail,
                context=context,
            )

    return sorted(seen.values(), key=lambda i: i.line_number)


def first_error(log_content: str) -> LogIssue | None:
    """Return the earliest-occurring issue in the log, or None if log is clean."""
    issues = analyze_log_for_issues(log_content)
    return issues[0] if issues else None


def summarize_issues(log_content: str) -> str:
    """
    Return a human-readable plain-text summary of all detected issues,
    suitable for including in an LLM prompt or a CLI report.
    """
    issues = analyze_log_for_issues(log_content)
    if not issues:
        return "No issues detected — log appears clean."

    lines = [f"Detected {len(issues)} issue(s) in log:\n"]
    for i, issue in enumerate(issues, 1):
        lines.append(
            f"  [{i}] Line {issue.line_number} | {issue.kind.value}\n"
            f"       Detail : {issue.detail}\n"
            f"       Log    : {issue.line}\n"
        )
    return "\n".join(lines)
