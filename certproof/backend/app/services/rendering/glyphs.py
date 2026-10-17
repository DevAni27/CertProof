"""Glyph coverage check against the bundled fonts (Chromium would silently substitute)."""
from __future__ import annotations

import unicodedata
from functools import lru_cache

from fontTools.ttLib import TTFont

from ...config import FONT_DIR
from .html import FONT_FACES

_IGNORABLE = {"​", "‌", "‍", "­", "﻿", " ", "\n", "\r", "\t"}


@lru_cache(maxsize=16)
def _cmap(font_key: str) -> frozenset[int]:
    fn = FONT_FACES[font_key][0][0]
    f = TTFont(str(FONT_DIR / fn), lazy=True)
    return frozenset(f.getBestCmap().keys())


def unsupported_chars(text: str, font_key: str) -> list[str]:
    cm = _cmap(font_key)
    bad = []
    for ch in unicodedata.normalize("NFC", text or ""):
        if ch in _IGNORABLE or ord(ch) in cm:
            continue
        if ch not in bad:
            bad.append(ch)
    return bad
