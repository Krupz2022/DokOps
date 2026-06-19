from app.services.connectors.teams_connector import _build_payload, TeamsConnector


def test_default_payload_is_adaptive_card():
    payload = _build_payload("post_adaptive_card", "Title", "Body")
    assert payload["type"] == "message"
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert any(b.get("text") == "Body" for b in card["body"])


def test_legacy_payload_is_message_card():
    payload = _build_payload("post_message_legacy", "Title", "Body")
    assert payload["@type"] == "MessageCard"
    assert payload["sections"][0]["activityText"] == "Body"


def test_actions_default_first():
    assert TeamsConnector().actions[0] == "post_adaptive_card"
    assert "post_message_legacy" in TeamsConnector().actions
