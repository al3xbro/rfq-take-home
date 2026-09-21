"""Flatten attachments into text blocks (and images) a model can read.

PDF strategy is a three-tier ladder, best-first:
  1. pymupdf4llm Markdown  — keeps table structure, which is what real RFQ PDFs carry
  2. plain PyMuPDF get_text — cheaper, and on simple layouts it preserves line breaks better
  3. rasterise to PNG      — the no-text-layer case; hand it to vision

Every fallback and every failure produces a warning rather than silent data loss.
"""
from __future__ import annotations

import logging

from ..config import MAX_ATTACHMENT_CHARS
from .source import RenderedSource, SourceDoc, SourcePart

log = logging.getLogger(__name__)

# Below this many characters we treat a text extraction as having failed.
_MIN_USEFUL_CHARS = 20
_RASTER_DPI = 150
# A page whose embedded images cover at least this share of it is carrying real
# content (a screenshotted table, a pasted scan), not decoration. Logos, headers
# and signatures sit well under 5%; a pasted parts table is typically 30%+.
_IMAGE_AREA_THRESHOLD = 0.10


def render_source(doc: SourceDoc) -> RenderedSource:
    out = RenderedSource()

    header_lines = [
        f"{k}: {v}" for k, v in doc.headers.items() if not k.startswith("_")
    ]
    out.text_blocks.append("--- EMAIL HEADERS ---\n" + "\n".join(header_lines))
    out.text_blocks.append("--- EMAIL BODY ---\n" + (doc.body_text or "(empty body)"))

    for part in doc.parts:
        try:
            _render_part(part, out)
        except Exception as exc:  # noqa: BLE001 - one bad attachment must not sink the email
            log.exception("attachment render failed: %s", part.filename)
            out.warnings.append(
                f"unsupported attachment: could not read {part.filename!r} ({type(exc).__name__})"
            )
    return out


def _render_part(part: SourcePart, out: RenderedSource) -> None:
    kind = part.kind

    if kind in ("csv", "text"):
        text = part.payload.decode("utf-8", errors="replace")
        out.text_blocks.append(
            _label(part, f"({kind.upper()} attachment, verbatim)") + _clip(text, out, part)
        )
        return

    if kind == "image":
        out.images.append((part.payload, part.mime))
        out.text_blocks.append(
            _label(part, "(image attachment — content supplied to the model as an image)")
        )
        return

    if kind == "pdf":
        _render_pdf(part, out)
        return

    out.warnings.append(
        f"unsupported attachment: {part.filename!r} of type {part.mime} was not read"
    )


def _render_pdf(part: SourcePart, out: RenderedSource) -> None:
    import pymupdf

    doc = pymupdf.open(stream=part.payload, filetype="pdf")
    try:
        text = _pdf_markdown(doc)
        tier = "markdown"

        if len(text.strip()) < _MIN_USEFUL_CHARS:
            text = "\n".join(page.get_text() for page in doc)
            tier = "plain-text"

        if len(text.strip()) < _MIN_USEFUL_CHARS:
            # No usable text layer: this is a scan. Rasterise for the vision model.
            for page in doc:
                png = page.get_pixmap(dpi=_RASTER_DPI).tobytes("png")
                out.images.append((png, "image/png"))
            out.text_blocks.append(
                _label(part, "(PDF had no text layer — pages supplied to the model as images)")
            )
            out.warnings.append(
                f"{part.filename!r} has no extractable text layer; read as a scanned image"
            )
            return

        if tier != "markdown":
            out.warnings.append(
                f"{part.filename!r}: table-aware extraction returned nothing, "
                "fell back to plain text extraction"
            )
        out.text_blocks.append(
            _label(part, f"(PDF attachment, extracted as {tier})") + _clip(text, out, part)
        )

        # A text layer does NOT mean the text is all of it. A PDF whose body says
        # "quote the table below" above a pasted screenshot of that table extracts
        # cleanly and loses everything that mattered. Pages carrying substantial
        # image content are also rasterised, so the text and the picture both reach
        # the model rather than the text silently winning.
        _attach_image_heavy_pages(part, doc, out)
    finally:
        doc.close()


def _attach_image_heavy_pages(part: SourcePart, doc, out: RenderedSource) -> None:
    """Rasterise pages whose embedded images cover a meaningful share of the page."""
    pages: list[int] = []
    for page in doc:
        try:
            page_area = abs(page.rect.get_area())
            if not page_area:
                continue
            covered = 0.0
            for info in page.get_images(full=True):
                for rect in page.get_image_rects(info[0]):
                    covered += abs(rect.get_area())
            if covered / page_area >= _IMAGE_AREA_THRESHOLD:
                out.images.append((page.get_pixmap(dpi=_RASTER_DPI).tobytes("png"), "image/png"))
                pages.append(page.number + 1)
        except Exception as exc:  # noqa: BLE001 - never let this sink a readable PDF
            log.warning("image-area scan failed on a page of %s: %s", part.filename, exc)
    if pages:
        listed = ", ".join(str(n) for n in pages)
        out.text_blocks.append(
            _label(part, f"(page(s) {listed} also contain images — supplied to the model as images)")
        )
        out.warnings.append(
            f"{part.filename!r}: page(s) {listed} contain embedded images alongside text; "
            "both were read. Check that nothing in the images was missed."
        )


def _pdf_markdown(doc) -> str:
    try:
        import pymupdf4llm

        return pymupdf4llm.to_markdown(doc, show_progress=False)
    except Exception as exc:  # noqa: BLE001 - degrade to the next tier, never fail the request
        log.warning("pymupdf4llm failed, falling back to get_text: %s", exc)
        return ""


def _label(part: SourcePart, note: str) -> str:
    return f"--- ATTACHMENT: {part.filename} {note} ---\n"


def _clip(text: str, out: RenderedSource, part: SourcePart) -> str:
    if len(text) <= MAX_ATTACHMENT_CHARS:
        return text
    out.warnings.append(
        f"{part.filename!r} was truncated at {MAX_ATTACHMENT_CHARS} characters; "
        "some line items may be missing"
    )
    return text[:MAX_ATTACHMENT_CHARS]
