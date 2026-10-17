"""Normalisation, issue construction and status helpers shared by all checks."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

from ...schemas import Issue

ERROR_CODES = {
    "MISSING_RECIPIENT", "UNEXPECTED_PAGE", "DUPLICATE_OUTPUT_RECORD", "FIELD_MISMATCH",
    "FIXED_TEXT_MISMATCH", "NAME_OVERFLOW", "CONTENT_OUTSIDE_PAGE", "ESSENTIAL_ELEMENT_OVERLAP",
    "UNSUPPORTED_GLYPH", "ASSET_LOAD_FAILURE", "PAGE_COUNT_MISMATCH", "HANDWRITING_AREA_OBSTRUCTED",
    "STALE_RECIPIENT_IN_BLANK_OUTPUT", "MISSING_SOURCE_VALUE", "CONFLICTING_RECIPIENT_ID",
}
WARNING_CODES = {"DUPLICATE_SOURCE_ROW", "AMBIGUOUS_PAGE_MATCH", "PDF_EXTRACTION_UNRELIABLE", "NAME_FONT_ADJUSTED"}

NEXT_ACTION = {
    "MISSING_RECIPIENT": "Add a certificate for this recipient or remove the row from the source.",
    "UNEXPECTED_PAGE": "Check whether this page belongs in the batch; remove it or add the recipient to the source.",
    "DUPLICATE_OUTPUT_RECORD": "This recipient appears on more than one page. Remove the repeated page or correct its name.",
    "FIELD_MISMATCH": "Compare the extracted text with the source value and fix whichever is wrong.",
    "FIXED_TEXT_MISMATCH": "The fixed text on the page differs from the confirmed event details. Correct the certificate or the confirmed details.",
    "NAME_OVERFLOW": "Shorten the name, allow two lines in the design, or widen the name area.",
    "CONTENT_OUTSIDE_PAGE": "Move or resize the element so it stays inside the page.",
    "ESSENTIAL_ELEMENT_OVERLAP": "Edit the design so these elements no longer overlap.",
    "UNSUPPORTED_GLYPH": "These characters are not in the bundled fonts. Choose another font or edit the text; names are never transliterated automatically.",
    "ASSET_LOAD_FAILURE": "Re-upload the image or reinstall the bundled fonts.",
    "PAGE_COUNT_MISMATCH": "Regenerate the batch; the PDF page count does not match the request.",
    "HANDWRITING_AREA_OBSTRUCTED": "Reduce the writing-area size or change the design so nothing enters the reserved area.",
    "STALE_RECIPIENT_IN_BLANK_OUTPUT": "Text was found in the area that must be blank. Do not print this file; regenerate it.",
    "MISSING_SOURCE_VALUE": "Fill in the missing value in the source, or remove the row.",
    "CONFLICTING_RECIPIENT_ID": "The same recipient ID is used for different names. Fix the IDs in the source.",
    "DUPLICATE_SOURCE_ROW": "Identical rows appear more than once. Remove duplicates if unintended.",
    "AMBIGUOUS_PAGE_MATCH": "Several source rows fit this page. Pick the right row manually.",
    "PDF_EXTRACTION_UNRELIABLE": "Text could not be read reliably from this page. Check it by eye or mark the field area manually.",
    "NAME_FONT_ADJUSTED": "The name was shrunk to fit. Acknowledge if the size is acceptable.",
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def norm_cmp(s: Optional[str]) -> str:
    """Comparison form: NFC, non-breaking spaces and line-wrap whitespace only.
    Case, punctuation and diacritics are preserved."""
    s = nfc(s or "").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def squash(s: Optional[str]) -> str:
    """Whitespace-free form, used only for fixed-text containment checks."""
    return re.sub(r"\s+", "", norm_cmp(s))


def make_issue(code: str, *, page=None, row_id=None, row_index=None, field=None, expected=None,
               actual=None, rect=None, message="", candidates=None, severity=None) -> Issue:
    sev = severity or ("error" if code in ERROR_CODES else "warning" if code in WARNING_CODES else "info")
    key = "|".join(str(x) for x in (code, page, row_id, field, expected, actual))
    return Issue(
        id=hashlib.sha1(key.encode("utf-8")).hexdigest()[:12], code=code, severity=sev, page=page,
        row_id=row_id, source_row_index=row_index, field=field, expected=expected, actual=actual,
        rect=rect, message=message or code.replace("_", " ").capitalize(),
        next_action=NEXT_ACTION.get(code, ""), candidates=candidates or [],
    )


def apply_acknowledgements(issues: list[Issue], acks: dict[str, str]) -> None:
    for i in issues:
        if i.severity == "warning" and i.id in acks:
            i.acknowledged, i.ack_note = True, acks[i.id]


def completion_state(issues: list[Issue]) -> str:
    if any(i.severity == "error" for i in issues):
        return "blocked"
    if any(i.severity == "warning" and not i.acknowledged for i in issues):
        return "needs_review"
    return "checked"


def status_for(issues: list[Issue]) -> str:
    if any(i.severity == "error" for i in issues):
        return "Blocked"
    if any(i.severity == "warning" and not i.acknowledged for i in issues):
        return "Needs review"
    return "Checked"
