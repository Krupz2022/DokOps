import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


# ── send_notifications ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_notifications_no_op_when_empty_config():
    from app.services.notification_service import send_notifications
    # Should not raise and should not call any connector
    await send_notifications({}, "hello")


@pytest.mark.asyncio
async def test_send_notifications_no_op_when_all_disabled():
    from app.services.notification_service import send_notifications
    config = {
        "slack": {"enabled": False, "webhook_url": "https://hooks.slack.com/x"},
        "teams": {"enabled": False, "webhook_url": ""},
    }
    with patch("app.services.connectors.slack_connector.SlackConnector.execute") as mock_exec:
        await send_notifications(config, "hello")
        mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_send_notifications_calls_slack():
    from app.services.notification_service import send_notifications
    config = {"slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/test"}}
    mock_connector = AsyncMock()
    with patch("app.services.notification_service.SlackConnector", return_value=mock_connector):
        await send_notifications(config, "patch done")
    mock_connector.execute.assert_awaited_once_with(
        {"webhook_url": "https://hooks.slack.com/test", "message": "patch done"}, {}
    )


@pytest.mark.asyncio
async def test_send_notifications_calls_teams():
    from app.services.notification_service import send_notifications
    config = {"teams": {"enabled": True, "webhook_url": "https://outlook.office.com/webhook/x"}}
    mock_connector = AsyncMock()
    with patch("app.services.notification_service.TeamsConnector", return_value=mock_connector):
        await send_notifications(config, "patch done")
    mock_connector.execute.assert_awaited_once_with(
        {"webhook_url": "https://outlook.office.com/webhook/x", "message": "patch done"}, {}
    )


@pytest.mark.asyncio
async def test_send_notifications_calls_jira():
    from app.services.notification_service import send_notifications
    config = {
        "jira": {
            "enabled": True,
            "base_url": "https://acme.atlassian.net",
            "project_key": "OPS",
            "issue_type": "Task",
            "email": "ops@acme.com",
            "api_token": "token123",
            "instance_type": "cloud",
        }
    }
    mock_connector = AsyncMock()
    with patch("app.services.notification_service.JiraConnector", return_value=mock_connector):
        await send_notifications(config, "Line 1 title\nBody content")
    call_args = mock_connector.execute.call_args[0][0]
    assert call_args["action"] == "create_issue"
    assert call_args["project_key"] == "OPS"
    assert "Line 1 title" in call_args["summary"]


@pytest.mark.asyncio
async def test_send_notifications_channel_failure_does_not_block_others():
    """A failing Slack connector must not prevent Teams from firing."""
    from app.services.notification_service import send_notifications
    config = {
        "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/bad"},
        "teams": {"enabled": True, "webhook_url": "https://outlook.office.com/webhook/good"},
    }
    bad_slack = AsyncMock(side_effect=Exception("network error"))
    good_teams = AsyncMock()
    with patch("app.services.notification_service.SlackConnector", return_value=bad_slack), \
         patch("app.services.notification_service.TeamsConnector", return_value=good_teams):
        await send_notifications(config, "test message")
    good_teams.execute.assert_awaited_once()


# ── build_patch_summary ───────────────────────────────────────────────────────

def _make_promo(status="done", reboot_minions="[]", patch_scope="security"):
    from datetime import datetime
    from types import SimpleNamespace
    return SimpleNamespace(
        pipeline_id="pipe-1",
        to_stage_id="stage-1",
        patch_scope=patch_scope,
        triggered_by="scheduler",
        status=status,
        completed_at=datetime(2026, 6, 9, 2, 0, 0),
        reboot_minions=reboot_minions,
        failed_minions="[]",
    )


def _make_result(minion_id, status="done", packages_count=3):
    from types import SimpleNamespace
    return SimpleNamespace(
        minion_id=minion_id,
        status=status,
        packages_count=packages_count,
        applied_advisories="[]",
        promotion_id="promo-1",
    )


def test_build_patch_summary_basic_structure():
    from app.services.notification_service import build_patch_summary
    promo = _make_promo()
    results = [
        _make_result("m-1", "done", 4),
        _make_result("m-2", "failed", 0),
    ]
    hostnames = {"m-1": "web-01.acme.com", "m-2": "db-01.acme.com"}
    summary = build_patch_summary(promo, results, hostnames, "prod-pipeline", "prod", auto_reboot=False)

    assert "prod-pipeline" in summary
    assert "prod" in summary
    assert "web-01.acme.com" in summary
    assert "db-01.acme.com" in summary
    assert "✓ done" in summary
    assert "✗ failed" in summary
    assert "2026-06-09" in summary


def test_build_patch_summary_reboot_required_when_auto_reboot_false():
    from app.services.notification_service import build_patch_summary
    import json
    promo = _make_promo(reboot_minions=json.dumps(["m-1"]))
    results = [_make_result("m-1", "done", 2)]
    hostnames = {"m-1": "web-01.acme.com"}
    summary = build_patch_summary(promo, results, hostnames, "p", "s", auto_reboot=False)
    assert "required" in summary


def test_build_patch_summary_reboot_done_when_auto_reboot_true():
    from app.services.notification_service import build_patch_summary
    import json
    promo = _make_promo(reboot_minions=json.dumps(["m-1"]))
    results = [_make_result("m-1", "done", 2)]
    hostnames = {"m-1": "web-01.acme.com"}
    summary = build_patch_summary(promo, results, hostnames, "p", "s", auto_reboot=True)
    assert "done" in summary
    assert "required" not in summary


def test_build_patch_summary_no_reboot_when_not_in_list():
    from app.services.notification_service import build_patch_summary
    promo = _make_promo(reboot_minions="[]")
    results = [_make_result("m-1", "done", 1)]
    hostnames = {"m-1": "web-01.acme.com"}
    summary = build_patch_summary(promo, results, hostnames, "p", "s", auto_reboot=False)
    assert "—" in summary


def test_build_patch_summary_totals():
    from app.services.notification_service import build_patch_summary
    promo = _make_promo()
    results = [
        _make_result("m-1", "done", 4),
        _make_result("m-2", "done", 2),
        _make_result("m-3", "failed", 0),
    ]
    hostnames = {"m-1": "a", "m-2": "b", "m-3": "c"}
    summary = build_patch_summary(promo, results, hostnames, "p", "s", auto_reboot=False)
    assert "6 patches" in summary
    assert "3 systems" in summary
    assert "2 succeeded" in summary
    assert "1 failed" in summary


# ── ai_beautify_message ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_beautify_returns_ai_output():
    from app.services.notification_service import ai_beautify_message
    mock_service = MagicMock()
    mock_service.simple_completion.return_value = "AI polished summary"
    with patch("app.services.notification_service.ai_service", mock_service):
        result = await ai_beautify_message("raw patch data")
    assert result == "AI polished summary"
    mock_service.simple_completion.assert_called_once()
    assert "raw patch data" in mock_service.simple_completion.call_args[0][0]


@pytest.mark.asyncio
async def test_ai_beautify_falls_back_on_error():
    from app.services.notification_service import ai_beautify_message
    mock_service = MagicMock()
    mock_service.simple_completion.side_effect = Exception("AI unavailable")
    with patch("app.services.notification_service.ai_service", mock_service):
        result = await ai_beautify_message("raw patch data")
    assert result == "raw patch data"
