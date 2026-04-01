"""
Tests for mcp_tools/notification_server.py

Covers:
- send_webhook_notification: SSRF guard, HTTPS requirement, payload validation,
  blocked hostnames, env var fallback, success/error status parsing
- send_slack_notification: webhook prefix guard, stub mode, env var fallback
- post_github_pr_comment: repo validation, pr_number validation, stub mode
"""
from __future__ import annotations

import json

import pytest

from mcp_tools.notification_server import (
    send_webhook_notification,
    send_slack_notification,
    post_github_pr_comment,
)

# Convenience: call with explicit webhook_url kwarg throughout so signature
# changes (webhook_url moved to last position) don't break positional ordering.

# ---------------------------------------------------------------------------
# send_webhook_notification
# ---------------------------------------------------------------------------

class TestWebhookUrlValidation:
    def test_empty_url_returns_skipped(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_URL", raising=False)
        result = json.loads(send_webhook_notification("title", "rca", webhook_url=""))
        assert result["status"] == "skipped"

    def test_http_url_rejected(self):
        result = json.loads(send_webhook_notification("t", "r", webhook_url="http://example.com/hook"))
        assert result["status"] == "error"
        assert "https" in result["reason"]

    def test_non_url_string_rejected(self):
        result = json.loads(send_webhook_notification("t", "r", webhook_url="not-a-url"))
        assert result["status"] == "error"

    def test_https_url_accepted_format(self, monkeypatch):
        import httpx
        class _FakeResponse:
            status_code = 200
            text = "ok"
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse())
        result = json.loads(send_webhook_notification("title", "rca", webhook_url="https://example.com/hook"))
        assert result["status"] == "sent"
        assert result["http_status"] == 200

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_URL", "https://example.com/hook")
        import httpx
        class _FakeResponse:
            status_code = 200
            text = "ok"
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse())
        result = json.loads(send_webhook_notification("title", "rca"))
        assert result["status"] == "sent"


class TestWebhookSsrfGuard:
    @pytest.mark.parametrize("url", [
        "https://localhost/hook",
        "https://localhost:8080/hook",
        "https://127.0.0.1/hook",
        "https://127.1.2.3/hook",
        "https://0.0.0.0/hook",
        "https://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
    ])
    def test_internal_hostnames_blocked(self, url):
        result = json.loads(send_webhook_notification("title", "rca", webhook_url=url))
        assert result["status"] == "error"
        assert "internal" in result["reason"].lower() or "not allowed" in result["reason"].lower()

    def test_extra_blocked_host_via_env(self, monkeypatch):
        import mcp_tools.notification_server as ns
        original = ns._BLOCKED_HOSTNAMES.copy()
        try:
            ns._BLOCKED_HOSTNAMES.add("internal.corp.com")
            result = json.loads(send_webhook_notification("t", "r", webhook_url="https://internal.corp.com/hook"))
            assert result["status"] == "error"
        finally:
            ns._BLOCKED_HOSTNAMES.clear()
            ns._BLOCKED_HOSTNAMES.update(original)

    def test_env_var_parsing_adds_hosts(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_BLOCKED_HOSTS", "evil.internal, bad.corp.com")
        import importlib
        import mcp_tools.notification_server as ns
        importlib.reload(ns)
        assert "evil.internal" in ns._BLOCKED_HOSTNAMES
        assert "bad.corp.com" in ns._BLOCKED_HOSTNAMES
        monkeypatch.delenv("WEBHOOK_BLOCKED_HOSTS", raising=False)
        importlib.reload(ns)


class TestWebhookPayload:
    def test_severity_normalised_to_p2_if_invalid(self, monkeypatch):
        import httpx
        captured = {}
        def _fake_post(url, json, **kw):
            captured["payload"] = json
            class R:
                status_code = 200
                text = "ok"
            return R()
        monkeypatch.setattr(httpx, "post", _fake_post)
        send_webhook_notification("t", "r", severity="XX", webhook_url="https://example.com/hook")
        assert captured["payload"]["severity"] == "P2"

    def test_valid_severity_preserved(self, monkeypatch):
        import httpx
        captured = {}
        def _fake_post(url, json, **kw):
            captured["payload"] = json
            class R:
                status_code = 200
                text = "ok"
            return R()
        monkeypatch.setattr(httpx, "post", _fake_post)
        send_webhook_notification("t", "r", severity="p1", webhook_url="https://example.com/hook")
        assert captured["payload"]["severity"] == "P1"

    def test_payload_contains_required_fields(self, monkeypatch):
        import httpx
        captured = {}
        def _fake_post(url, json, **kw):
            captured["payload"] = json
            class R:
                status_code = 200
                text = "ok"
            return R()
        monkeypatch.setattr(httpx, "post", _fake_post)
        send_webhook_notification("Build #42 failed", "Root cause here", webhook_url="https://example.com/hook")
        p = captured["payload"]
        assert p["event"] == "opsagent.rca"
        assert p["title"] == "Build #42 failed"
        assert p["rca"] == "Root cause here"
        assert "timestamp" in p

    def test_invalid_pipeline_url_rejected(self):
        result = json.loads(
            send_webhook_notification("t", "r", pipeline_url="ftp://bad", webhook_url="https://example.com/hook")
        )
        assert result["status"] == "error"
        assert "pipeline_url" in result["reason"]

    def test_pipeline_url_included_in_payload(self, monkeypatch):
        import httpx
        captured = {}
        def _fake_post(url, json, **kw):
            captured["payload"] = json
            class R:
                status_code = 200
                text = "ok"
            return R()
        monkeypatch.setattr(httpx, "post", _fake_post)
        send_webhook_notification(
            "t", "r",
            pipeline_url="https://github.com/actions/runs/123",
            webhook_url="https://example.com/hook",
        )
        assert captured["payload"]["pipeline_url"] == "https://github.com/actions/runs/123"

    def test_non_200_response_returns_error_status(self, monkeypatch):
        import httpx
        class _FakeResponse:
            status_code = 500
            text = "Internal Server Error"
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse())
        result = json.loads(send_webhook_notification("t", "r", webhook_url="https://example.com/hook"))
        assert result["status"] == "error"
        assert result["http_status"] == 500

    def test_request_error_returns_error_status(self, monkeypatch):
        import httpx
        def _raise(*a, **kw):
            raise httpx.RequestError("connection refused")
        monkeypatch.setattr(httpx, "post", _raise)
        result = json.loads(send_webhook_notification("t", "r", webhook_url="https://example.com/hook"))
        assert result["status"] == "error"
        assert "connection refused" not in json.dumps(result)


