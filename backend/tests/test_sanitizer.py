# backend/tests/test_sanitizer.py
import pytest
from app.services.sanitizer import sanitize_for_llm


def test_redacts_bearer_token():
    raw = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJrdW1hciJ9.abc123"
    result = sanitize_for_llm(raw)
    assert "eyJhbGciOiJSUzI1NiJ9" not in result
    assert "[REDACTED_TOKEN]" in result


def test_redacts_password_in_env_var():
    raw = "DB_PASSWORD=supersecret123 connecting to db"
    result = sanitize_for_llm(raw)
    assert "supersecret123" not in result
    assert "[REDACTED_SECRET]" in result


def test_redacts_aws_key():
    raw = "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE export AWS_ACCESS_KEY_ID=abc"
    result = sanitize_for_llm(raw)
    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert "[REDACTED_AWS]" in result


def test_redacts_ip_address():
    raw = "Error connecting to 192.168.1.100:5432 timeout"
    result = sanitize_for_llm(raw)
    assert "192.168.1.100" not in result
    assert "[REDACTED_IP]" in result


def test_preserves_error_messages():
    raw = "OOMKilled: container exceeded memory limit 512Mi"
    result = sanitize_for_llm(raw)
    assert "OOMKilled" in result
    assert "512Mi" in result


def test_preserves_pod_names():
    raw = "pod api-deployment-7d9f8b-xkqzp restarted 3 times"
    result = sanitize_for_llm(raw)
    assert "api-deployment-7d9f8b-xkqzp" in result


def test_enforces_token_cap():
    raw = "a" * 50000
    result = sanitize_for_llm(raw, token_cap=100)
    assert len(result) <= 400  # 100 tokens * ~4 chars


def test_empty_string_safe():
    result = sanitize_for_llm("")
    assert result == ""


def test_presidio_importable():
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    assert AnalyzerEngine is not None
    assert AnonymizerEngine is not None


def test_sanitize_for_llm_handles_multiline():
    raw = "line 1: normal log\nDB_PASSWORD=hunter2\nline 3: OOMKilled"
    result = sanitize_for_llm(raw)
    assert "hunter2" not in result
    assert "OOMKilled" in result
    assert "line 1: normal log" in result
