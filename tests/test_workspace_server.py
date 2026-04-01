"""
Tests for mcp_tools/workspace_server.py

Covers:
- read_build_log: normal reads, truncation, error paths
- list_workspace_files: listing, filtering, error paths
- analyze_log_issues: MCP tool wrapper delegates to log_analyzer correctly
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from mcp_tools.workspace_server import (
    MAX_LOG_CHARS,
    HEAD_CHARS,
    TAIL_CHARS,
    read_build_log,
    list_workspace_files,
    analyze_log_issues,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# read_build_log
# ---------------------------------------------------------------------------

class TestReadBuildLog:
    def test_reads_existing_log(self, tmp_path):
        log = tmp_path / "build.log"
        log.write_text("Step 1 OK\nStep 2 OK\n", encoding="utf-8")
        result = read_build_log(str(log))
        assert "Step 1 OK" in result
        assert "Step 2 OK" in result

    def test_missing_file_returns_error(self, tmp_path):
        result = read_build_log(str(tmp_path / "nonexistent.log"))
        assert result.startswith("ERROR")
        assert "not found" in result.lower()

    def test_directory_path_returns_error(self, tmp_path):
        result = read_build_log(str(tmp_path))
        assert result.startswith("ERROR")
        assert "not a file" in result.lower()

    def test_small_log_not_truncated(self, tmp_path):
        content = "A" * 1000
        log = tmp_path / "small.log"
        log.write_text(content, encoding="utf-8")
        result = read_build_log(str(log))
        assert result == content

    def test_large_log_truncated_with_notice(self, tmp_path):
        # Create a log larger than MAX_LOG_CHARS
        content = "X" * (MAX_LOG_CHARS + 10_000)
        log = tmp_path / "big.log"
        log.write_text(content, encoding="utf-8")
        result = read_build_log(str(log))
        assert "omitted" in result
        assert "truncated" in result

    def test_large_log_keeps_head(self, tmp_path):
        head_marker = "HEAD_MARKER"
        tail_marker = "TAIL_MARKER"
        # Construct: short head + filler + short tail, total > MAX_LOG_CHARS
        head = head_marker + "A" * (HEAD_CHARS - len(head_marker))
        filler = "B" * (MAX_LOG_CHARS)
        tail = "C" * (TAIL_CHARS - len(tail_marker)) + tail_marker
        content = head + filler + tail
        log = tmp_path / "big.log"
        log.write_text(content, encoding="utf-8")
        result = read_build_log(str(log))
        assert head_marker in result
        assert tail_marker in result

    def test_large_log_result_is_bounded(self, tmp_path):
        content = "Z" * (MAX_LOG_CHARS * 3)
        log = tmp_path / "huge.log"
        log.write_text(content, encoding="utf-8")
        result = read_build_log(str(log))
        # Result must be notably smaller than the original
        assert len(result) < len(content)

    def test_reads_fixture_import_error_log(self):
        result = read_build_log(str(FIXTURES / "python_import_error.log"))
        assert "ModuleNotFoundError" in result
        assert "redis" in result

    def test_reads_fixture_oom_log(self):
        result = read_build_log(str(FIXTURES / "oom_killed.log"))
        assert "OOMKilled" in result

    def test_unicode_content_handled(self, tmp_path):
        log = tmp_path / "unicode.log"
        log.write_text("Build ✓ passed — résumé: 成功\n", encoding="utf-8")
        result = read_build_log(str(log))
        assert "✓" in result

    def test_binary_content_does_not_crash(self, tmp_path):
        log = tmp_path / "binary.log"
        log.write_bytes(b"\x00\xff\xfe binary data \x80\x81")
        result = read_build_log(str(log))
        # Should return something (replacement chars), not raise
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# list_workspace_files
# ---------------------------------------------------------------------------

class TestListWorkspaceFiles:
    def test_lists_files(self, tmp_path):
        (tmp_path / "app.py").write_text("x")
        (tmp_path / "utils.py").write_text("x")
        result = list_workspace_files(str(tmp_path))
        assert "app.py" in result
        assert "utils.py" in result

    def test_missing_workspace_returns_error(self, tmp_path):
        result = list_workspace_files(str(tmp_path / "no_such_dir"))
        assert result.startswith("ERROR")
        assert "not found" in result.lower()

    def test_file_path_as_workspace_returns_error(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = list_workspace_files(str(f))
        assert result.startswith("ERROR")
        assert "not a directory" in result.lower()

    def test_skips_git_directory(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("x")
        (tmp_path / "main.py").write_text("x")
        result = list_workspace_files(str(tmp_path))
        assert ".git" not in result
        assert "main.py" in result

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "lodash.js").write_text("x")
        (tmp_path / "index.js").write_text("x")
        result = list_workspace_files(str(tmp_path))
        assert "node_modules" not in result
        assert "index.js" in result

    def test_skips_pycache(self, tmp_path):
        pc = tmp_path / "__pycache__"
        pc.mkdir()
        (pc / "app.cpython-311.pyc").write_bytes(b"x")
        (tmp_path / "app.py").write_text("x")
        result = list_workspace_files(str(tmp_path))
        assert "__pycache__" not in result
        assert "app.py" in result

    def test_custom_glob_pattern(self, tmp_path):
        (tmp_path / "main.py").write_text("x")
        (tmp_path / "README.md").write_text("x")
        (tmp_path / "config.yaml").write_text("x")
        result = list_workspace_files(str(tmp_path), pattern="*.py")
        assert "main.py" in result
        assert "README.md" not in result

    def test_empty_directory(self, tmp_path):
        result = list_workspace_files(str(tmp_path))
        assert "No files found" in result

    def test_result_is_sorted(self, tmp_path):
        for name in ["zebra.py", "alpha.py", "middle.py"]:
            (tmp_path / name).write_text("x")
        result = list_workspace_files(str(tmp_path))
        lines = result.strip().splitlines()
        assert lines == sorted(lines)

    def test_nested_files_included(self, tmp_path):
        sub = tmp_path / "src" / "core"
        sub.mkdir(parents=True)
        (sub / "engine.py").write_text("x")
        result = list_workspace_files(str(tmp_path))
        assert "engine.py" in result


# ---------------------------------------------------------------------------
# analyze_log_issues (MCP tool wrapper)
# ---------------------------------------------------------------------------

class TestAnalyzeLogIssues:
    def test_missing_file_returns_error(self, tmp_path):
        result = analyze_log_issues(str(tmp_path / "no.log"))
        assert result.startswith("ERROR")

    def test_directory_path_returns_error(self, tmp_path):
        result = analyze_log_issues(str(tmp_path))
        assert result.startswith("ERROR")

    def test_clean_log_reports_no_issues(self, tmp_path):
        log = tmp_path / "ok.log"
        log.write_text("All tests passed.\nBuild succeeded.\n")
        result = analyze_log_issues(str(log))
        assert "clean" in result.lower() or "no issues" in result.lower()

    def test_import_error_log_surfaces_dependency(self):
        result = analyze_log_issues(str(FIXTURES / "python_import_error.log"))
        assert "missing_dependency" in result
        assert "redis" in result

    def test_oom_log_surfaces_oom(self):
        result = analyze_log_issues(str(FIXTURES / "oom_killed.log"))
        assert "oom_killed" in result

    def test_test_failure_log_surfaces_failures(self):
        result = analyze_log_issues(str(FIXTURES / "test_failure.log"))
        assert "test_failure" in result

    def test_dependency_version_log_surfaces_version_error(self):
        result = analyze_log_issues(str(FIXTURES / "dependency_version_error.log"))
        assert "dependency_version_error" in result
        assert "fastapi" in result

    def test_syntax_error_log_surfaces_syntax(self):
        result = analyze_log_issues(str(FIXTURES / "syntax_error.log"))
        assert "syntax_error" in result

    def test_timeout_log_surfaces_timeout(self):
        result = analyze_log_issues(str(FIXTURES / "timeout.log"))
        assert "timeout" in result

    def test_docker_error_log_surfaces_docker(self):
        result = analyze_log_issues(str(FIXTURES / "docker_build_error.log"))
        assert "docker_build_error" in result

    def test_returns_string(self, tmp_path):
        log = tmp_path / "x.log"
        log.write_text("ERROR: something went wrong\n")
        result = analyze_log_issues(str(log))
        assert isinstance(result, str)
