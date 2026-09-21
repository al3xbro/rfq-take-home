"""PDFs that carry content as images alongside a text layer.

The failure this guards against: a PDF whose body reads "please quote the table
below" above a pasted screenshot of that table. The text layer extracts cleanly
and passes the usefulness threshold, so the rasterise fallback never fires and the
table — the only part that mattered — is silently dropped. No warning, no images,
a confident-looking result with zero line items.

Text-vs-image is not either/or in real PDFs, so both channels are read.
"""
from __future__ import annotations

import pymupdf
import pytest

from rfq_extractor.ingest.attachments import render_source
from rfq_extractor.ingest.source import SourceDoc, SourcePart


def build_pdf(*, text: str, image_frac: float) -> bytes:
    """A one-page PDF with `text` and an image covering `image_frac` of the page."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 70), text, fontsize=11)
    if image_frac > 0:
        png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 400)).tobytes("png")
        h = page.rect.height * image_frac
        page.insert_image(pymupdf.Rect(0, page.rect.height - h, page.rect.width, page.rect.height),
                          stream=png)
    out = doc.tobytes()
    doc.close()
    return out


def render(pdf: bytes):
    return render_source(
        SourceDoc(headers={"Subject": "t"}, body_text="See attached.",
                  parts=[SourcePart("rfq.pdf", "application/pdf", pdf)])
    )


def test_image_heavy_page_is_also_sent_to_vision():
    """The regression: text extracted fine, but the content was in the picture."""
    r = render(build_pdf(text="Please quote the parts in the table below.", image_frac=0.6))
    assert len(r.images) == 1, "the embedded image must reach the model"
    assert any("embedded images alongside text" in w for w in r.warnings)
    # The text layer is still delivered too — this is additive, not a replacement.
    assert any("quote the parts" in b for b in r.text_blocks)


def test_text_only_pdf_sends_no_images():
    r = render(build_pdf(text="Part: LM358N  Qty: 500\nPart: BC547  Qty: 1000", image_frac=0))
    assert r.images == []
    assert r.warnings == []


def test_small_decorative_image_is_ignored():
    """A logo or signature must not drag every page into the vision channel."""
    r = render(build_pdf(text="Part: LM358N  Qty: 500", image_frac=0.03))
    assert r.images == [], "a 3% image is decoration, not content"


def test_real_sample_pdf_is_unaffected():
    from rfq_extractor.ingest.email_parse import parse_email
    from conftest import SAMPLES

    r = render_source(parse_email((SAMPLES / "rfq-05-pdf-attachment.eml").read_bytes()))
    assert r.images == []
    assert r.warnings == []
    assert "STM32F407VGT6" in r.combined_text()
