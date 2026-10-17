"""FastAPI application. Binds to loopback by default; serves the built frontend if present."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import jobs, pipeline, storage
from .config import REPO, get_settings
from .schemas import (BlankOptions, Brand, ConfirmedMapping, DesignSpec, EventFields, OutputMode, Project, Signatory,
                      SourceData, TARGETS, now_iso)
from .services.ai import ollama, ops
from .services.ai.ollama import AIError
from .services.imports import tabular
from .services.matching.external import check_external
from .services.matching.source import mapped_values, source_issues
from .services.verification import pdf_extract
from .services.verification.common import apply_acknowledgements, completion_state, norm_cmp, status_for
from .services.verification.pdf_extract import PdfProblem

app = FastAPI(title="CertProof", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def guard_host(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host not in ("127.0.0.1", "localhost", "testserver", "[::1]"):
        return JSONResponse({"detail": "Host not allowed (loopback only)."}, status_code=403)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.on_event("startup")
def _startup() -> None:
    storage.init_db()


def P(pid: str) -> Project:
    try:
        p = storage.get_project(pid)
    except storage.StorageError:
        raise HTTPException(404, "Project not found")
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def bad(msg: str, code: int = 422):
    raise HTTPException(code, msg)


async def read_upload(f: UploadFile, limit_mb: Optional[int] = None) -> bytes:
    lim = (limit_mb or get_settings().max_upload_mb) * 1024 * 1024
    data = await f.read(lim + 1)
    if len(data) > lim:
        bad(f"File is larger than {lim // 1024 // 1024} MB.", 413)
    return data


# ---- health / AI ---------------------------------------------------------------
@app.get("/api/health")
def health():
    s = get_settings()
    return {"ok": True, "version": app.version, "data_dir": str(s.data_dir), "host": s.host}


@app.get("/api/ai/status")
def ai_status():
    return ollama.status()


@app.post("/api/ai/unload")
def ai_unload():
    return {"unloaded": ollama.unload()}


@app.get("/api/limits")
def limits():
    s = get_settings()
    return {"max_rows": s.max_rows, "max_pdf_pages": s.max_pdf_pages, "max_blank_copies": s.max_blank_copies,
            "max_upload_mb": s.max_upload_mb}


# ---- projects ------------------------------------------------------------------
class NewProject(BaseModel):
    title: str = "Untitled project"
    kind: str = "generate"
    sample: bool = False


SAMPLE_ROWS = [
    {"name": "Priya Sharma-Iyer", "organisation": "Greenfield College", "award": "First Place", "recipient_id": "001"},
    {"name": "José Ángel Núñez", "organisation": "Riverside University", "award": "Second Place", "recipient_id": "002"},
    {"name": "Zoë O'Brien", "organisation": "Greenfield College", "award": "Best Design", "recipient_id": "003"},
    {"name": "Mohammed Al-Farsi", "organisation": "Lakeside Institute", "award": "Participant", "recipient_id": "004"},
    {"name": "Alexandria Konstantinopoulos-Montgomery", "organisation": "Riverside University", "award": "Participant", "recipient_id": "005"},
    {"name": "Wei Chen", "organisation": "Greenfield College", "award": "Participant", "recipient_id": "006"},
    {"name": "<b>Test</b> & \"Quotes\"", "organisation": "Lakeside Institute", "award": "Participant", "recipient_id": "007"},
]


@app.get("/api/projects")
def list_projects():
    return storage.list_projects()


@app.post("/api/projects")
def create_project(body: NewProject):
    if body.kind not in ("generate", "check"):
        bad("kind must be 'generate' or 'check'")
    p = storage.create_project(body.title[:80] or "Untitled project", body.kind, is_demo=body.sample)
    if body.sample:
        p.title = "DEMO — Example Hackathon 2026 (synthetic data)"
        p.event = EventFields(event_name="Example Hackathon 2026", organisation="Example Tech Club (demo)",
                              cert_type="Certificate of Achievement", event_date="12 October 2026",
                              signatories=[Signatory(name="A. Example", title="Faculty Advisor"),
                                           Signatory(name="B. Sample", title="Club President")])
        p.design = ops.fallback_design("formal", p.brand)
        p.design_version = 1
        p.source = tabular.manual_source(SAMPLE_ROWS)
        p.source.version = 1
        p.mapping = ConfirmedMapping(name="Name", organisation="Organisation", award="Award", recipient_id="ID",
                                     method="auto_manual_entry", confirmed_at=now_iso(), version=1)
        storage.save_project(p)
    return p


def project_view(p: Project) -> dict:
    d = p.model_dump()
    d["intent_hash"] = pipeline.current_intent_hash(p)
    d["readiness"] = pipeline.readiness(p) if p.kind == "generate" else []
    d["source_issues"] = []
    if p.mapping and p.mapping.name:
        d["source_issues"] = [i.model_dump() for i in source_issues(p.source.rows, p.mapping, p.output_mode == "personalised")]
    return d


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return project_view(P(pid))


class Patch(BaseModel):
    title: Optional[str] = None
    event: Optional[EventFields] = None
    brand: Optional[Brand] = None
    output_mode: Optional[OutputMode] = None
    blank: Optional[BlankOptions] = None


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, body: Patch):
    p = P(pid)
    if body.title is not None:
        p.title = body.title[:80]
    if body.event is not None:
        p.event = body.event
    if body.brand is not None:
        p.brand = body.brand
    if body.output_mode is not None:
        p.output_mode = body.output_mode  # recipient data is kept; hash changes -> old artifacts go stale
    if body.blank is not None:
        if body.blank.copies > get_settings().max_blank_copies:
            bad(f"At most {get_settings().max_blank_copies} blank copies.")
        p.blank = body.blank
    storage.save_project(p)
    return project_view(p)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    P(pid)
    storage.delete_project(pid)
    return {"deleted": True}


class Ack(BaseModel):
    issue_id: str
    note: str = ""


@app.post("/api/projects/{pid}/acknowledge")
def acknowledge(pid: str, body: Ack):
    p = P(pid)
    if not body.note.strip():
        bad("An acknowledgement needs a short audit note.")
    p.acknowledgements[body.issue_id] = body.note.strip()[:200]
    storage.save_project(p)
    return {"ok": True}


# ---- assets --------------------------------------------------------------------
@app.post("/api/projects/{pid}/assets")
async def upload_asset(pid: str, file: UploadFile = File(...), role: str = Form("logo"), signatory_index: int = Form(0)):
    p = P(pid)
    data = await read_upload(file)
    try:
        a = storage.add_image_asset(pid, data, file.filename or "image")
    except storage.StorageError as e:
        bad(str(e))
    if role == "logo":
        p.event.logo_asset_id = a["id"]
    elif role == "signature":
        if signatory_index > 3:
            bad("At most 4 signatories")
        while len(p.event.signatories) <= signatory_index:
            p.event.signatories.append(Signatory())
        p.event.signatories[signatory_index].signature_asset_id = a["id"]
    else:
        bad("role must be 'logo' or 'signature'")
    storage.save_project(p)
    return a


@app.get("/api/projects/{pid}/assets/{aid}")
def get_asset(pid: str, aid: str):
    P(pid)
    a = storage.get_asset(pid, aid)
    if not a:
        raise HTTPException(404, "Asset not found")
    return FileResponse(a["path"], media_type=a["mime"])


# ---- design --------------------------------------------------------------------
class ProposeBody(BaseModel):
    brief: str = ""


def _need_event(p: Project):
    if not (p.event.event_name.strip() and p.event.organisation.strip()):
        bad("Enter the event name and organisation first.")


@app.post("/api/projects/{pid}/design/propose")
def propose_design(pid: str, body: ProposeBody):
    p = P(pid)
    _need_event(p)
    brief = body.brief or p.brand.brief
    event, brand = p.event, p.brand

    def run(ctx):
        try:
            spec, meta = ops.generate_design(brief, brand, event, ctx.cancel)
        except AIError as e:
            raise jobs.JobFailure(e.message, {"kind": e.kind})
        return {"design": spec.model_dump(), "meta": meta}

    return {"job_id": jobs.runner.submit(pid, "design", run)}


class FallbackBody(BaseModel):
    layout: str = "formal"


@app.post("/api/projects/{pid}/design/fallback")
def design_fallback(pid: str, body: FallbackBody):
    p = P(pid)
    if body.layout not in ("academic", "formal", "event", "luxe"):
        bad("Unknown layout")
    return ops.fallback_design(body.layout, p.brand)


@app.put("/api/projects/{pid}/design")
def put_design(pid: str, spec: DesignSpec):
    p = P(pid)
    bad_ph = pipeline.unknown_placeholders(spec.body_text) + pipeline.unknown_placeholders(spec.preamble_text)
    if bad_ph:
        bad("Unknown placeholders: " + ", ".join(bad_ph))
    p.design = spec
    p.design_version += 1
    storage.save_project(p)
    return project_view(p)


# ---- recipients ----------------------------------------------------------------
def _set_source(p: Project, src: SourceData, auto_map: bool = False):
    src.version = p.source.version + 1
    p.source = src
    if auto_map:
        p.mapping = ConfirmedMapping(name="Name", organisation="Organisation", award="Award", recipient_id="ID",
                                     method="auto_manual_entry", confirmed_at=now_iso(), version=(p.mapping.version + 1 if p.mapping else 1))
    else:
        p.mapping = None  # a new source needs a freshly reviewed mapping


@app.post("/api/projects/{pid}/recipients/import")
async def import_recipients(pid: str, file: Optional[UploadFile] = File(None), sheet: Optional[str] = Form(None),
                            header_row: int = Form(1)):
    p = P(pid)
    s = get_settings()
    d = storage.project_dir(pid)
    if file is not None:
        data = await read_upload(file)
        name = file.filename or "upload"
        ext = ".xlsx" if name.lower().endswith(".xlsx") else ".csv"
        for old in d.glob("source_upload.*"):
            old.unlink()
        (d / f"source_upload{ext}").write_bytes(data)
        (d / "source_name.txt").write_text(name, encoding="utf-8")
    else:
        ups = list(d.glob("source_upload.*"))
        if not ups:
            bad("Upload a CSV or XLSX file first.")
        data, name = ups[0].read_bytes(), (d / "source_name.txt").read_text(encoding="utf-8")
    try:
        src = tabular.parse_upload(data, name, sheet, max(1, header_row), s.max_rows)
    except tabular.ImportProblem as e:
        bad(str(e))
    _set_source(p, src)
    storage.save_project(p)
    return project_view(p)


class ManualBody(BaseModel):
    rows: Optional[list[dict]] = None
    paste: Optional[str] = None


@app.put("/api/projects/{pid}/recipients")
def put_recipients(pid: str, body: ManualBody):
    p = P(pid)
    if body.paste is not None:
        src = tabular.paste_source(body.paste)
    elif body.rows is not None:
        src = tabular.manual_source([{k: str(v) for k, v in r.items()} for r in body.rows])
    else:
        bad("Send 'rows' or 'paste'.")
    if len(src.rows) > get_settings().max_rows:
        bad(f"At most {get_settings().max_rows} recipients.")
    _set_source(p, src, auto_map=True)
    storage.save_project(p)
    return project_view(p)


# ---- mapping -------------------------------------------------------------------
class MapPropose(BaseModel):
    use_ai: bool = False


@app.post("/api/projects/{pid}/mapping/propose")
def propose_mapping(pid: str, body: MapPropose):
    p = P(pid)
    if not p.source.headers:
        bad("Import a source file first.")
    if not body.use_ai:
        return {"method": "rule_based", "proposal": ops.rule_based_mapping(p.source.headers)}
    headers, sample = p.source.headers, [r.cells for r in p.source.rows[:3]]

    def run(ctx):
        try:
            prop, meta = ops.suggest_mapping(headers, sample, ctx.cancel)
        except AIError as e:
            raise jobs.JobFailure(e.message, {"kind": e.kind, "fallback": ops.rule_based_mapping(headers)})
        return {"method": "ai", "proposal": prop, "meta": meta}

    return {"job_id": jobs.runner.submit(pid, "mapping", run)}


class MapConfirm(BaseModel):
    name: Optional[str] = None
    organisation: Optional[str] = None
    award: Optional[str] = None
    recipient_id: Optional[str] = None
    method: str = "manual"


@app.put("/api/projects/{pid}/mapping/confirm")
def confirm_mapping(pid: str, body: MapConfirm):
    p = P(pid)
    cols = [getattr(body, t) for t in TARGETS if getattr(body, t)]
    for c in cols:
        if c not in p.source.headers:
            bad(f"Column '{c}' does not exist in the source.")
    if len(set(cols)) != len(cols):
        bad("A column can be mapped to only one field.")
    if not body.name:
        bad("Choose the column that holds the recipient's name.")
    method = body.method if body.method in ("manual", "ai", "rule_based") else "manual"
    p.mapping = ConfirmedMapping(name=body.name, organisation=body.organisation, award=body.award,
                                 recipient_id=body.recipient_id, method=method, confirmed_at=now_iso(),
                                 version=(p.mapping.version + 1 if p.mapping else 1))
    storage.save_project(p)
    return project_view(p)


# ---- preview / export -----------------------------------------------------------
class PreviewBody(BaseModel):
    row_id: Optional[str] = None


@app.post("/api/projects/{pid}/preview")
def preview(pid: str, body: PreviewBody):
    P(pid)
    try:
        return pipeline.render_preview_png(pid, body.row_id)
    except jobs.JobFailure as e:
        raise HTTPException(422, {"message": e.message, **e.result})


@app.post("/api/projects/{pid}/export")
def export(pid: str):
    p = P(pid)
    msgs = pipeline.readiness(p)
    if msgs:
        raise HTTPException(422, {"message": "Not ready to export", "blocking": msgs})
    return {"job_id": jobs.runner.submit(pid, "export", lambda ctx: pipeline.run_export(pid, ctx))}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = jobs.get_job(jid)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    if not jobs.get_job(jid):
        raise HTTPException(404, "Job not found")
    return {"requested": jobs.runner.cancel(jid)}


# ---- artifacts -----------------------------------------------------------------
def _artifact_view(p: Project, a: dict) -> dict:
    if a["kind"] == "external_check":
        stale = a["intent_hash"] != external_hash(p, a["meta"])
    else:
        stale = a["intent_hash"] != pipeline.current_intent_hash(p)
    return {**a, "stale": stale}


@app.get("/api/projects/{pid}/artifacts")
def artifacts(pid: str):
    p = P(pid)
    return [_artifact_view(p, a) for a in storage.list_artifacts(pid) if a["kind"] != "preview"]


@app.get("/api/projects/{pid}/artifacts/{aid}")
def artifact(pid: str, aid: str):
    p = P(pid)
    a = storage.get_artifact(pid, aid)
    if not a:
        raise HTTPException(404, "Artifact not found")
    v = _artifact_view(p, a)
    rj = storage.artifact_dir(pid, aid) / "report.json"
    if rj.exists():
        rep = json.loads(rj.read_text(encoding="utf-8"))
        apply_ack_to_report(p, rep)
        v["report"] = rep
    return v


def apply_ack_to_report(p: Project, rep: dict) -> None:
    from .schemas import Issue
    issues = [Issue(**i) for i in rep["issues"]]
    apply_acknowledgements(issues, p.acknowledgements)
    rep["issues"] = [i.model_dump() for i in issues]
    rep["completion"] = completion_state(issues)


def _file(pid: str, aid: str, name: str, mime: str, download: Optional[str] = None):
    P(pid)
    if not storage.get_artifact(pid, aid):
        raise HTTPException(404, "Artifact not found")
    path = storage.artifact_dir(pid, aid) / name
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type=mime, filename=download)


@app.get("/api/projects/{pid}/artifacts/{aid}/pdf")
def artifact_pdf(pid: str, aid: str):
    a = storage.get_artifact(pid, aid)
    if not a or "pdf" not in a["meta"]:
        raise HTTPException(404, "No PDF for this artifact")
    return _file(pid, aid, a["meta"]["pdf"], "application/pdf", a["meta"]["pdf"])


@app.get("/api/projects/{pid}/artifacts/{aid}/report.json")
def artifact_report_json(pid: str, aid: str):
    return _file(pid, aid, "report.json", "application/json", "certproof_report.json")


@app.get("/api/projects/{pid}/artifacts/{aid}/report.csv")
def artifact_report_csv(pid: str, aid: str):
    return _file(pid, aid, "report.csv", "text/csv", "certproof_report.csv")


@app.get("/api/projects/{pid}/artifacts/{aid}/preview.png")
def artifact_preview_png(pid: str, aid: str):
    return _file(pid, aid, "preview.png", "image/png")


@app.get("/api/projects/{pid}/artifacts/{aid}/thumb/{n}.png")
def artifact_thumb(pid: str, aid: str, n: int):
    return _file(pid, aid, f"thumbs/{int(n)}.png", "image/png")


@app.get("/api/projects/{pid}/artifacts/{aid}/page/{n}.png")
def artifact_page(pid: str, aid: str, n: int, scale: float = 1.4):
    import io
    import pypdfium2 as pdfium
    a = storage.get_artifact(pid, aid)
    if not a or "pdf" not in a["meta"]:
        raise HTTPException(404, "No PDF for this artifact")
    path = storage.artifact_dir(pid, aid) / a["meta"]["pdf"]
    doc = pdfium.PdfDocument(str(path))
    if not (1 <= n <= len(doc)):
        raise HTTPException(404, "No such page")
    buf = io.BytesIO()
    doc[n - 1].render(scale=min(max(scale, 0.3), 3.0)).to_pil().save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


# ---- external PDF check ---------------------------------------------------------
def external_hash(p: Project, meta: dict) -> str:
    payload = {"rows": [r.cells for r in p.source.rows], "mapping": p.mapping.model_dump(exclude={"confirmed_at", "version"}) if p.mapping else None,
               "pdf": meta.get("pdf_sha256"), "zones": meta.get("zones"), "fixed": meta.get("fixed_texts"),
               "res": meta.get("resolutions")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _ext_pdf(pid: str) -> Path:
    return storage.project_dir(pid) / "external.pdf"


@app.post("/api/projects/{pid}/verify-external/inspect")
async def inspect_external(pid: str, file: UploadFile = File(...)):
    p = P(pid)
    s = get_settings()
    data = await read_upload(file)
    try:
        pages = pdf_extract.extract_pages(data, s.max_pdf_pages)
        pdf_extract.require_text_layer(pages)
    except PdfProblem as e:
        raise HTTPException(422, {"code": e.code, "message": e.message})
    _ext_pdf(pid).write_bytes(data)
    first = pages[0]
    lines = pdf_extract.lines_with_boxes(first)
    suggestion, notes = {}, []

    def band(rect):
        """Widen a line's box to a full-width band: other pages have names of different lengths."""
        h = rect[3] - rect[1]
        return [0.04, max(0.0, rect[1] - 0.25 * h), 0.96, min(1.0, rect[3] + 0.25 * h)]

    if p.mapping and p.mapping.name:
        names = {norm_cmp(mapped_values(r, p.mapping)["name"]) for r in p.source.rows}
        hits = [ln for ln in lines if norm_cmp(ln["text"]) in names]
        if len(hits) == 1:
            suggestion["name"] = band(hits[0]["rect"])
            row = next(r for r in p.source.rows if norm_cmp(mapped_values(r, p.mapping)["name"]) == norm_cmp(hits[0]["text"]))
            v = mapped_values(row, p.mapping)
            for f in ("organisation", "award", "recipient_id"):
                m = [ln for ln in lines if v[f] and norm_cmp(ln["text"]) == norm_cmp(v[f])]
                if len(m) == 1:
                    suggestion[f] = band(m[0]["rect"])
        else:
            notes.append("Could not tell automatically which text is the recipient name. Select the name line on the page "
                         "(or draw its area) to continue.")
    unreliable = [pg.index for pg in pages if pg.unreliable or not pg.chars]
    return {"pages": len(pages), "page_size_pt": [first.width, first.height], "lines": lines,
            "suggested_zones": suggestion, "notes": notes, "pages_without_text": unreliable,
            "caveat": "A searchable PDF can still extract unreliably. Pages that cannot be read are shown as 'Needs review', never as passed."}


