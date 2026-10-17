"""Reads actual PDF bytes. Independent of the renderer: knows nothing about HTML."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import pdfplumber

from .common import norm_cmp

logging.getLogger("pdfminer").setLevel(logging.ERROR)


class PdfProblem(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Ch:
    t: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float


@dataclass
class ExtractedPage:
    index: int  # 1-based
    width: float
    height: float
    chars: list[Ch] = field(default_factory=list)

    def text_in(self, rect_frac=None) -> str:
        """Text of characters whose centre lies in the fractional rect [x0,y0,x1,y1]."""
        cs = self.chars
        if rect_frac:
            x0, y0, x1, y1 = (rect_frac[0] * self.width, rect_frac[1] * self.height,
                              rect_frac[2] * self.width, rect_frac[3] * self.height)
            cs = [c for c in cs if x0 <= (c.x0 + c.x1) / 2 <= x1 and y0 <= (c.top + c.bottom) / 2 <= y1]
        return _layout(cs)

    @property
    def unreliable(self) -> bool:
        t = "".join(c.t for c in self.chars)
        return "�" in t or "(cid:" in t


def _layout(cs: list[Ch]) -> str:
    if not cs:
        return ""
    cs = sorted(cs, key=lambda c: ((c.top + c.bottom) / 2, c.x0))
    lines: list[list[Ch]] = []
    for c in cs:
        mid = (c.top + c.bottom) / 2
        if lines and abs(mid - sum((x.top + x.bottom) / 2 for x in lines[-1]) / len(lines[-1])) < max(2.0, c.size * 0.5):
            lines[-1].append(c)
        else:
            lines.append([c])
    out = []
    for ln in lines:
        ln.sort(key=lambda c: c.x0)
        s, prev = "", None
        for c in ln:
            if prev is not None and not s.endswith(" ") and c.t != " " and c.x0 - prev.x1 > 0.28 * max(c.size, 1):
                s += " "
            s += c.t
            prev = c
        out.append(s)
    # Join wrapped lines. A line that ends in a hyphen was broken after the hyphen: no space was in the source.
    joined = ""
    for ln in out:
        joined += ln if (not joined or joined.endswith(("-", "\u2010"))) else " " + ln
    return norm_cmp(joined)


def extract_pages(data: bytes, max_pages: int, progress=None, cancel=None) -> list[ExtractedPage]:
    if not data[:5] == b"%PDF-":
        raise PdfProblem("CORRUPT_PDF", "This file is not a PDF (missing %PDF header).")
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as e:  # corrupt / encrypted
        msg = "The PDF is password-protected." if "password" in str(e).lower() or "encrypt" in str(e).lower() \
            else "The PDF is corrupt or could not be opened."
        raise PdfProblem("CORRUPT_PDF", msg) from e
    with pdf:
        n = len(pdf.pages)
        if n == 0:
            raise PdfProblem("CORRUPT_PDF", "The PDF has no pages.")
        if n > max_pages:
            raise PdfProblem("TOO_MANY_PAGES", f"The PDF has {n} pages; the limit is {max_pages}.")
        pages = []
        for i, p in enumerate(pdf.pages):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("cancelled")
            try:
                chars = [Ch(c["text"], c["x0"], c["x1"], c["top"], c["bottom"], c.get("size", 10) or 10) for c in p.chars]
            except Exception as e:
                raise PdfProblem("CORRUPT_PDF", f"Page {i+1} could not be read.") from e
            pages.append(ExtractedPage(i + 1, float(p.width), float(p.height), chars))
            if progress:
                progress(i + 1, n)
        return pages


def require_text_layer(pages: list[ExtractedPage]) -> None:
    if not any(p.chars for p in pages):
        raise PdfProblem(
            "NO_TEXT_LAYER",
            "This PDF has no searchable text (it looks scanned or image-only). OCR is not supported. "
            "Export a searchable PDF from your design tool, or run OCR elsewhere first.",
        )


def pdf_metadata_strings(data: bytes) -> list[str]:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    vals = [str(v) for v in (r.metadata or {}).values()]
    try:
        x = r.xmp_metadata
        if x is not None:
            vals.append(str(x.stream.get_data()) if hasattr(x, "stream") else "")
    except Exception:
        pass
    return vals


def lines_with_boxes(pg: ExtractedPage) -> list[dict]:
    """Text lines with fractional bounding boxes, used for field-zone suggestions."""
    cs = sorted(pg.chars, key=lambda c: ((c.top + c.bottom) / 2, c.x0))
    groups: list[list[Ch]] = []
    for c in cs:
        mid = (c.top + c.bottom) / 2
        if groups and abs(mid - sum((x.top + x.bottom) / 2 for x in groups[-1]) / len(groups[-1])) < max(2.0, c.size * 0.5):
            groups[-1].append(c)
        else:
            groups.append([c])
    out = []
    for g in groups:
        text = _layout(g)
        if not text:
            continue
        x0, x1 = min(c.x0 for c in g), max(c.x1 for c in g)
        t, b = min(c.top for c in g), max(c.bottom for c in g)
        out.append({"text": text, "size": round(max(c.size for c in g), 1),
                    "rect": [max(0, x0 / pg.width), max(0, t / pg.height), min(1, x1 / pg.width), min(1, b / pg.height)]})
    return out
