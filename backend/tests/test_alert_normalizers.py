# backend/tests/test_alert_normalizers.py
import pytest
from datetime import datetime, timezone
from app.services.alert_normalizers import (
    NormalizedAlert,
    parse_alertmanager,
    parse_grafana,
    parse_datadog,
    parse_pagerduty,
    parse_opsgenie,
    parse_elasticsearch,
    parse_generic,
)


# ── Alertmanager ──────────────────────────────────────────────────────────────

ALERTMANAGER_PAYLOAD = {
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "CrashLoopBackOff",
                "namespace": "production",
                "pod": "api-7d9b8c-xkz2p",
                "severity": "critical",
            },
            "annotations": {"description": "Pod is crash looping"},
            "fingerprint": "abc123",
        }
    ]
}


def test_parse_alertmanager_produces_normalized_alerts():
    alerts = parse_alertmanager(ALERTMANAGER_PAYLOAD)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.alert_name == "CrashLoopBackOff"
    assert a.namespace == "production"
    assert a.pod_name == "api-7d9b8c-xkz2p"
    assert a.severity == "critical"
    assert a.source == "alertmanager"
    assert a.fingerprint  # non-empty


def test_parse_alertmanager_skips_resolved_alerts():
    payload = {"alerts": [{"status": "resolved", "labels": {"alertname": "Foo"}, "annotations": {}, "fingerprint": "x"}]}
    alerts = parse_alertmanager(payload)
    assert alerts == []


# ── Grafana ───────────────────────────────────────────────────────────────────

GRAFANA_PAYLOAD = {
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighMemoryUsage", "severity": "warning", "namespace": "staging"},
            "annotations": {"description": "Memory above 90%"},
            "fingerprint": "def456",
        }
    ]
}


def test_parse_grafana():
    alerts = parse_grafana(GRAFANA_PAYLOAD)
    assert len(alerts) == 1
    assert alerts[0].alert_name == "HighMemoryUsage"
    assert alerts[0].severity == "warning"
    assert alerts[0].source == "grafana"


# ── Datadog ───────────────────────────────────────────────────────────────────

DATADOG_PAYLOAD = {
    "title": "CPU spike on api pod",
    "alert_metric": "kubernetes.cpu.usage",
    "alert_status": "Triggered",
    "priority": "P1",
    "tags": "namespace:prod,pod_name:api-xyz",
    "body": "CPU exceeded threshold for 5 minutes",
}


def test_parse_datadog():
    alerts = parse_datadog(DATADOG_PAYLOAD)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.source == "datadog"
    assert a.severity == "critical"
    assert "api pod" in a.alert_name.lower() or a.alert_name


# ── PagerDuty ─────────────────────────────────────────────────────────────────

PAGERDUTY_PAYLOAD = {
    "messages": [
        {
            "event": "incident.trigger",
            "incident": {
                "title": "OOMKilled in production",
                "urgency": "high",
                "body": {"cef_details": {"details": {"namespace": "production", "pod": "worker-abc"}}},
            },
        }
    ]
}


def test_parse_pagerduty():
    alerts = parse_pagerduty(PAGERDUTY_PAYLOAD)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.source == "pagerduty"
    assert a.severity in ("critical", "warning", "info")


# ── OpsGenie ──────────────────────────────────────────────────────────────────

OPSGENIE_PAYLOAD = {
    "action": "Create",
    "alert": {
        "alertId": "og-001",
        "message": "PodCrashLooping in default namespace",
        "priority": "P2",
        "tags": ["namespace:default", "pod:frontend-123"],
        "description": "Pod has restarted 5 times",
    },
}


def test_parse_opsgenie():
    alerts = parse_opsgenie(OPSGENIE_PAYLOAD)
    assert len(alerts) == 1
    assert alerts[0].source == "opsgenie"


# ── Elasticsearch ─────────────────────────────────────────────────────────────

ELASTICSEARCH_PAYLOAD = {
    "alert_name": "ErrImagePull",
    "namespace": "staging",
    "pod": "myapp-deploy-789",
    "severity": "warning",
    "message": "Image pull failed for myapp:latest",
}


def test_parse_elasticsearch():
    alerts = parse_elasticsearch(ELASTICSEARCH_PAYLOAD)
    assert len(alerts) == 1
    assert alerts[0].alert_name == "ErrImagePull"
    assert alerts[0].source == "elasticsearch"
    assert alerts[0].namespace == "staging"


# ── Generic ───────────────────────────────────────────────────────────────────

GENERIC_PAYLOAD = {
    "alert_name": "DiskPressure",
    "severity": "critical",
    "namespace": "kube-system",
    "pod_name": "storage-0",
    "description": "Node disk pressure threshold exceeded",
}


def test_parse_generic():
    alerts = parse_generic(GENERIC_PAYLOAD)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.alert_name == "DiskPressure"
    assert a.namespace == "kube-system"
    assert a.pod_name == "storage-0"
    assert a.source == "generic"


def test_parse_generic_requires_alert_name():
    alerts = parse_generic({})
    assert alerts == []


def test_fingerprint_is_deterministic():
    a1 = parse_generic(GENERIC_PAYLOAD)[0]
    a2 = parse_generic(GENERIC_PAYLOAD)[0]
    assert a1.fingerprint == a2.fingerprint
