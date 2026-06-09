"""
Log sanitizer — strips PII and secrets before data reaches the LLM.

Layer 1: Microsoft Presidio (NLP-based PII: emails, names, phone numbers)
Layer 2: Regex patterns (secrets, tokens, IPs — things Presidio misses)
Layer 3: Hard token cap to prevent context overflow
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Presidio is loaded lazily — it pulls in spaCy which is heavy (~500ms on first call)
_analyzer = None
_anonymizer = None

# Characters-per-token approximation. Conservative estimate for safety.
_CHARS_PER_TOKEN = 4

SECRET_PATTERNS = [
    # Bearer / JWT tokens
    (r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "[REDACTED_TOKEN]"),
    # Generic env-style secrets: KEY=value or KEY: value
    (
        r"(?i)(password|passwd|secret|api_key|apikey|private_key|token|auth_token)\s*[=:]\s*\S+",
        "[REDACTED_SECRET]",
    ),
    # AWS credentials
    (r"(?i)aws_[a-z_]+=\S+", "[REDACTED_AWS]"),
    # IPv4 addresses (internal network topology)
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[REDACTED_IP]"),
]


def _get_presidio():
    """Lazy-load Presidio engines so startup isn't blocked."""
    global _analyzer, _anonymizer
    if _analyzer is None:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        from presidio_anonymizer import AnonymizerEngine  # type: ignore
        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()
    return _analyzer, _anonymizer


_PRESIDIO_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
]

def _presidio_redact(text: str) -> str:
    """Run Presidio PII detection. Falls back to raw text if Presidio unavailable."""
    try:
        analyzer, anonymizer = _get_presidio()
        results = analyzer.analyze(text=text, language="en", entities=_PRESIDIO_ENTITIES)
        if not results:
            return text
        return anonymizer.anonymize(text=text, analyzer_results=results).text
    except Exception:
        # Never block the log pipeline if Presidio fails
        return text


def sanitize_for_llm(text: str, token_cap: int = 1000) -> str:
    """
    Sanitize raw log/observation text before injecting into LLM context.

    Args:
        text: Raw text from K8s logs, events, or tool output.
        token_cap: Maximum tokens to pass. Default 1000 (~4000 chars).

    Returns:
        Sanitized, truncated string safe to include in LLM prompts.
    """
    if not text:
        return text

    # Layer 1: Regex — handles secrets, tokens, IPs (run first so Presidio can't obscure patterns)
    clean = text
    regex_hits: list[str] = []
    for pattern, replacement in SECRET_PATTERNS:
        new_clean = re.sub(pattern, replacement, clean)
        if new_clean != clean:
            regex_hits.append(replacement)
        clean = new_clean

    # Layer 2: Presidio — handles emails, names, phone numbers, credit cards
    after_presidio = _presidio_redact(clean)
    presidio_hit = after_presidio != clean
    clean = after_presidio

    # Layer 3: Hard token cap
    char_limit = token_cap * _CHARS_PER_TOKEN
    truncated = len(text) > char_limit
    result = clean[:char_limit]

    parts = []
    if regex_hits:
        parts.append(f"regex={regex_hits}")
    if presidio_hit:
        parts.append("presidio=PII_found")
    if truncated:
        parts.append(f"truncated={len(text)}→{char_limit}chars")

    status = ", ".join(parts) if parts else "clean"
    logger.info("sanitizer: in=%dchars out=%dchars [%s]", len(text), len(result), status)

    return result