@app.get("/api/projects/{pid}/external/page/{n}.png")
def external_page(pid: str, n: int, scale: float = 1.4):
    import io
    import pypdfium2 as pdfium
    P(pid)
    f = _ext_pdf(pid)
    if not f.exists():
        raise HTTPException(404, "No PDF uploaded")
    doc = pdfium.PdfDocument(str(f))
    if not (1 <= n <= len(doc)):
        raise HTTPException(404, "No such page")
    buf = io.BytesIO()
    doc[n - 1].render(scale=min(max(scale, 0.3), 3.0)).to_pil().save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


class ExtBody(BaseModel):
    zones: dict[str, list[float]]
    fixed_texts: list[str] = []
    resolutions: dict[int, str] = {}


@app.post("/api/projects/{pid}/verify-external")
def verify_external(pid: str, body: ExtBody):
    p = P(pid)
    if not _ext_pdf(pid).exists():
        bad("Upload the PDF first (inspect step).")
    if not p.mapping or not p.mapping.name:
        bad("Confirm the column mapping first.")
    if "name" not in body.zones or len(body.zones["name"]) != 4:
        bad("Mark the recipient-name area first.")
    for z in body.zones.values():
        if len(z) != 4 or not all(0 <= v <= 1 for v in z) or z[0] >= z[2] or z[1] >= z[3]:
            bad("Invalid zone rectangle.")
    zones, fixed, res = body.zones, [t for t in body.fixed_texts if t.strip()][:30], body.resolutions
    mapping, rows = p.mapping, p.source.rows

    def run(ctx):
        s = get_settings()
        data = _ext_pdf(pid).read_bytes()
        pages = pdf_extract.extract_pages(data, s.max_pdf_pages, cancel=ctx.cancel,
                                          progress=lambda d, t: ctx.progress(d, t + 1, f"Read {d} of {t} pages"))
        issues, assoc, extracted, recs = check_external(rows, mapping, pages, zones, fixed, res)
        apply_acknowledgements(issues, p.acknowledgements)
        by_page, by_row = {}, {}
        for i in issues:
            if i.page:
                by_page.setdefault(i.page, []).append(i)
            if i.row_id:
                by_row.setdefault(i.row_id, []).append(i)
        page_rows = [{"page": pg.index, "status": status_for(by_page.get(pg.index, [])) if assoc[pg.index].state not in ("unreliable",)
                      else "Needs review", "state": assoc[pg.index].state, "row_id": assoc[pg.index].row_id,
                      "candidates": assoc[pg.index].row_ids, "method": assoc[pg.index].method,
                      "extracted": extracted[pg.index]} for pg in pages]
        row_rows = []
        matched_rows = {a.row_id for a in assoc.values() if a.row_id}
        for rid, d in recs.items():
            st = status_for(by_row.get(rid, [])) if rid in matched_rows else ("Blocked" if any(i.code == "MISSING_RECIPIENT" and i.row_id == rid for i in issues) else "Needs review")
            row_rows.append({"row_id": rid, "source_row_index": d["row"].row_index, "name": d["name"], "status": st})
        counts = {"source_rows": len(recs), "pdf_pages": len(pages),
                  "rows_without_page": sum(i.code == "MISSING_RECIPIENT" for i in issues),
                  "unexpected_pages": sum(i.code == "UNEXPECTED_PAGE" for i in issues),
                  "ambiguous_pages": sum(i.code == "AMBIGUOUS_PAGE_MATCH" for i in issues),
                  "pages_checked": sum(1 for r in page_rows if r["status"] == "Checked")}
        sha = hashlib.sha256(data).hexdigest()
        meta = {"pdf_sha256": sha, "zones": zones, "fixed_texts": fixed, "resolutions": {str(k): v for k, v in res.items()}}
        meta_for_hash = {**meta, "resolutions": {str(k): v for k, v in res.items()}}
        ih = external_hash(p, meta_for_hash)
        completion = completion_state(issues)
        report = {"report_version": 1, "generated_at": now_iso(), "project_id": pid, "mode": "external_check", "intent_hash": ih,
                  "pdf_sha256": sha, "pdf_pages": len(pages), "completion": completion, "counts": counts,
                  "issues": [i.model_dump() for i in issues], "page_statuses": page_rows, "row_statuses": row_rows,
                  "meaning_of_checked": pipeline.NOTE,
                  "note": "Page count equality is not treated as evidence that every recipient exists."}
        aid = storage.add_artifact(pid, "external_check", ih, sha, len(pages), completion, {**meta, "counts": counts})
        d = storage.artifact_dir(pid, aid)
        (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "report.csv").write_text(pipeline.report_csv(report), encoding="utf-8", newline="")
        return {"artifact_id": aid, "completion": completion, "counts": counts}

    return {"job_id": jobs.runner.submit(pid, "verify_external", run)}


# ---- static frontend -----------------------------------------------------------
DIST = REPO / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404)
        f = (DIST / full_path).resolve()
        if full_path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")


def run():
    import uvicorn
    s = get_settings()
    uvicorn.run("backend.app.main:app", host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    run()
