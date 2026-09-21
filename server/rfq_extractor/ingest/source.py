"""Intermediate representations between a raw .eml and the model prompt."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourcePart:
    """One MIME part carrying content we may need to read."""

    filename: str
    mime: str
    payload: bytes

    @property
    def kind(self) -> str:
        if self.mime == "text/csv" or self.filename.lower().endswith(".csv"):
            return "csv"
        if self.mime == "application/pdf" or self.filename.lower().endswith(".pdf"):
            return "pdf"
        if self.mime.startswith("image/"):
            return "image"
        if self.mime.startswith("text/"):
            return "text"
        return "unsupported"


@dataclass
class SourceDoc:
    """A parsed email: headers, body, and whatever came attached."""

    headers: dict[str, str] = field(default_factory=dict)
    body_text: str = ""
    parts: list[SourcePart] = field(default_factory=list)

    @property
    def sent_date(self) -> str | None:
        """ISO date the mail was sent — the anchor for relative dates like 'by Aug 15'."""
        return self.headers.get("_sent_date_iso")


@dataclass
class RenderedSource:
    """Everything from the email, flattened into what we can hand a model."""

    text_blocks: list[str] = field(default_factory=list)
    images: list[tuple[bytes, str]] = field(default_factory=list)  # (data, media_type)
    warnings: list[str] = field(default_factory=list)

    def combined_text(self) -> str:
        return "\n\n".join(self.text_blocks)
