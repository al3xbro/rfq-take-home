"""Cheap, deterministic prompt-injection detector.

This is belt-and-braces only. The real defence is structural: instructions live in
the system prompt, email content goes in the user turn wrapped in
<untrusted_email_content>, and the prompt tells the model that anything inside
those tags is data. This detector never changes the extraction — it only raises a
warning so a human knows the email tried something.
"""
from __future__ import annotations

import re

_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)",
    r"disregard\s+(?:the\s+)?(?:message|instructions?|above|previous|any)",
    r"system\s+instruction",
    r"</?(?:system|instruction)s?>",
    r"you\s+are\s+now\s+",
    r"do\s+not\s+mention\s+(?:this|that)",
    r"respond\s+with\s+\{",
    r"new\s+instructions?:",
    r"override\s+(?:your|the)\s+",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

WARNING = (
    "possible prompt injection: the source contains text styled as an instruction "
    "to the extraction system. It was ignored and the content extracted normally — "
    "review this email before trusting it."
)


def detect_injection(text: str) -> list[str]:
    for pattern in _COMPILED:
        if pattern.search(text):
            return [WARNING]
    return []
