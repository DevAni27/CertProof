"""Export pipeline: intent snapshot -> pre-checks -> canonical render -> independent PDF checks -> artifacts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import threading
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pypdfium2 as pdfium

from .config import get_settings
from .jobs import JobCtx, JobFailure
from .schemas import ConfirmedMapping, Issue, Project, now_iso
from .services.matching.source import mapped_values, source_issues
from .services.rendering.glyphs import unsupported_chars
from .services.rendering.html import PageData, RenderContext, expected_fixed_texts
from .services.rendering.renderer import Cancelled, chunk_count, render_pdf
from .services.verification.common import (apply_acknowledgements, completion_state, make_issue, norm_cmp, status_for)
from .services.verification.generated import verify_generated
from .services.verification.pdf_extract import PdfProblem
from .storage import (add_artifact, artifact_dir, asset_hashes, get_project, list_artifacts, project_assets, project_dir)

PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
ALLOWED_PLACEHOLDERS = {"{event_name}", "{organisation}", "{event_date}"}
NOTE = ("'Checked' means the implemented checks passed against the confirmed inputs. It does not certify identity, "
        "event truth, authorisation, the spelling supplied by the organiser, or legal validity.")


def unknown_placeholders(text: str) -> list[str]:
    return [m for m in PLACEHOLDER_RE.findall(text or "") if m not in ALLOWED_PLACEHOLDERS]


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:40] or "event"


# ---- intent --------------------------------------------------------------------
def readiness(p: Project) -> list[str]:
    s = get_settings()
    m: list[str] = []
    if p.kind != "generate":
        return ["This is a check-only project; it has no certificate design."]
    if not p.design:
        m.append("Create or confirm a design first.")
    e = p.event
    if not (e.event_name.strip() and e.organisation.strip() and e.event_date.strip()):
        m.append("Confirm the event name, organisation and event date.")
    if p.design:
        bad = unknown_placeholders(e.wording or p.design.body_text)
        if bad:
            m.append("Wording uses unknown placeholders: " + ", ".join(bad))
    if p.output_mode == "personalised":
        if not p.source.rows:
            m.append("Add recipients (manual, paste, or CSV/XLSX).")
        elif not p.mapping or not p.mapping.name:
            m.append("Confirm the column mapping, including the recipient name column.")
        elif not any(norm_cmp(mapped_values(r, p.mapping)["name"]) for r in p.source.rows):
            m.append("No row has a recipient name.")
    else:
        b = p.blank
        if b.copies > s.max_blank_copies:
            m.append(f"At most {s.max_blank_copies} blank copies are supported.")
        if b.confirmed_copies != b.copies:
            m.append(f"Confirm that you want exactly {b.copies} blank certificate(s).")
        if p.mapping:
            for fld in ("organisation", "award"):
                if getattr(p.mapping, fld) and fld not in b.optional_fields:
                    m.append(f"Choose how the per-recipient '{fld}' field is handled in blank mode "
                             "(fixed text, omitted, or handwriting). It is never inherited from a recipient.")
    return m


def build_intent(p: Project) -> Optional[dict]:
    if not p.design:
        return None
    base = {"version": 1, "mode": p.output_mode, "event": p.event.model_dump(), "design": p.design.model_dump(),
            "assets": asset_hashes(p)}
    if p.output_mode == "blank_name":
        base["blank"] = p.blank.model_dump(exclude={"confirmed_copies"})
        base["pages"] = None
        return base
    pages = []
    if p.mapping:
        for r in p.source.rows:
            v = mapped_values(r, p.mapping)
            if norm_cmp(v["name"]):
                pages.append({"page": len(pages) + 1, "row_id": r.row_id, "source_row_index": r.row_index,
                              "name": v["name"].strip(), "organisation": v["organisation"].strip(),
                              "award": v["award"].strip(), "recipient_id": v["recipient_id"].strip()})
    base["pages"] = pages
    base["mapping"] = p.mapping.model_dump(exclude={"confirmed_at", "version"}) if p.mapping else None
    return base


def intent_hash(intent: Optional[dict]) -> Optional[str]:
    if intent is None:
        return None
    return hashlib.sha256(json.dumps(intent, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def current_intent_hash(p: Project) -> Optional[str]:
    return intent_hash(build_intent(p))


def _render_ctx(p: Project, intent: dict, only_row: Optional[str] = None) -> RenderContext:
    if intent["mode"] == "blank_name":
        pages = [PageData() for _ in range(p.blank.copies)]
        return RenderContext(p.design, p.event, pages, blank=p.blank)
    src = intent["pages"]
    if only_row:
        src = [x for x in src if x["row_id"] == only_row] or src[:1]
    return RenderContext(p.design, p.event, [PageData(x["name"], x["organisation"], x["award"], x["row_id"]) for x in src])


def _verify_intent(p: Project, intent: dict, ctx: RenderContext) -> dict:
    spec = p.design
    blank = intent["mode"] == "blank_name"
    return {"mode": intent["mode"], "fixed": expected_fixed_texts(ctx), "n_sig": len(p.event.signatories),
            "name_w": p.blank.width_mm if blank else spec.name_box_width_mm,
            "name_h": p.blank.height_mm if blank else spec.name_box_height_mm,
            "pages": intent["pages"] or [], "blank": intent.get("blank")}


def _glyph_issues(p: Project, intent: dict, ctx: RenderContext) -> list[Issue]:
    sp = p.design
    out = []
    for f in expected_fixed_texts(ctx):
        bad = set(unsupported_chars(f["text"], sp.fonts.heading)) | set(unsupported_chars(f["text"], sp.fonts.body))
        if bad:
            out.append(make_issue("UNSUPPORTED_GLYPH", field=f["label"], actual="".join(sorted(bad)),
                                  message=f"The bundled fonts cannot draw: {' '.join(sorted(bad))} (in {f['label']})."))
    for pg in intent["pages"] or []:
        for fld, font in (("name", sp.fonts.name), ("organisation", sp.fonts.body), ("award", sp.fonts.heading)):
            bad = unsupported_chars(pg[fld], font)
            if bad:
                out.append(make_issue("UNSUPPORTED_GLYPH", page=pg["page"], row_id=pg["row_id"], row_index=pg["source_row_index"],
                                      field=fld, actual="".join(bad),
                                      message=f"Row {pg['source_row_index']}: the selected font cannot draw {' '.join(bad)} in the {fld}."))
    return out


def _render_issues(res, intent: dict) -> list[Issue]:
    out: list[Issue] = []
    pages = intent["pages"] or []

    def row_of(pn):
        return pages[pn - 1] if intent["mode"] == "personalised" and 0 < pn <= len(pages) else None

    for f in res.fits:
        r = row_of(f["page"]) or {}
        kw = dict(page=f["page"], row_id=r.get("row_id"), row_index=r.get("source_row_index"), field="name",
                  expected=r.get("name"))
        if f["overflow"]:
            out.append(make_issue("NAME_OVERFLOW", **kw, message=f"Page {f['page']}: the name does not fit legibly "
                                                                  f"(minimum size {f['size']:.1f} pt reached)."))
        elif f["adjusted"]:
            out.append(make_issue("NAME_FONT_ADJUSTED", **kw,
                                  message=f"Page {f['page']}: name shrunk to {f['size']:.1f} pt"
                                          + (f" on {f['lines']} lines" if f["lines"] > 1 else "") + " to fit."))
    groups: dict = defaultdict(list)
    for g in res.geometry:
        groups[(g["code"], g["el"], g.get("other"))].append(g["page"])
    for (code, el, other), pgs in groups.items():
        r = row_of(pgs[0]) or {}
        more = f" (on {len(pgs)} pages)" if len(pgs) > 1 else ""
        out.append(make_issue(code, page=pgs[0] or None, row_id=r.get("row_id"), row_index=r.get("source_row_index"),
                              field=el, message=f"{code.replace('_', ' ').capitalize()}: '{el}'" + (f" and '{other}'" if other else "") + more))
    for u in res.blocked_requests:
        out.append(make_issue("ASSET_LOAD_FAILURE", field="network", actual=u[:80],
                              message="The renderer tried to load an unmanaged resource; it was blocked."))
    return out


# ---- preview -------------------------------------------------------------------
def render_preview_png(pid: str, row_id: Optional[str] = None) -> dict:
    p = get_project(pid)
    msgs = readiness(p)
    # a preview of the blank design does not need the copy confirmation
    msgs = [m for m in msgs if not m.startswith("Confirm that you want exactly")]
    # No recipients yet: preview with a clearly fictional sample name so the design can be judged. Never exported.
    sample = p.output_mode == "personalised" and (not p.source.rows or not p.mapping or not p.mapping.name)
    if sample:
        msgs = [m for m in msgs if not m.startswith(("Add recipients", "Confirm the column mapping"))]
    if msgs:
        raise JobFailure("Not ready for a preview", {"blocking": msgs})
    if sample:
        ctx = RenderContext(p.design, p.event, [PageData("Alexandra Sample-Name", "Sample Organisation", "Sample Award")])
        res = render_pdf(ctx, project_assets(p), p.event.event_name or p.title)
        pdf = pdfium.PdfDocument(res.pdf)
        img = pdf[0].render(scale=1.6).to_pil()
        h = hashlib.sha256(("sample|" + p.design.model_dump_json() + p.event.model_dump_json()).encode()).hexdigest()
        aid = add_artifact(pid, "preview", h, hashlib.sha256(res.pdf).hexdigest(), 1, "preview", {"row_id": None, "sample": True})
        d = artifact_dir(pid, aid)
        img.save(d / "preview.png")
        (d / "preview.pdf").write_bytes(res.pdf)
        return {"artifact_id": aid, "intent_hash": h, "issues": [], "fits": res.fits, "sample": True}
    intent = build_intent(p)
    ctx = _render_ctx(p, intent, row_id)
    if intent["mode"] == "blank_name":
        ctx.pages = ctx.pages[:1]
    ctx.pages = ctx.pages[:1]
    res = render_pdf(ctx, project_assets(p), p.event.event_name or p.title)
    pdf = pdfium.PdfDocument(res.pdf)
    img = pdf[0].render(scale=1.6).to_pil()
    for a in list_artifacts(pid, "preview"):
        pass
    h = intent_hash(intent)
    aid = add_artifact(pid, "preview", h, hashlib.sha256(res.pdf).hexdigest(), 1, "preview", {"row_id": row_id})
    d = artifact_dir(pid, aid)
    img.save(d / "preview.png")
    (d / "preview.pdf").write_bytes(res.pdf)
    return {"artifact_id": aid, "intent_hash": h, "issues": [i.model_dump() for i in _render_issues(res, intent)],
            "fits": res.fits}


# ---- export --------------------------------------------------------------------
def _sanitise_csv(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_report(p: Project, intent: dict, ih: str, pdf_sha: str, pages: int, issues: list[Issue], statuses: list[dict],
                 summary: dict, completion: str) -> dict:
    manifest = None
    if intent["mode"] == "personalised":
        manifest = [{"page": x["page"], "row_id": x["row_id"], "source_row_index": x["source_row_index"]} for x in intent["pages"]]
    return {"report_version": 1, "generated_at": now_iso(), "project_id": p.id, "mode": intent["mode"],
            "intent_hash": ih, "pdf_sha256": pdf_sha, "pdf_pages": pages, "completion": completion,
            "recipient_matching": summary.get("recipient_matching"), "summary": summary,
            "counts": {"errors": sum(i.severity == "error" for i in issues), "warnings": sum(i.severity == "warning" for i in issues)},
            "issues": [i.model_dump() for i in issues], "page_statuses": statuses, "manifest": manifest,
            "meaning_of_checked": NOTE}


def report_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["page", "source_row_index", "code", "severity", "field", "expected", "actual", "message", "acknowledged", "ack_note"]
    w.writerow(cols)
    for i in report["issues"]:
        w.writerow([_sanitise_csv(i.get(c)) for c in cols])
    return buf.getvalue()


def checkpoint_path(pid: str, ih: str) -> Path:
    """Finished chunks of an export live here, keyed by the export's content hash."""
    return project_dir(pid) / "checkpoints" / ih[:16]


