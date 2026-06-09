# backend/app/services/alert_normalizers.py
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel


class NormalizedAlert(BaseModel):
    fingerprint: str
    source: str
    severity: str
    alert_name: str
    description: str
    namespace: Optional[str] = None
    pod_name: Optional[str] = None
    cluster_name: Optional[str] = None  # resolved at ingestion time; None = auto-resolve
    labels: Dict[str, str] = {}
    raw_payload: Dict = {}
    received_at: datetime = None

    def model_post_init(self, __context):
        if self.received_at is None:
            object.__setattr__(self, "received_at", datetime.now(timezone.utc))


def _fingerprint(alert_name: str, labels: Dict[str, str]) -> str:
    key = alert_name + "|" + "|".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _priority_to_severity(priority: str) -> str:
    p = (priority or "").upper()
    if p in ("P1", "CRITICAL", "HIGH", "TRIGGERED"):
        return "critical"
    if p in ("P2", "P3", "WARNING", "MEDIUM"):
        return "warning"
    return "info"


def _extract_tag_value(tags: list, key: str) -> Optional[str]:
    """Extract value from tags like ['namespace:prod', 'pod_name:api']."""
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(f"{key}:"):
            return tag.split(":", 1)[1]
    return None


def parse_alertmanager(payload: Dict) -> List[NormalizedAlert]:
    results = []
    for alert in payload.get("alerts", []):
        if alert.get("status") == "resolved":
            continue
        labels = alert.get("labels", {})
        alert_name = labels.get("alertname", "UnknownAlert")
        severity = labels.get("severity", "warning")
        namespace = labels.get("namespace") or labels.get("exported_namespace")
        pod_name = labels.get("pod") or labels.get("pod_name")
        description = alert.get("annotations", {}).get("description", alert_name)
        fp = alert.get("fingerprint") or _fingerprint(alert_name, labels)
        results.append(NormalizedAlert(
            fingerprint=fp,
            source="alertmanager",
            severity=severity,
            alert_name=alert_name,
            description=description,
            namespace=namespace,
            pod_name=pod_name,
            labels=labels,
            raw_payload=alert,
        ))
    return results


def parse_grafana(payload: Dict) -> List[NormalizedAlert]:
    results = []
    for alert in payload.get("alerts", []):
        if alert.get("status") == "resolved":
            continue
        labels = alert.get("labels", {})
        alert_name = labels.get("alertname", payload.get("title", "GrafanaAlert"))
        severity = labels.get("severity", "warning")
        namespace = labels.get("namespace")
        pod_name = labels.get("pod") or labels.get("pod_name")
        description = alert.get("annotations", {}).get("description", alert_name)
        fp = alert.get("fingerprint") or _fingerprint(alert_name, labels)
        results.append(NormalizedAlert(
            fingerprint=fp,
            source="grafana",
            severity=severity,
            alert_name=alert_name,
            description=description,
            namespace=namespace,
            pod_name=pod_name,
            labels=labels,
            raw_payload=alert,
        ))
    return results


def parse_datadog(payload: Dict) -> List[NormalizedAlert]:
    title = payload.get("title", "DatadogAlert")
    priority = payload.get("priority", payload.get("alert_status", "warning"))
    severity = _priority_to_severity(priority)
    tags_raw = payload.get("tags", "")
    tags_list = [t.strip() for t in tags_raw.split(",")] if isinstance(tags_raw, str) else (tags_raw or [])
    namespace = _extract_tag_value(tags_list, "namespace") or _extract_tag_value(tags_list, "kube_namespace")
    pod_name = _extract_tag_value(tags_list, "pod_name") or _extract_tag_value(tags_list, "pod")
    labels = {"source": "datadog", "priority": str(priority)}
    description = payload.get("body", title)
    return [NormalizedAlert(
        fingerprint=_fingerprint(title, labels),
        source="datadog",
        severity=severity,
        alert_name=title,
        description=description,
        namespace=namespace,
        pod_name=pod_name,
        labels=labels,
        raw_payload=payload,
    )]


def parse_pagerduty(payload: Dict) -> List[NormalizedAlert]:
    results = []
    for msg in payload.get("messages", []):
        if msg.get("event") not in ("incident.trigger", "incident.acknowledge"):
            continue
        incident = msg.get("incident", {})
        title = incident.get("title", "PagerDutyIncident")
        urgency = incident.get("urgency", "low")
        severity = "critical" if urgency == "high" else "warning"
        details = incident.get("body", {}).get("cef_details", {}).get("details", {})
        namespace = details.get("namespace")
        pod_name = details.get("pod") or details.get("pod_name")
        labels = {"urgency": urgency}
        results.append(NormalizedAlert(
            fingerprint=_fingerprint(title, labels),
            source="pagerduty",
            severity=severity,
            alert_name=title,
            description=title,
            namespace=namespace,
            pod_name=pod_name,
            labels=labels,
            raw_payload=msg,
        ))
    return results


def parse_opsgenie(payload: Dict) -> List[NormalizedAlert]:
    action = payload.get("action", "")
    if action not in ("Create", "Acknowledge"):
        return []
    alert = payload.get("alert", {})
    message = alert.get("message", "OpsGenieAlert")
    priority = alert.get("priority", "P3")
    severity = _priority_to_severity(priority)
    tags = alert.get("tags", [])
    namespace = _extract_tag_value(tags, "namespace")
    pod_name = _extract_tag_value(tags, "pod") or _extract_tag_value(tags, "pod_name")
    labels = {"priority": priority}
    description = alert.get("description", message)
    return [NormalizedAlert(
        fingerprint=_fingerprint(message, labels),
        source="opsgenie",
        severity=severity,
        alert_name=message,
        description=description,
        namespace=namespace,
        pod_name=pod_name,
        labels=labels,
        raw_payload=payload,
    )]


def parse_elasticsearch(payload: Dict) -> List[NormalizedAlert]:
    alert_name = payload.get("alert_name") or payload.get("rule_name") or payload.get("name", "ElasticAlert")
    severity = payload.get("severity", "warning")
    namespace = payload.get("namespace")
    pod_name = payload.get("pod") or payload.get("pod_name")
    description = payload.get("message") or payload.get("description", alert_name)
    labels = {"severity": severity}
    return [NormalizedAlert(
        fingerprint=_fingerprint(alert_name, labels),
        source="elasticsearch",
        severity=severity,
        alert_name=alert_name,
        description=description,
        namespace=namespace,
        pod_name=pod_name,
        labels=labels,
        raw_payload=payload,
    )]


def parse_generic(payload: Dict) -> List[NormalizedAlert]:
    alert_name = payload.get("alert_name") or payload.get("name")
    if not alert_name:
        return []
    severity = payload.get("severity", "warning")
    namespace = payload.get("namespace")
    pod_name = payload.get("pod_name") or payload.get("pod")
    description = payload.get("description", alert_name)
    labels = {"severity": severity}
    return [NormalizedAlert(
        fingerprint=_fingerprint(alert_name, labels),
        source="generic",
        severity=severity,
        alert_name=alert_name,
        description=description,
        namespace=namespace,
        pod_name=pod_name,
        labels=labels,
        raw_payload=payload,
    )]
