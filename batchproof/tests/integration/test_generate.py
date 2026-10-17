import io
import sqlite3

import pdfplumber
import pytest

from backend.app import storage
from tests.conftest import EX, codes, export_ok, make_project, pdf_bytes, wait_job

ROWS = [
    {"name": "Priya Sharma-Iyer", "organisation": "Greenfield College", "award": "First Place", "recipient_id": "001"},
    {"name": "José Ángel Núñez", "organisation": "Riverside University", "award": "", "recipient_id": "002"},
    {"name": "Zoë O'Brien", "organisation": "", "award": "Best Design", "recipient_id": "003"},
    {"name": "<b>Hi</b> & \"Q\"", "organisation": "", "award": "", "recipient_id": "004"},
    {"name": "<script>alert(1)</script>", "organisation": "", "award": "", "recipient_id": "005"},
]


def text_pages(pdf):
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        return [pg.extract_text() or "" for pg in p.pages]


def upload(c, pid, path, role="logo", idx=0):
    r = c.post(f"/api/projects/{pid}/assets", files={"file": (path.name, path.read_bytes(), "image/png")},
               data={"role": role, "signatory_index": idx})
    assert r.status_code == 200, r.text
    return r.json()


def test_valid_batch_with_assets_is_checked_and_text_is_selectable(client):
    pid = make_project(client, ROWS)
    upload(client, pid, EX / "assets" / "logo_fictional.png")
    upload(client, pid, EX / "assets" / "signature_fictional.png", "signature", 0)
    j, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", a["report"]["issues"]
    assert a["pages"] == 5 and a["report"]["pdf_pages"] == 5 and a["stale"] is False
    pdf = pdf_bytes(client, pid, a)
    t = text_pages(pdf)
    assert "José Ángel Núñez" in t[1] and "Zoë O'Brien" in t[2]       # selectable, exact
    assert '<b>Hi</b> & "Q"' in t[3] and "<script>alert(1)</script>" in t[4]  # rendered literally
    assert all("Test Summit 2026" in x and "Dr. Test Signer" in x for x in t)
    assert a["meta"]["pdf"].startswith("certificates_personalised_") and "DRAFT" not in a["meta"]["pdf"]
    assert client.get(f"/api/projects/{pid}/artifacts/{a['id']}/thumb/1.png").status_code == 200
    assert client.get(f"/api/projects/{pid}/artifacts/{a['id']}/report.csv").status_code == 200
    # Original logo is embedded (not repainted/stretched): placed image keeps its 3:1 proportion
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        im = p.pages[0].images[0]
        assert abs((im["x1"] - im["x0"]) / (im["bottom"] - im["top"]) - 3.0) < 0.05


def test_pdf_metadata_has_no_recipient_data(client):
    pid = make_project(client, ROWS)
    j, a = export_ok(client, pid)
    from pypdf import PdfReader
    meta = " ".join(str(v) for v in PdfReader(io.BytesIO(pdf_bytes(client, pid, a))).metadata.values())
    assert "Priya" not in meta and "Test Summit 2026" in meta


def test_html_is_escaped_in_canonical_document(client):
    from backend.app.schemas import DesignSpec, EventFields
    from backend.app.services.rendering.html import PageData, RenderContext, build_document
    ctx = RenderContext(DesignSpec(), EventFields(event_name="x", organisation="<img src=x onerror=alert(1)>"),
                        [PageData(name="</span><script>alert(1)</script>")])
    html = build_document(ctx, "t")
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)" in html and "<img src=x" not in html


def test_long_name_fits_after_adjustment_needs_acknowledgement(client):
    rows = [{"name": "Konstantinos Papadopoulos-Lee"}, {"name": "Ann Lee"}]
    pid = make_project(client, rows)
    j, a = export_ok(client, pid)
    adj = [i for i in a["report"]["issues"] if i["code"] == "NAME_FONT_ADJUSTED"]
    assert len(adj) == 1 and adj[0]["page"] == 1 and a["report"]["completion"] == "needs_review"
    assert a["meta"]["pdf"].endswith("_DRAFT.pdf")
    r = client.post(f"/api/projects/{pid}/acknowledge", json={"issue_id": adj[0]["id"], "note": "size ok, checked by eye"})
    assert r.status_code == 200
    a2 = client.get(f"/api/projects/{pid}/artifacts/{a['id']}").json()
    assert a2["report"]["completion"] == "checked" and a2["report"]["issues"][0]["ack_note"]
    assert client.post(f"/api/projects/{pid}/acknowledge", json={"issue_id": "x", "note": " "}).status_code == 422


def test_name_that_cannot_fit_is_blocked_then_two_lines_option(client):
    long = "Alexandria Konstantinopoulos-Montgomery Wellington-Smythe"
    pid = make_project(client, [{"name": long}])
    j, a = export_ok(client, pid)
    assert "NAME_OVERFLOW" in codes(a) and a["report"]["completion"] == "blocked"
    assert a["meta"]["pdf"].endswith("_DRAFT.pdf")                      # clearly labelled draft
    d = client.get(f"/api/projects/{pid}").json()["design"]
    d["allow_two_lines"] = True
    client.put(f"/api/projects/{pid}/design", json=d)
    j, a = export_ok(client, pid)
    assert "NAME_OVERFLOW" not in codes(a) and "FIELD_MISMATCH" not in codes(a), a["report"]["issues"]
    adj = next(i for i in a["report"]["issues"] if i["code"] == "NAME_FONT_ADJUSTED")
    assert "2 lines" in adj["message"]