def plan_export(pid: str) -> dict:
    """What a durable workflow needs to know: how many chunks, and which version of the project they belong to.
    Only ids and counts: no names ever go into a workflow."""
    p = get_project(pid)
    msgs = readiness(p)
    if msgs:
        raise JobFailure("Not ready to export", {"blocking": msgs})
    intent = build_intent(p)
    return {"intent_hash": intent_hash(intent), "chunks": chunk_count(_render_ctx(p, intent))}


def render_export_chunk(pid: str, ih: str, ci: int) -> None:
    p = get_project(pid)
    intent = build_intent(p)
    if intent_hash(intent) != ih:
        raise JobFailure("The project changed while the export was running. Start it again.")
    rctx = _render_ctx(p, intent)
    render_pdf(rctx, project_assets(p), p.event.event_name or p.title, checkpoint_dir=checkpoint_path(pid, ih), only_chunks=[ci])


def run_export(pid: str, ctx: JobCtx, checkpoint: bool = False) -> dict:
    s = get_settings()
    p = get_project(pid)
    msgs = readiness(p)
    if msgs:
        raise JobFailure("Not ready to export", {"blocking": msgs})
    intent = build_intent(p)
    ih = intent_hash(intent)
    rctx = _render_ctx(p, intent)
    issues: list[Issue] = []
    if intent["mode"] == "personalised":
        issues += source_issues(p.source.rows, p.mapping, require_name=True)
    issues += _glyph_issues(p, intent, rctx)
    total_chunks = max(1, -(-len(rctx.pages) // 25))
    ctx.progress(0, total_chunks + 2, "Rendering pages")
    cp = checkpoint_path(pid, ih) if checkpoint else None
    res = render_pdf(rctx, project_assets(p), p.event.event_name or p.title, cancel=ctx.cancel, checkpoint_dir=cp,
                     progress=lambda d, t: ctx.progress(d, t + 2, f"Rendered {min(d * 25, len(rctx.pages))} of {len(rctx.pages)} pages"))
    issues += _render_issues(res, intent)
    ctx.progress(total_chunks + 1, total_chunks + 2, "Checking the PDF")
    vintent = _verify_intent(p, intent, rctx)
    if intent["mode"] == "blank_name":
        vintent["stale_strings"] = [mapped_values(r, p.mapping)["name"] for r in p.source.rows] if p.mapping else \
                                   [r.cells.get(p.source.headers[0], "") for r in p.source.rows if p.source.headers]
    try:
        vissues, summary = verify_generated(res.pdf, vintent, s.max_pdf_pages)
    except PdfProblem as e:
        raise JobFailure(e.message)
    for i in vissues:  # never echo a leaked recipient string back into a report
        if i.code == "STALE_RECIPIENT_IN_BLANK_OUTPUT" and intent["mode"] == "blank_name":
            i.actual = "(redacted)"
    issues += vissues
    if ctx.cancel.is_set():
        raise Cancelled()
    # de-duplicate by id, apply acknowledgements
    seen, uniq = set(), []
    for i in issues:
        if i.id not in seen:
            seen.add(i.id)
            uniq.append(i)
    apply_acknowledgements(uniq, p.acknowledgements)
    completion = completion_state(uniq)
    n = res.page_count
    statuses = []
    for pg in range(1, n + 1):
        pis = [i for i in uniq if i.page == pg or (i.page is None and i.row_id and intent["pages"] and pg <= len(intent["pages"])
                                                    and intent["pages"][pg - 1]["row_id"] == i.row_id)]
        statuses.append({"page": pg, "status": status_for(pis),
                         "row_id": (intent["pages"][pg - 1]["row_id"] if intent["pages"] and pg <= len(intent["pages"]) else None)})
    pdf_sha = hashlib.sha256(res.pdf).hexdigest()
    report = build_report(p, intent, ih, pdf_sha, n, uniq, statuses, summary, completion)
    # write the artifact only now: a cancelled/interrupted run never leaves a "completed" artifact behind
    aid = add_artifact(pid, "export", ih, pdf_sha, n, completion, {"mode": intent["mode"]})
    d = artifact_dir(pid, aid)
    tag = "" if completion == "checked" else "_DRAFT"
    base = (f"certificates_BLANK-NAME_x{n}_{slug(p.event.event_name)}{tag}" if intent["mode"] == "blank_name"
            else f"certificates_personalised_{slug(p.event.event_name)}{tag}")
    (d / f"{base}.pdf").write_bytes(res.pdf)
    (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "report.csv").write_text(report_csv(report), encoding="utf-8", newline="")
    (d / "thumbs").mkdir(exist_ok=True)
    doc = pdfium.PdfDocument(res.pdf)
    for k in range(n):
        doc[k].render(scale=0.35).to_pil().save(d / "thumbs" / f"{k+1}.png")
    import sqlite3
    from .storage import db
    with db() as c:
        c.execute("UPDATE artifacts SET meta=? WHERE id=?",
                  (json.dumps({"mode": intent["mode"], "pdf": f"{base}.pdf", "report_json": "report.json",
                               "report_csv": "report.csv", "counts": report["counts"]}), aid))
    ctx.progress(total_chunks + 2, total_chunks + 2, "Done")
    if cp is not None:
        shutil.rmtree(cp, ignore_errors=True)       # chunk files hold names: remove them once the artifact is written
    return {"artifact_id": aid, "completion": completion, "pages": n, "counts": report["counts"],
            "filename": f"{base}.pdf", "intent_hash": ih}
