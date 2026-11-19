"""Redact secrets and personal data before any telemetry is sent to the model."""
import re

PATTERNS = [
    (re.compile(r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9]{8,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[REDACTED_JWT]"),
]


def redact(text: str) -> str:
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text
