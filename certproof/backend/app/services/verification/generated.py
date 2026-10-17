"""Independent verification of PDFs produced by the generator.

Reads the actual PDF bytes. Expectations come from the immutable export intent,
never from the HTML that was rendered.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from ...schemas import Issue
from ..rendering.layouts import frac, geometry, signatory_rects
from .common import make_issue, norm_cmp, squash
from .pdf_extract import ExtractedPage, extract_pages, pdf_metadata_strings, require_text_layer

PLACEHOLDERS = ["Name", "Recipient", "John Doe", "{{name}}", "{name}", "[Name]", "Your Name"]


def zones_for(name_w: float, name_h: float) -> dict[str, list[float]]:
    g = geometry(name_w, name_h)
    return {"name": frac(g["name"], 1.5), "organisation": frac(g["field_org"], 0.5), "award": frac(g["field_award"], 0.5)}


def fixed_text_zones(n_sig: int, name_w: float, name_h: float) -> dict[str, list[float]]:
    g = geometry(name_w, name_h)
    z = {"organisation": frac(g["org"], 0.5), "certificate type": frac(g["title"], 0.5),
         "preamble": frac(g["preamble"], 0.5), "award wording": frac(g["body"], 0.5)}
    for i, r in enumerate(signatory_rects(n_sig)):
        z[f"signatory {i+1} name"] = frac(r, 0.5)
        z[f"signatory {i+1} title"] = frac(r, 0.5)
    return z


def check_fixed(pg: ExtractedPage, fixed: list[dict], zones: Optional[dict]) -> list[Issue]:
    out = []
    full = squash(pg.text_in())
    for f in fixed:
        want = squash(f["text"])
        rect = (zones or {}).get(f["label"]) if zones else None
        hay = squash(pg.text_in(rect)) if rect else full
        if want and want not in hay:
            out.append(make_issue("FIXED_TEXT_MISMATCH", page=pg.index, field=f["label"], expected=f["text"],
                                  actual=norm_cmp(pg.text_in(rect)) if rect else "(not found on this page)",
                                  rect=rect,
                                  message=f"Page {pg.index}: {f['label']} does not match the confirmed text."))
    return out


def verify_generated(pdf: bytes, intent: dict, max_pages: int) -> tuple[list[Issue], dict]:
    """intent: {mode, fixed:[{label,text}], n_sig, name_w, name_h, pages:[...] | blank:{...}}"""
    pages = extract_pages(pdf, max_pages)
    require_text_layer(pages)
    mode = intent["mode"]
    issues: list[Issue] = []
    z = zones_for(intent["name_w"], intent["name_h"])
    fz = fixed_text_zones(intent["n_sig"], intent["name_w"], intent["name_h"])
    fixed = intent["fixed"]
    expected_count = len(intent["pages"]) if mode == "personalised" else intent["blank"]["copies"]
    if len(pages) != expected_count:
        issues.append(make_issue("PAGE_COUNT_MISMATCH", expected=str(expected_count), actual=str(len(pages)),
                                 message=f"Expected {expected_count} pages but the PDF has {len(pages)}."))
    summary: dict = {"pdf_pages": len(pages), "expected_pages": expected_count, "mode": mode}

    if mode == "blank_name":
        stale = intent.get("stale_strings", [])
        reserved = [("name", z["name"])]
        for fld, key in (("organisation", "organisation"), ("award", "award")):
            pol = intent["blank"]["optional_fields"].get(fld, {"mode": "omit"})
            if pol["mode"] == "handwriting":
                reserved.append((fld, z[key]))
            elif pol["mode"] == "omit":
                reserved.append((fld, z[key]))  # must stay empty too
        for pg in pages:
            for label, rect in reserved:
                t = pg.text_in(rect)
                pol = intent["blank"]["optional_fields"].get(label, {"mode": "omit"}) if label != "name" else None
                if pol and pol["mode"] == "fixed":
                    continue
                if t:
                    issues.append(make_issue("STALE_RECIPIENT_IN_BLANK_OUTPUT" if label == "name" else "HANDWRITING_AREA_OBSTRUCTED",
                                             page=pg.index, field=label, expected="(empty)", actual=t, rect=rect,
                                             message=f"Page {pg.index}: text found in the {label} area, which must stay empty."))
            full_text = pg.text_in()
            sq = squash(full_text)
            for s in stale + PLACEHOLDERS:
                ss = squash(s)
                if not ss:
                    continue
                if s in PLACEHOLDERS:
                    continue  # placeholders only matter inside reserved areas (checked above)
                if ss in sq:
                    issues.append(make_issue("STALE_RECIPIENT_IN_BLANK_OUTPUT", page=pg.index, field="page text",
                                             expected="(no recipient names)", actual=s,
                                             message=f"Page {pg.index}: a recipient-like string appears on a blank certificate."))
            issues += check_fixed(pg, fixed, fz)
        meta = " ".join(pdf_metadata_strings(pdf))
        for s in stale:
            if s and squash(s) in squash(meta):
                issues.append(make_issue("STALE_RECIPIENT_IN_BLANK_OUTPUT", field="metadata", actual=s,
                                         message="A recipient-like string appears in the PDF metadata."))
        summary["recipient_matching"] = "not_applicable"
        return issues, summary

    # personalised ------------------------------------------------------------
    exp = intent["pages"]
    actual_names: list[str] = []
    for i, pg in enumerate(pages):
        actual = norm_cmp(pg.text_in(z["name"]))
        actual_names.append(actual)
        if i >= len(exp):
            issues.append(make_issue("UNEXPECTED_PAGE", page=pg.index, actual=actual,
                                     message=f"Page {pg.index} has no matching entry in the export."))
            continue
        e = exp[i]
        ctx = dict(page=pg.index, row_id=e["row_id"], row_index=e["source_row_index"])
        if pg.unreliable:
            issues.append(make_issue("PDF_EXTRACTION_UNRELIABLE", **ctx, message=f"Page {pg.index}: text extraction looks garbled."))
            continue
        if actual != norm_cmp(e["name"]):
            issues.append(make_issue("FIELD_MISMATCH", **ctx, field="name", expected=e["name"], actual=actual, rect=z["name"],
                                     message=f"Page {pg.index}: recipient name differs from the source (row {e['source_row_index']})."))
        for fld in ("organisation", "award"):
            want, got = norm_cmp(e.get(fld) or ""), norm_cmp(pg.text_in(z[fld]))
            if want != got:
                issues.append(make_issue("FIELD_MISMATCH", **ctx, field=fld, expected=e.get(fld) or "", actual=got, rect=z[fld],
                                         message=f"Page {pg.index}: {fld} differs from the source."))
        issues += [Issue(**{**x.model_dump(), "row_id": e["row_id"], "source_row_index": e["source_row_index"]})
                   for x in check_fixed(pg, fixed, fz)]
    # set-level reconciliation (counts, not order)
    E = Counter(norm_cmp(e["name"]) for e in exp)
    A = Counter(actual_names)
    for i, a in enumerate(actual_names[:len(exp)]):
        if a == norm_cmp(exp[i]["name"]) or not a:
            continue
        if a in E and A[a] > E[a]:
            issues.append(make_issue("DUPLICATE_OUTPUT_RECORD", page=i + 1, row_id=exp[i]["row_id"],
                                     row_index=exp[i]["source_row_index"], field="name", actual=a,
                                     message=f"Page {i+1} repeats '{a}', which is already present elsewhere in the PDF."))
        elif a not in E:
            issues.append(make_issue("UNEXPECTED_PAGE", page=i + 1, field="name", actual=a,
                                     message=f"Page {i+1} shows a name that is not in the source."))
    for e in exp:
        n = norm_cmp(e["name"])
        if A[n] < E[n]:
            A[n] += 1  # each row reported once
            issues.append(make_issue("MISSING_RECIPIENT", row_id=e["row_id"], row_index=e["source_row_index"], field="name",
                                     expected=e["name"], message=f"'{e['name']}' (source row {e['source_row_index']}) does not appear in the PDF."))
    summary["recipient_matching"] = "checked_against_export_manifest"
    return issues, summary
