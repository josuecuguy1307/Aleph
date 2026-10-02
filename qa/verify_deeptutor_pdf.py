#!/usr/bin/env python3
"""Mini-vara: the imported tutor still reads and renders a PDF without PyMuPDF."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "deeptutor"))

import pypdfium2 as pdfium  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from deeptutor.utils.document_extractor import extract_text_from_bytes  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="aleph-educacion-pdf-") as tmp:
        source = Path(tmp) / "lesson.pdf"
        pdf = canvas.Canvas(str(source))
        pdf.drawString(72, 720, "Aleph education PDF witness")
        pdf.showPage()
        pdf.save()
        raw = source.read_bytes()

    extracted = extract_text_from_bytes("lesson.pdf", raw)
    assert "Aleph education PDF witness" in extracted, extracted

    document = pdfium.PdfDocument(raw)
    assert len(document) == 1, len(document)
    bitmap = document[0].render(scale=1)
    assert bitmap.width > 0 and bitmap.height > 0, (bitmap.width, bitmap.height)
    print("PASS PDF: text extraction + one rendered bitmap; PyMuPDF absent")


if __name__ == "__main__":
    main()