def test_unsupported_glyph_blocks_instead_of_silently_substituting(client):
    pid = make_project(client, [{"name": "李小龍"}, {"name": "Ann"}])
    j, a = export_ok(client, pid)
    g = [i for i in a["report"]["issues"] if i["code"] == "UNSUPPORTED_GLYPH"]
    assert g and g[0]["row_id"] and a["report"]["completion"] == "blocked"


def test_stale_artifacts_after_every_kind_of_edit(client):
    pid = make_project(client, ROWS[:2])
    j, a = export_ok(client, pid)
    aid = a["id"]
    stale = lambda: client.get(f"/api/projects/{pid}/artifacts/{aid}").json()["stale"]
    assert stale() is False
    # event field
    ev = client.get(f"/api/projects/{pid}").json()["event"]
    client.patch(f"/api/projects/{pid}", json={"event": {**ev, "event_date": "13 October 2026"}})
    assert stale() is True
    client.patch(f"/api/projects/{pid}", json={"event": ev})
    assert stale() is False                    # content-addressed: restoring the inputs restores validity
    # source data
    client.put(f"/api/projects/{pid}/recipients", json={"rows": ROWS[:1]})
    assert stale() is True
    client.put(f"/api/projects/{pid}/recipients", json={"rows": ROWS[:2]})
    assert stale() is False
    # design
    d = client.get(f"/api/projects/{pid}").json()["design"]
    client.put(f"/api/projects/{pid}/design", json={**d, "density": 1.1})
    assert stale() is True
    client.put(f"/api/projects/{pid}/design", json=d)
    assert stale() is False
    # mode switch
    client.patch(f"/api/projects/{pid}", json={"output_mode": "blank_name"})
    assert stale() is True


def test_cancel_leaves_no_completed_artifact(client):
    rows = [{"name": f"Person Number {i}"} for i in range(100)]
    pid = make_project(client, rows)
    jid = client.post(f"/api/projects/{pid}/export").json()["job_id"]
    assert client.post(f"/api/jobs/{jid}/cancel").json()["requested"] is True
    j = wait_job(client, jid)
    assert j["status"] == "cancelled", j
    assert [x for x in client.get(f"/api/projects/{pid}/artifacts").json() if x["kind"] == "export"] == []


def test_interrupted_jobs_are_marked_on_restart(client):
    pid = make_project(client, ROWS[:1])
    with storage.db() as c:
        c.execute("INSERT INTO jobs VALUES('deadbeefdeadbeef',?,'export','running',0.4,'x','{}','t','t')", (pid,))
    storage.init_db()
    j = client.get("/api/jobs/deadbeefdeadbeef").json()
    assert j["status"] == "interrupted" and "run again" in j["message"]


def test_export_is_refused_until_inputs_are_confirmed(client):
    pid = client.post("/api/projects", json={}).json()["id"]
    r = client.post(f"/api/projects/{pid}/export")
    assert r.status_code == 422 and r.json()["detail"]["blocking"]
    pid = make_project(client, ROWS[:1])
    client.patch(f"/api/projects/{pid}", json={"event": {"event_name": "X", "organisation": "Y", "event_date": ""}})
    assert "event date" in " ".join(client.post(f"/api/projects/{pid}/export").json()["detail"]["blocking"])


def test_unknown_placeholders_rejected(client):
    pid = make_project(client, ROWS[:1])
    d = client.get(f"/api/projects/{pid}").json()["design"]
    assert client.put(f"/api/projects/{pid}/design", json={**d, "body_text": "by {signatory}"}).status_code == 422


def test_design_cannot_carry_html_or_unknown_fields(client):
    pid = make_project(client, ROWS[:1])
    d = client.get(f"/api/projects/{pid}").json()["design"]
    assert client.put(f"/api/projects/{pid}/design", json={**d, "palette": {**d["palette"], "primary": "red; background:url(x)"}}).status_code == 422
    assert client.put(f"/api/projects/{pid}/design", json={**d, "html": "<script>"}).status_code == 422
    assert client.put(f"/api/projects/{pid}/design", json={**d, "fonts": {**d["fonts"], "heading": "comic-sans"}}).status_code == 422


def test_all_three_layouts_render_and_verify(client):
    for layout in ("academic", "formal", "event"):
        pid = make_project(client, ROWS[:2], layout=layout)
        j, a = export_ok(client, pid)
        assert a["report"]["completion"] == "checked", (layout, a["report"]["issues"])


def test_preview_is_canonical_png(client):
    pid = make_project(client, ROWS)
    r = client.post(f"/api/projects/{pid}/preview", json={"row_id": "r2"})
    assert r.status_code == 200
    png = client.get(f"/api/projects/{pid}/artifacts/{r.json()['artifact_id']}/preview.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_name_too_long_even_for_two_lines_stays_blocked(client):
    pid = make_project(client, [{"name": "Alexandria Konstantinopoulos-Montgomery Wellington-Smythe the Third of Westminster and Bartholomew Featherstonehaugh-Cholmondeley Ravenscroft-Pennington"}])
    d = client.get(f"/api/projects/{pid}").json()["design"]
    client.put(f"/api/projects/{pid}/design", json={**d, "allow_two_lines": True})
    j, a = export_ok(client, pid)
    assert "NAME_OVERFLOW" in codes(a) and a["report"]["completion"] == "blocked"
