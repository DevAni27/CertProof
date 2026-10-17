"""Builds the synthetic example files. Everything here is fictional.

External fixture PDFs are produced with ReportLab (NOT with CertProof's renderer), so they
exercise the verifier independently of the normal pipeline.
Run:  .venv\\Scripts\\python.exe examples\\make_fixtures.py
"""
from __future__ import annotations

import csv
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
FONTS = HERE.parent / "backend" / "fonts"
pdfmetrics.registerFont(TTFont("Poppins", str(FONTS / "Poppins-Regular.ttf")))
pdfmetrics.registerFont(TTFont("PoppinsB", str(FONTS / "Poppins-Bold.ttf")))

HEADERS = ["Participant Full Name", "College / University", "Prize Position", "Reg No"]
ROWS = [
    ["Priya Sharma-Iyer", "Greenfield College", "First Place", "001"],
    ["José Ángel Núñez", "Riverside University", "Second Place", "002"],
    ["Zoë O'Brien", "Greenfield College", "Best Design", "003"],
    ["Mohammed Al-Farsi", "Lakeside Institute", "Participant", "004"],
    ["Alexandria Konstantinopoulos-Montgomery", "Riverside University", "Participant", "005"],
    ["Wei Chen", "Greenfield College", "Participant", "006"],
]
DATE = "12 October 2026"
ORG = "Example Tech Club (demo)"


def write_csv(path: Path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        w.writerows(ROWS)


def write_xlsx(path: Path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Winners"
    ws.append(HEADERS)
    for r in ROWS:
        ws.append(r)  # Reg No stays text so leading zeros survive
    ws2 = wb.create_sheet("Notes")
    ws2.append(["This sheet is ignored unless selected"])
    wb.save(path)


def cert_pdf(path: Path, recs: list[dict]):
    """Landscape A4 certificates with a layout unlike CertProof's own."""
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    W, H = landscape(A4)
    for r in recs:
        c.setFillColorRGB(0.1, 0.25, 0.45)
        c.rect(0, H - 40, W, 40, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("PoppinsB", 16)
        c.drawCentredString(W / 2, H - 27, r.get("org_header", ORG))
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.setFont("Poppins", 26)
        c.drawCentredString(W / 2, H - 120, "Certificate of Achievement")
        c.setFont("Poppins", 12)
        c.drawCentredString(W / 2, H - 160, "awarded to")
        c.setFont("PoppinsB", 30)
        c.drawCentredString(W / 2, H - 215, r["name"])
        c.setFont("Poppins", 14)
        c.drawCentredString(W / 2, H - 250, r["college"])
        c.drawCentredString(W / 2, H - 275, r["prize"])
        c.setFont("Poppins", 11)
        c.drawCentredString(W / 2, 110, f"Example Hackathon 2026, {r.get('date', DATE)}")
        c.drawString(90, 60, "A. Example, Faculty Advisor")
        c.showPage()
    c.save()


def rec(i, **over):
    n, col, pr, _ = ROWS[i]
    return {"name": n, "college": col, "prize": pr, **over}


def main():
    out = HERE
    write_csv(out / "recipients_sample.csv")
    write_xlsx(out / "recipients_sample.xlsx")
    cert_pdf(out / "external_clean.pdf", [rec(i) for i in range(6)])
    # Flawed: same page count (6) as the source, but recipients are missing / replaced / altered.
    cert_pdf(out / "external_flawed.pdf", [
        rec(0),                                     # correct
        rec(1, college="Riverside College"),        # wrong organisation
        rec(2, date="12 November 2026"),            # wrong event date
        rec(0),                                     # Priya repeated, replacing Mohammed
        rec(5, name="Wei Chenn"),                   # changed name (typo)
        {"name": "Taylor Unknown", "college": "Nowhere Academy", "prize": "Participant"},  # unexpected; Alexandria missing
    ])
    cert_pdf(out / "external_reordered.pdf", [rec(i) for i in (5, 3, 0, 4, 2, 1)])
    # Image-only (scanned-like) PDF: no text layer
    img = Image.new("RGB", (1240, 877), "white")
    d = ImageDraw.Draw(img)
    d.text((300, 400), "Scanned certificate (image only)", fill="black")
    img.save(out / "external_scanned.pdf", "PDF", resolution=150)
    (out / "external_corrupt.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nthis file is truncated and broken")
    # Brand assets (fictional): a wide logo and a transparent signature scribble
    logo = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(logo)
    d.ellipse((10, 10, 190, 190), fill=(31, 58, 95, 255))
    d.rectangle((210, 70, 590, 130), fill=(200, 150, 62, 255))
    d.text((235, 88), "EXAMPLE TECH CLUB (FICTIONAL)", fill=(255, 255, 255, 255))
    d.polygon([(100, 40), (60, 120), (140, 120)], fill=(255, 255, 255, 255))
    (out / "assets").mkdir(exist_ok=True)
    logo.save(out / "assets" / "logo_fictional.png")
    sig = Image.new("RGBA", (400, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(sig)
    pts = [(10 + x, 70 + 30 * math.sin(x / 18) * math.exp(-x / 300)) for x in range(0, 380, 3)]
    d.line(pts, fill=(20, 20, 80, 255), width=4)
    sig.save(out / "assets" / "signature_fictional.png")
    print("fixtures written to", out)


if __name__ == "__main__":
    main()
