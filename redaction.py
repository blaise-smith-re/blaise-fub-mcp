"""Data-minimization helpers: reject and redact sensitive content before it can
reach a FUB write, a log line, or an error message.

Never store or log: passwords/auth secrets, Social Security numbers, account
numbers, wire instructions, TrustFunds secret words, or other confidential
financial credentials. This module is the single choke point for that rule.
"""

from __future__ import annotations

import re

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SSN_LABELED_RE = re.compile(r"\bsocial\s*security\b", re.IGNORECASE)
# Bare "SSN"/"S.S.N." mention, with or without a delimited number nearby.
# Flagged on its own (no digits required) since the abbreviation alone is
# enough signal in a real-estate CRM note to warrant human rewording.
_SSN_ABBR_RE = re.compile(r"\bs\.?s\.?n\.?\b", re.IGNORECASE)
_ACCOUNT_RE = re.compile(r"\b(account|acct)\.?\s*(number|#|no\.?)\b.{0,20}?\d{4,}", re.IGNORECASE | re.DOTALL)
_ROUTING_RE = re.compile(r"\brouting\s*(number|#|no\.?)\b", re.IGNORECASE)
_WIRE_RE = re.compile(r"\bwire\s*(instructions?|transfer\s*instructions?)\b", re.IGNORECASE)
_SWIFT_IBAN_RE = re.compile(r"\b(swift\s*code|iban)\b", re.IGNORECASE)
_TRUSTFUNDS_SECRET_RE = re.compile(
    r"\btrustfunds\b.{0,40}?\bsecret\s*word\b|\bsecret\s*word\b.{0,40}?\btrustfunds\b",
    re.IGNORECASE | re.DOTALL,
)
_PASSWORD_RE = re.compile(
    r"\b(password|passcode|pass\s*code|api\s*key|secret\s*key|pin\s*(code|number)?)\b\s*(is|:|=)",
    re.IGNORECASE,
)

_ALL_PATTERNS: dict[str, re.Pattern[str]] = {
    "ssn": _SSN_RE,
    "ssn_labeled": _SSN_LABELED_RE,
    "ssn_abbreviation": _SSN_ABBR_RE,
    "account_number": _ACCOUNT_RE,
    "routing_number": _ROUTING_RE,
    "wire_instructions": _WIRE_RE,
    "swift_or_iban": _SWIFT_IBAN_RE,
    "trustfunds_secret_word": _TRUSTFUNDS_SECRET_RE,
    "password_or_credential": _PASSWORD_RE,
}


def scan_sensitive(text: str | None) -> list[str]:
    """Return the sorted category names of sensitive-data patterns found in text."""
    if not text:
        return []
    hits = [label for label, pattern in _ALL_PATTERNS.items() if pattern.search(text)]
    return sorted(set(hits))


def assert_no_sensitive_data(*texts: str | None, field_label: str = "text") -> None:
    """Raise ValueError if any provided text appears to contain sensitive data.

    The exception message never echoes the matched text itself, only the
    category names, so a rejection cannot leak the secret it caught.
    """
    categories: set[str] = set()
    for text in texts:
        categories.update(scan_sensitive(text))
    if categories:
        raise ValueError(
            f"Rejected: {field_label} appears to contain sensitive data "
            f"({', '.join(sorted(categories))}). Do not place passwords, SSNs, "
            "account/routing numbers, wire instructions, or TrustFunds secret "
            "words in Follow Up Boss."
        )


def redact_for_log(text: str | None) -> str:
    """Best-effort redaction of sensitive spans for any text that must be logged."""
    if not text:
        return ""
    redacted = text
    for pattern in (_SSN_RE, _ACCOUNT_RE, _ROUTING_RE):
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
