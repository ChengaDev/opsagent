"""
Tests for mcp_tools/log_analyzer.py

Covers:
- Issue detection for each IssueKind from realistic CI log fixtures
- first_error() returns earliest issue when log has multiple problems
- summarize_issues() produces readable output
- Edge cases: empty log, clean log, malformed content, very large log
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mcp_tools.log_analyzer import (
    IssueKind,
    LogIssue,
    analyze_log_for_issues,
    first_error,
    summarize_issues,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kinds(issues: list[LogIssue]) -> list[IssueKind]:
    return [i.kind for i in issues]


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture-based tests — each fixture maps to a specific failure scenario
# ---------------------------------------------------------------------------

class TestPythonImportError:
    log = _load("python_import_error.log")

    def test_detects_missing_dependency(self):
        issues = analyze_log_for_issues(self.log)
        kinds = _kinds(issues)
        assert IssueKind.MISSING_DEPENDENCY in kinds

    def test_extracts_module_name(self):
        issues = analyze_log_for_issues(self.log)
        dep_issues = [i for i in issues if i.kind == IssueKind.MISSING_DEPENDENCY]
        assert any("redis" in i.detail for i in dep_issues)

    def test_first_error_is_import_related(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind in (IssueKind.MISSING_DEPENDENCY, IssueKind.PYTHON_EXCEPTION)

    def test_line_number_is_positive(self):
        issues = analyze_log_for_issues(self.log)
        for issue in issues:
            assert issue.line_number >= 1

    def test_context_lines_populated(self):
        issues = analyze_log_for_issues(self.log)
        for issue in issues:
            assert isinstance(issue.context, list)
            assert len(issue.context) > 0


class TestOOMKilled:
    log = _load("oom_killed.log")

    def test_detects_oom(self):
        issues = analyze_log_for_issues(self.log)
        assert IssueKind.OOM_KILLED in _kinds(issues)

    def test_first_error_is_oom(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.OOM_KILLED

    def test_oom_line_contains_keyword(self):
        issues = analyze_log_for_issues(self.log)
        oom = next(i for i in issues if i.kind == IssueKind.OOM_KILLED)
        assert "OOMKilled" in oom.line or "killed" in oom.line.lower()


class TestTestFailure:
    log = _load("test_failure.log")

    def test_detects_test_failures(self):
        issues = analyze_log_for_issues(self.log)
        assert IssueKind.TEST_FAILURE in _kinds(issues)

    def test_finds_both_failed_tests(self):
        issues = analyze_log_for_issues(self.log)
        failed = [i for i in issues if i.kind == IssueKind.TEST_FAILURE]
        # Fixture has 2 FAILED lines and 1 "2 failed" summary line
        test_ids = {i.detail for i in failed}
        assert any("test_login_missing_token" in d for d in test_ids)
        assert any("test_refund" in d for d in test_ids)

    def test_first_error_is_test_failure(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.TEST_FAILURE


class TestDependencyVersionError:
    log = _load("dependency_version_error.log")

    def test_detects_version_error(self):
        issues = analyze_log_for_issues(self.log)
        assert IssueKind.DEPENDENCY_VERSION in _kinds(issues)

    def test_extracts_package_name(self):
        issues = analyze_log_for_issues(self.log)
        version_issues = [i for i in issues if i.kind == IssueKind.DEPENDENCY_VERSION]
        assert any("fastapi" in i.detail for i in version_issues)

    def test_first_error_is_dependency(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.DEPENDENCY_VERSION


class TestSyntaxError:
    log = _load("syntax_error.log")

    def test_detects_syntax_error(self):
        issues = analyze_log_for_issues(self.log)
        assert IssueKind.SYNTAX_ERROR in _kinds(issues)

    def test_extracts_syntax_message(self):
        issues = analyze_log_for_issues(self.log)
        syntax = [i for i in issues if i.kind == IssueKind.SYNTAX_ERROR]
        assert len(syntax) >= 1
        assert "expected ':'" in syntax[0].detail or "expected" in syntax[0].detail

    def test_first_error_is_syntax(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.SYNTAX_ERROR


class TestTimeout:
    log = _load("timeout.log")

    def test_detects_timeout(self):
        issues = analyze_log_for_issues(self.log)
        assert IssueKind.TIMEOUT in _kinds(issues)

    def test_first_error_is_timeout(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.TIMEOUT


class TestDockerBuildError:
    log = _load("docker_build_error.log")

    def test_detects_docker_error(self):
        issues = analyze_log_for_issues(self.log)
        assert IssueKind.DOCKER_BUILD in _kinds(issues)

    def test_first_error_is_docker(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.DOCKER_BUILD


class TestCleanBuild:
    log = _load("clean_build.log")

    def test_no_issues_in_clean_log(self):
        issues = analyze_log_for_issues(self.log)
        assert issues == []

    def test_first_error_is_none(self):
        assert first_error(self.log) is None

    def test_summarize_reports_clean(self):
        summary = summarize_issues(self.log)
        assert "clean" in summary.lower() or "no issues" in summary.lower()


# ---------------------------------------------------------------------------
# Inline / parametrized tests — cover specific patterns without fixture files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("log_line,expected_kind,expected_detail_fragment", [
    # Python missing module
    (
        "ModuleNotFoundError: No module named 'boto3'",
        IssueKind.MISSING_DEPENDENCY,
        "boto3",
    ),
    # Node missing module
    (
        "Cannot find module 'express'",
        IssueKind.MISSING_DEPENDENCY,
        "express",
    ),
    # OOM variants
    (
        "The container was OOMKilled by the kernel.",
        IssueKind.OOM_KILLED,
        "OOMKilled",
    ),
    (
        "Killed process 1234 (python) total-vm:2048MB",
        IssueKind.OOM_KILLED,
        "",  # detail not checked for this variant
    ),
    # Dependency version (pip)
    (
        "ERROR: Could not find a version that satisfies the requirement torch==2.5.0",
        IssueKind.DEPENDENCY_VERSION,
        "torch==2.5.0",
    ),
    # Pytest FAILED line
    (
        "FAILED tests/unit/test_core.py::test_process_event - AssertionError",
        IssueKind.TEST_FAILURE,
        "tests/unit/test_core.py::test_process_event",
    ),
    # Syntax error
    (
        "SyntaxError: invalid syntax",
        IssueKind.SYNTAX_ERROR,
        "invalid syntax",
    ),
    # Timeout
    (
        "ConnectionError: connection timed out after 30s",
        IssueKind.TIMEOUT,
        "",
    ),
    # Docker build error
    (
        "ERROR: failed to build: failed to solve: exit 1",
        IssueKind.DOCKER_BUILD,
        "failed to build",
    ),
    # Permission
    (
        "PermissionError: [Errno 13] Permission denied: '/etc/secrets'",
        IssueKind.PERMISSION,
        "",
    ),
    # FATAL line
    (
        "FATAL: database connection pool exhausted",
        IssueKind.FATAL,
        "database connection pool exhausted",
    ),
])
def test_single_line_detection(log_line: str, expected_kind: IssueKind, expected_detail_fragment: str):
    issues = analyze_log_for_issues(log_line)
    assert len(issues) >= 1, f"Expected at least one issue in: {log_line!r}"
    assert issues[0].kind == expected_kind
    if expected_detail_fragment:
        assert expected_detail_fragment in issues[0].detail


# ---------------------------------------------------------------------------
# first_error() ordering guarantee
# ---------------------------------------------------------------------------

def test_first_error_returns_earliest_line():
    log = textwrap.dedent("""\
        Build started
        All checks passing
        FATAL: disk quota exceeded
        FAILED tests/foo.py::bar - AssertionError
        ModuleNotFoundError: No module named 'xyz'
    """)
    issue = first_error(log)
    assert issue is not None
    assert issue.kind == IssueKind.FATAL   # FATAL appears first on line 3


def test_multiple_issue_types_ordered_by_line():
    log = textwrap.dedent("""\
        line 1: ok
        line 2: FAILED tests/a.py::test_one - AssertionError
        line 3: ok
        line 4: ModuleNotFoundError: No module named 'foo'
    """)
    issues = analyze_log_for_issues(log)
    assert len(issues) >= 2
    # Must be sorted ascending by line number
    line_numbers = [i.line_number for i in issues]
    assert line_numbers == sorted(line_numbers)
    assert issues[0].kind == IssueKind.TEST_FAILURE
    assert issues[1].kind == IssueKind.MISSING_DEPENDENCY


def test_duplicate_line_not_reported_twice():
    # A line that matches multiple patterns should only appear once
    log = "ModuleNotFoundError: No module named 'redis'\n"
    issues = analyze_log_for_issues(log)
    line_numbers = [i.line_number for i in issues]
    assert len(line_numbers) == len(set(line_numbers)), "Duplicate line numbers found"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_log():
    assert analyze_log_for_issues("") == []
    assert first_error("") is None


def test_whitespace_only_log():
    assert analyze_log_for_issues("   \n\n\t\n") == []


def test_log_with_no_errors():
    log = "Build succeeded\nAll tests passed\nDone."
    assert analyze_log_for_issues(log) == []


def test_very_large_log_does_not_hang():
    """Analyzer should complete in reasonable time on a 200k-line log."""
    chunk = "INFO: Processing item 123 OK\n" * 200_000
    issues = analyze_log_for_issues(chunk)
    assert issues == []


def test_log_with_max_issues_capped():
    """If a log has hundreds of FAILED lines, we cap at MAX_ISSUES."""
    from mcp_tools.log_analyzer import _MAX_ISSUES
    many_failures = "\n".join(
        f"FAILED tests/test_{i}.py::test_fn - AssertionError" for i in range(_MAX_ISSUES + 100)
    )
    issues = analyze_log_for_issues(many_failures)
    assert len(issues) <= _MAX_ISSUES


def test_issue_line_field_strips_whitespace():
    log = "   ModuleNotFoundError: No module named 'foo'   \n"
    issues = analyze_log_for_issues(log)
    assert len(issues) >= 1
    assert issues[0].line == issues[0].line.strip()


# ---------------------------------------------------------------------------
# summarize_issues()
# ---------------------------------------------------------------------------

def test_summarize_lists_all_issues():
    log = textwrap.dedent("""\
        FAILED tests/test_a.py::test_one - AssertionError
        ModuleNotFoundError: No module named 'httpx'
    """)
    summary = summarize_issues(log)
    assert "test_failure" in summary
    assert "missing_dependency" in summary
    assert "httpx" in summary


def test_summarize_includes_line_numbers():
    log = "line1\nFATAL: boom\nline3\n"
    summary = summarize_issues(log)
    assert "Line 2" in summary


def test_summarize_clean_log_message():
    summary = summarize_issues("Everything is fine.\n")
    assert "clean" in summary.lower() or "no issues" in summary.lower()