# ---------------------------------------------------------------------------
# send_slack_notification — guard / stub behaviour
# ---------------------------------------------------------------------------

class TestSlackNotificationGuard:
    def test_stub_url_returns_skipped(self):
        result = json.loads(send_slack_notification(
            "t", "r", webhook_url="https://hooks.slack.com/services/xxx/yyy/zzz"
        ))
        assert result["status"] == "skipped"

    def test_non_slack_url_rejected(self):
        result = json.loads(send_slack_notification(
            "t", "r", webhook_url="https://evil.com/steal-tokens"
        ))
        assert result["status"] == "error"
        assert "hooks.slack.com" in result["reason"]

    def test_empty_url_returns_skipped(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        result = json.loads(send_slack_notification("t", "r", webhook_url=""))
        assert result["status"] == "skipped"

    def test_env_var_fallback_skipped_when_stub(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/xxx/yyy/zzz")
        result = json.loads(send_slack_notification("t", "r"))
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# post_github_pr_comment — validation
# ---------------------------------------------------------------------------

class TestGitHubPrComment:
    def test_invalid_repo_format_rejected(self):
        result = json.loads(post_github_pr_comment("not-a-repo", 1, "body"))
        assert result["status"] == "error"
        assert "owner/repo" in result["reason"]

    def test_zero_pr_number_rejected(self):
        result = json.loads(post_github_pr_comment("owner/repo", 0, "body"))
        assert result["status"] == "error"

    def test_negative_pr_number_rejected(self):
        result = json.loads(post_github_pr_comment("owner/repo", -5, "body"))
        assert result["status"] == "error"

    def test_no_token_returns_skipped(self):
        result = json.loads(post_github_pr_comment("owner/repo", 42, "body"))
        assert result["status"] == "skipped"
        assert "would_post_to" in result

    def test_oversized_comment_rejected(self):
        result = json.loads(post_github_pr_comment("owner/repo", 1, "x" * 70_000))
        assert result["status"] == "error"
        assert "65,536" in result["reason"]
