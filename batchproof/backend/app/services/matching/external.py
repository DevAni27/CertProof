"""Association of pages in an externally produced PDF with source rows.

Rules (handoff section 11): exact comparison-name match, secondary fields for
disambiguation, injective assignment, fuzzy similarity only *suggests*.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Optional

from ...schemas import ConfirmedMapping, Issue, SourceRow
from ..verification.common import make_issue, norm_cmp, status_for
from ..verification.generated import check_fixed
from ..verification.pdf_extract import ExtractedPage
from .source import mapped_values, source_issues


@dataclass
class PageAssociation:
    page: int
    row_ids: list[str] = field(default_factory=list)  # candidates
    row_id: Optional[str] = None  # resolved
    method: str = "none"
    evidence: dict = field(default_factory=dict)
    state: str = "unmatched"  # matched | ambiguous | unmatched | unreliable | suggested


def check_external(rows: list[SourceRow], mapping: ConfirmedMapping, pages: list[ExtractedPage],
                   zones: dict[str, list[float]], fixed_texts: list[str],
                   resolutions: Optional[dict[int, str]] = None):
    resolutions = resolutions or {}
    issues: list[Issue] = list(source_issues(rows, mapping, require_name=True))
    recs = {}
    for r in rows:
        v = mapped_values(r, mapping)
        recs[r.row_id] = dict(row=r, name=v["name"], n=norm_cmp(v["name"]), org=norm_cmp(v["organisation"]),
                              award=norm_cmp(v["award"]), rid=norm_cmp(v["recipient_id"]))
    by_name: dict[str, list[str]] = {}
    for rid, d in recs.items():
        if d["n"]:
            by_name.setdefault(d["n"], []).append(rid)

    assoc: dict[int, PageAssociation] = {}
    extracted: dict[int, dict] = {}
    for pg in pages:
        ex = {f: norm_cmp(pg.text_in(zones[f])) for f in ("name", "organisation", "award", "recipient_id") if zones.get(f)}
        extracted[pg.index] = ex
        a = PageAssociation(pg.index)
        assoc[pg.index] = a
        if pg.unreliable or not pg.chars or not ex.get("name"):
            a.state = "unreliable"
            issues.append(make_issue("PDF_EXTRACTION_UNRELIABLE", page=pg.index, rect=zones.get("name"),
                                     message=f"Page {pg.index}: no readable text in the recipient-name area."
                                     if not pg.unreliable else f"Page {pg.index}: extracted text looks garbled."))

    taken: dict[str, int] = {}  # row_id -> page that owns it
    # pass 1/2: exact-name candidates, disambiguate by id then secondary fields
    ambiguous_groups: set[str] = set()
    for pg in pages:
        a = assoc[pg.index]
        if a.state == "unreliable":
            continue
        ex = extracted[pg.index]
        cands = list(by_name.get(ex["name"], []))
        if pg.index in resolutions and resolutions[pg.index] in recs:
            cands, a.method = [resolutions[pg.index]], "manual"
        elif cands:
            if ex.get("recipient_id"):
                idm = [c for c in cands if recs[c]["rid"] == ex["recipient_id"]]
                if len(idm) == 1:
                    cands, a.method = idm, "id"
            if len(cands) > 1:
                sec = cands
                for f, key in (("organisation", "org"), ("award", "award")):
                    if ex.get(f) and mapping.__dict__.get(f):
                        narrowed = [c for c in sec if recs[c][key] == ex[f]]
                        if narrowed:
                            sec = narrowed
                if len(sec) < len(cands):
                    cands, a.method = sec, "name+secondary"
            if len(cands) == 1 and a.method == "none":
                a.method = "name"
        a.row_ids = cands
        if not cands:
            continue
        if len(cands) > 1:
            a.state = "ambiguous"
            ambiguous_groups.add(ex["name"])
            issues.append(make_issue("AMBIGUOUS_PAGE_MATCH", page=pg.index, field="name", actual=ex["name"],
                                     rect=zones.get("name"), candidates=[str(recs[c]["row"].row_index) for c in cands],
                                     message=f"Page {pg.index}: '{ex['name']}' fits source rows "
                                             + ", ".join(str(recs[c]['row'].row_index) for c in cands) + ". Choose the right one."))
            continue
        rid = cands[0]
        if rid in taken:
            a.state = "matched"
            a.row_id = rid
            issues.append(make_issue("DUPLICATE_OUTPUT_RECORD", page=pg.index, row_id=rid, row_index=recs[rid]["row"].row_index,
                                     field="name", actual=ex["name"], rect=zones.get("name"),
                                     message=f"Page {pg.index} repeats '{ex['name']}' (source row {recs[rid]['row'].row_index}), "
                                             f"already used by page {taken[rid]}."))
            a.row_id = None
            a.state = "duplicate"
            continue
        taken[rid] = pg.index
        a.row_id, a.state = rid, "matched"

    # fuzzy suggestions for still-unmatched pages (suggest only; never pass)
    free_rows = [rid for rid, d in recs.items() if rid not in taken and d["n"] and d["n"] not in ambiguous_groups]
    pairs = []
    for pg in pages:
        a = assoc[pg.index]
        if a.state != "unmatched":
            continue
        nm = extracted[pg.index].get("name", "")
        for rid in free_rows:
            ratio = difflib.SequenceMatcher(None, nm.casefold(), recs[rid]["n"].casefold()).ratio()
            if ratio >= 0.75:
                pairs.append((ratio, pg.index, rid))
    used_p, used_r = set(), set()
    for ratio, p, rid in sorted(pairs, reverse=True):
        if p in used_p or rid in used_r:
            continue
        used_p.add(p)
        used_r.add(rid)
        a = assoc[p]
        a.state, a.row_ids, a.method = "suggested", [rid], "fuzzy_suggestion"
        a.evidence = {"similarity": round(ratio, 2)}
        d = recs[rid]
        issues.append(make_issue("FIELD_MISMATCH", page=p, row_id=rid, row_index=d["row"].row_index, field="name",
                                 expected=d["name"], actual=extracted[p]["name"], rect=zones.get("name"),
                                 candidates=[str(d["row"].row_index)],
                                 message=f"Page {p}: name is close to source row {d['row'].row_index} but not identical (not auto-accepted)."))
    for pg in pages:
        a = assoc[pg.index]
        if a.state == "unmatched":
            issues.append(make_issue("UNEXPECTED_PAGE", page=pg.index, field="name", actual=extracted[pg.index].get("name", ""),
                                     rect=zones.get("name"),
                                     message=f"Page {pg.index}: '{extracted[pg.index].get('name','')}' matches no source row."))
    for rid, d in recs.items():
        if rid in taken or rid in used_r or not d["n"] or d["n"] in ambiguous_groups:
            continue
        issues.append(make_issue("MISSING_RECIPIENT", row_id=rid, row_index=d["row"].row_index, field="name",
                                 expected=d["name"], message=f"'{d['name']}' (source row {d['row'].row_index}) has no page in the PDF."))

    # secondary fields + fixed text on matched pages
    fixed = [{"label": f"fixed text {i+1}", "text": t} for i, t in enumerate(fixed_texts) if t.strip()]
    for pg in pages:
        a = assoc[pg.index]
        if a.state == "matched" and a.row_id:
            d = recs[a.row_id]
            for f, key in (("organisation", "org"), ("award", "award")):
                if zones.get(f) and getattr(mapping, f):
                    got = extracted[pg.index].get(f, "")
                    if got != d[key]:
                        issues.append(make_issue("FIELD_MISMATCH", page=pg.index, row_id=a.row_id, row_index=d["row"].row_index,
                                                 field=f, expected=d[key], actual=got, rect=zones.get(f),
                                                 message=f"Page {pg.index}: {f} differs from source row {d['row'].row_index}."))
        if not pg.unreliable and pg.chars:
            for it in check_fixed(pg, fixed, None):
                if a.row_id:
                    it.row_id, it.source_row_index = a.row_id, recs[a.row_id]["row"].row_index
                issues.append(it)
    return issues, assoc, extracted, recs
