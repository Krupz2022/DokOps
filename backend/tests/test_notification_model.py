import pytest
from app.models.notification import Notification


def test_notification_defaults():
    n = Notification(
        user_id=1, conversation_id="conv-1", kind="rollout_watch",
        namespace="dokops-chaos", target="deployment/sample-api",
        message="Rolling out deployment/sample-api…",
    )
    assert n.status == "watching"
    assert n.read is False
    assert n.resolved_at is None
    assert n.created_at is not None
