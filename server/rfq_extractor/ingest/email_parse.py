"""Parse raw .eml bytes into a SourceDoc.

Uses the stdlib `email` package with `policy.default`, which handles the
transfer-encoding and charset decoding the samples need (base64 attachments,
8bit bodies) without extra dependencies.
"""
from __future__ import annotations

import email
import re
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from .source import SourceDoc, SourcePart

_INTERESTING_HEADERS = ("From", "To", "Subject", "Date", "Message-ID", "Reply-To", "Cc")
_TAG_RE = re.compile(r"<[^>]+>")


class EmailParseError(ValueError):
    """Raised when the bytes are not a usable email at all."""


def parse_email(raw: bytes) -> SourceDoc:
    if not raw or not raw.strip():
        raise EmailParseError("empty request body")

    try:
        msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)
    except Exception as exc:  # noqa: BLE001 - surface any MIME failure uniformly
        raise EmailParseError(f"could not parse MIME message: {exc}") from exc

    headers = {h: str(msg[h]) for h in _INTERESTING_HEADERS if msg[h] is not None}

    # A bare blob of text with no headers at all is almost certainly not an email.
    if not headers and not msg.get_payload():
        raise EmailParseError("no email headers and no payload found")

    if msg["Date"]:
        try:
            headers["_sent_date_iso"] = parsedate_to_datetime(msg["Date"]).date().isoformat()
        except (TypeError, ValueError):
            pass  # Unparseable Date is not fatal; relative dates just lose their anchor.

    body_text, parts = _walk(msg)
    return SourceDoc(headers=headers, body_text=body_text.strip(), parts=parts)


def _walk(msg: EmailMessage) -> tuple[str, list[SourcePart]]:
    """Split the MIME tree into a plain-text body and a list of content parts."""
    body_chunks: list[str] = []
    parts: list[SourcePart] = []
    html_fallback: list[str] = []

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue

        mime = part.get_content_type()
        filename = part.get_filename() or ""
        disposition = (part.get_content_disposition() or "").lower()
        is_attachment = disposition == "attachment" or bool(filename)

        if mime == "text/plain" and not is_attachment:
            body_chunks.append(_safe_text(part))
            continue

        if mime == "text/html" and not is_attachment:
            html_fallback.append(_strip_html(_safe_text(part)))
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        parts.append(
            SourcePart(
                filename=filename or f"inline.{mime.split('/')[-1]}",
                mime=mime,
                payload=payload,
            )
        )

    body = "\n".join(c for c in body_chunks if c)
    # Only fall back to HTML when there was no plain-text alternative at all.
    if not body.strip() and html_fallback:
        body = "\n".join(html_fallback)
    return body, parts


def _safe_text(part) -> str:
    try:
        return part.get_content()
    except Exception:  # noqa: BLE001 - fall back to raw decode on odd charsets
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text)
