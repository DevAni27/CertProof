"""Layout geometry (A4 landscape, millimetres). Shared by renderer and verifier."""
from __future__ import annotations

PAGE_W, PAGE_H = 297.0, 210.0
MM_TO_PT = 72.0 / 25.4
NAME_CY = 100.0

Rect = tuple[float, float, float, float]  # x, y, w, h (mm)


def geometry(name_w: float, name_h: float) -> dict[str, Rect]:
    cx = PAGE_W / 2
    return {
        "logo": (cx - 30, 13, 60, 20),
        "org": (48.5, 35, 200, 8),
        "title": (28, 45, 241, 17),
        "preamble": (48.5, 68, 200, 8),
        "name": (cx - name_w / 2, NAME_CY - name_h / 2, name_w, name_h),
        "field_org": (48.5, 118, 200, 8),
        "field_award": (48.5, 127, 200, 9),
        "body": (40, 139, 217, 20),
    }


def signatory_rects(n: int) -> list[Rect]:
    cx = PAGE_W / 2
    step, w = (85, 70) if n <= 3 else (72, 66)
    return [(cx + (i - (n - 1) / 2) * step - w / 2, 164, w, 30) for i in range(n)]


def frac(rect: Rect, pad_mm: float = 0.0) -> list[float]:
    x, y, w, h = rect
    return [
        max(0.0, (x - pad_mm) / PAGE_W),
        max(0.0, (y - pad_mm) / PAGE_H),
        min(1.0, (x + w + pad_mm) / PAGE_W),
        min(1.0, (y + h + pad_mm) / PAGE_H),
    ]
