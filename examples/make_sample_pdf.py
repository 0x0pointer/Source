#!/usr/bin/env python3
"""Optional: write a plain sample PDF into the vault to demonstrate PDF indexing.

The indexer can read PDFs too — build with `--ext .md,.txt,.pdf`. This script just
drops one ordinary text PDF into ../source/ so you have something to try it on:

    .venv/bin/pip install reportlab          # only needed for this demo
    .venv/bin/python examples/make_sample_pdf.py
    .venv/bin/python build_index.py --ext .md,.txt,.pdf
    .venv/bin/python query.py "sample pdf"

Nothing here is special — it's a normal PDF with normal text. Delete it (and this
script) once you've confirmed PDF ingestion works.
"""
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "source" / "sample-note.pdf"

PARAGRAPHS = [
    "Sample Reference Note",
    "",
    "This is an ordinary PDF indexed alongside the Markdown notes. It exists only to show that "
    "PDFs are searchable when you build with --ext .md,.txt,.pdf. Each page is read as text and "
    "chunked the same way a Markdown section is.",
    "",
    "Put real reference PDFs (exported runbooks, vendor docs, spec sheets) in the vault and they "
    "become part of the same search index as your notes.",
]


def main():
    c = canvas.Canvas(str(OUT), pagesize=letter)
    width, height = letter
    y = height - inch
    c.setFont("Helvetica", 12)
    for line in PARAGRAPHS:
        for wrapped in _wrap(line, 90):
            if y < inch:
                c.showPage(); c.setFont("Helvetica", 12); y = height - inch
            c.drawString(inch, y, wrapped); y -= 16
    c.save()
    print(f"wrote {OUT}")


def _wrap(text, width):
    if not text:
        return [""]
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line); line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    main()
