"""
Tests for CD-specific issue detection in mcp_tools/log_analyzer.py

Covers Kubernetes, Helm, Terraform, container registry, and health check failures
that occur in deployment pipelines running as GitHub Actions workflows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_tools.log_analyzer import (
    IssueKind,
    analyze_log_for_issues,
    first_error,
    summarize_issues,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _kinds(log_content: str) -> list[IssueKind]:
    return [i.kind for i in analyze_log_for_issues(log_content)]


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Kubernetes — CrashLoopBackOff
# ---------------------------------------------------------------------------

class TestKubernetesCrashLoop:
    log = _load("k8s_crash_loop.log")

    def test_detects_crash_loop(self):
        assert IssueKind.KUBERNETES_ERROR in _kinds(self.log)

    def test_detects_back_off_restart(self):
        issues = analyze_log_for_issues(self.log)
        k8s = [i for i in issues if i.kind == IssueKind.KUBERNETES_ERROR]
        assert any("CrashLoopBackOff" in i.line or "Back-off" in i.line for i in k8s)

    def test_first_error_is_kubernetes(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.KUBERNETES_ERROR


# ---------------------------------------------------------------------------
# Kubernetes — ImagePullBackOff
# ---------------------------------------------------------------------------

class TestKubernetesImagePull:
    log = _load("k8s_image_pull_error.log")

    def test_detects_image_pull_backoff(self):
        assert IssueKind.KUBERNETES_ERROR in _kinds(self.log)

    def test_detects_registry_manifest_unknown(self):
        assert IssueKind.REGISTRY_ERROR in _kinds(self.log)

    def test_image_pull_issue_contains_keyword(self):
        issues = analyze_log_for_issues(self.log)
        k8s = [i for i in issues if i.kind == IssueKind.KUBERNETES_ERROR]
        assert any(
            "ImagePullBackOff" in i.line or "ErrImagePull" in i.line for i in k8s
        )


# ---------------------------------------------------------------------------
# Helm — upgrade failed
# ---------------------------------------------------------------------------

class TestHelmUpgradeFailed:
    log = _load("helm_upgrade_failed.log")

    def test_detects_helm_error(self):
        assert IssueKind.HELM_ERROR in _kinds(self.log)

    def test_extracts_helm_failure_detail(self):
        issues = analyze_log_for_issues(self.log)
        helm = [i for i in issues if i.kind == IssueKind.HELM_ERROR]
        assert len(helm) >= 1
        assert any("timed out" in i.detail.lower() or "UPGRADE FAILED" in i.line for i in helm)

    def test_first_error_is_helm(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.HELM_ERROR


# ---------------------------------------------------------------------------
# Terraform — apply error
# ---------------------------------------------------------------------------

class TestTerraformError:
    log = _load("terraform_error.log")

    def test_detects_terraform_error(self):
        assert IssueKind.TERRAFORM_ERROR in _kinds(self.log)

    def test_detects_apply_failed(self):
        issues = analyze_log_for_issues(self.log)
        tf = [i for i in issues if i.kind == IssueKind.TERRAFORM_ERROR]
        assert len(tf) >= 1

    def test_extracts_terraform_detail(self):
        issues = analyze_log_for_issues(self.log)
        tf = [i for i in issues if i.kind == IssueKind.TERRAFORM_ERROR]
        # Should capture the IAM error message from the box format
        combined = " ".join(i.detail for i in tf)
        assert "permissions" in combined.lower() or "Apply failed" in combined or "Lambda" in combined

    def test_first_error_is_terraform(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.TERRAFORM_ERROR


# ---------------------------------------------------------------------------
# Registry — auth error
# ---------------------------------------------------------------------------

class TestRegistryAuthError:
    log = _load("registry_auth_error.log")

    def test_detects_registry_error(self):
        assert IssueKind.REGISTRY_ERROR in _kinds(self.log)

    def test_extracts_auth_detail(self):
        issues = analyze_log_for_issues(self.log)
        reg = [i for i in issues if i.kind == IssueKind.REGISTRY_ERROR]
        assert len(reg) >= 1
        assert any("authentication" in i.detail.lower() or "unauthorized" in i.line.lower() for i in reg)

    def test_first_error_is_registry(self):
        issue = first_error(self.log)
        assert issue is not None
        assert issue.kind == IssueKind.REGISTRY_ERROR


# ---------------------------------------------------------------------------
# Health check / readiness probe
# ---------------------------------------------------------------------------

class TestHealthCheckFailed:
    log = _load("health_check_failed.log")

    def test_detects_health_check_failure(self):
        assert IssueKind.HEALTH_CHECK_FAILED in _kinds(self.log)

    def test_detects_readiness_probe(self):
        issues = analyze_log_for_issues(self.log)
        hc = [i for i in issues if i.kind == IssueKind.HEALTH_CHECK_FAILED]
        assert any("Readiness probe" in i.line or "Liveness probe" in i.line for i in hc)

    def test_extracts_probe_detail(self):
        issues = analyze_log_for_issues(self.log)
        hc = [i for i in issues if i.kind == IssueKind.HEALTH_CHECK_FAILED]
        assert len(hc) >= 1
        assert any(i.detail for i in hc)


# ---------------------------------------------------------------------------
# Parametrized single-line CD patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("log_line,expected_kind,detail_fragment", [
    # Kubernetes
    ("  Reason: CrashLoopBackOff", IssueKind.KUBERNETES_ERROR, ""),
    ("Warning  Failed  ErrImagePull: failed to pull image", IssueKind.KUBERNETES_ERROR, ""),
    ("Warning  BackOff  Back-off restarting failed container", IssueKind.KUBERNETES_ERROR, ""),
    ("FailedScheduling: 0/3 nodes are available: insufficient memory", IssueKind.KUBERNETES_ERROR, "insufficient memory"),
    ("Error from server (NotFound): pods 'api-service' not found", IssueKind.KUBERNETES_ERROR, ""),

    # Helm
    ("Error: UPGRADE FAILED: post-upgrade hooks failed: timed out waiting", IssueKind.HELM_ERROR, "post-upgrade hooks failed"),
    ("Error: INSTALL FAILED: cannot re-use a name that is still in use", IssueKind.HELM_ERROR, "cannot re-use"),
    ("rendered manifests contain a resource that already exists", IssueKind.HELM_ERROR, ""),
    ("timed out waiting for the condition", IssueKind.HELM_ERROR, ""),

    # Terraform
    ("│ Error: Invalid function argument", IssueKind.TERRAFORM_ERROR, "Invalid function argument"),
    ("Apply failed!", IssueKind.TERRAFORM_ERROR, ""),
    ("Error acquiring the state lock", IssueKind.TERRAFORM_ERROR, ""),

    # Registry
    ("denied: access forbidden", IssueKind.REGISTRY_ERROR, "access forbidden"),
    ("manifest unknown: manifest unknown", IssueKind.REGISTRY_ERROR, ""),
    ("repository does not exist or may require 'docker login': pull access denied", IssueKind.REGISTRY_ERROR, ""),

    # Health check
    ("Readiness probe failed: HTTP probe failed with statuscode: 503", IssueKind.HEALTH_CHECK_FAILED, "HTTP probe failed"),
    ("Liveness probe failed: Get http://localhost:8080/health: connection refused", IssueKind.HEALTH_CHECK_FAILED, ""),
    ("health check failed after 30 attempts", IssueKind.HEALTH_CHECK_FAILED, ""),
    ("service is unhealthy, shutting down", IssueKind.HEALTH_CHECK_FAILED, ""),
])
def test_cd_single_line_detection(log_line: str, expected_kind: IssueKind, detail_fragment: str):
    issues = analyze_log_for_issues(log_line)
    assert len(issues) >= 1, f"Expected at least one issue in: {log_line!r}"
    assert issues[0].kind == expected_kind, (
        f"Expected {expected_kind}, got {issues[0].kind} for: {log_line!r}"
    )
    if detail_fragment:
        assert detail_fragment.lower() in issues[0].detail.lower()


# ---------------------------------------------------------------------------
# CD issues appear in summarize_issues output
# ---------------------------------------------------------------------------

def test_summarize_includes_cd_kinds():
    log = "\n".join([
        "Reason: CrashLoopBackOff",
        "Error: UPGRADE FAILED: timed out waiting for the condition",
    ])
    summary = summarize_issues(log)
    assert "kubernetes_error" in summary
    assert "helm_error" in summary


# ---------------------------------------------------------------------------
# CI and CD issues coexist and are ordered by line number
# ---------------------------------------------------------------------------

def test_ci_and_cd_issues_ordered():
    log = "\n".join([
        "ModuleNotFoundError: No module named 'boto3'",   # line 1 — CI
        "All tests passed",                                # line 2
        "Error: UPGRADE FAILED: something went wrong",    # line 3 — CD
        "CrashLoopBackOff",                               # line 4 — CD
    ])
    issues = analyze_log_for_issues(log)
    line_numbers = [i.line_number for i in issues]
    assert line_numbers == sorted(line_numbers)
    kinds = [i.kind for i in issues]
    assert IssueKind.MISSING_DEPENDENCY in kinds
    assert IssueKind.HELM_ERROR in kinds
    assert IssueKind.KUBERNETES_ERROR in kinds
