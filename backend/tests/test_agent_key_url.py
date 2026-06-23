import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "minion"))
import agent  # noqa: E402


def test_build_ws_url_appends_key():
    url = agent.build_ws_url("http://localhost:8000", "mid", "TOK", "KEYVAL")
    assert url.startswith("ws://localhost:8000/api/v1/minions/ws/mid?token=TOK")
    assert "&key=KEYVAL" in url


def test_build_ws_url_without_key():
    url = agent.build_ws_url("http://localhost:8000", "mid", "TOK", "")
    assert url == "ws://localhost:8000/api/v1/minions/ws/mid?token=TOK"
