import io

import pdfplumber
import pytest
from PIL import Image

from backend.app.services.rendering.layouts import MM_TO_PT
from tests.conftest import codes, export_ok, make_project, pdf_bytes

NAMES = [{"name": "Priya Sharma-Iyer", "organisation": "Greenfield College", "award": "First Place"},
         {"name": "José Núñez", "organisation": "Riverside University", "award": "Second"},
         {"name": "Zoë O'Brien", "organisation": "Lakeside", "award": "Third"}]


def blank(c, pid, **kw):
    b = {"copies": 1, "confirmed_copies": kw.pop("confirmed", kw.get("copies", 1)), "line": True,
         "width_mm": 120, "height_mm": 18, "optional_fields": {}, **kw}
    r = c.patch(f"/api/projects/{pid}", json={"output_mode": "blank_name", "blank": b})
    assert r.status_code == 200, r.text


def texts(pdf):
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        return [pg.extract_text() or "" for pg in p.pages]


def name_area_ink(c, pid, a, w=120, h=18, scale=3.0):
    """Count non-white pixels inside the reserved name rectangle of page 1 of the final PDF."""
    r = c.get(f"/api/projects/{pid}/artifacts/{a['id']}/page/1.png?scale={scale}")
    im = Image.open(io.BytesIO(r.content)).convert("L")
    k = MM_TO_PT * scale
    x0, x1 = (148.5 - w / 2) * k, (148.5 + w / 2) * k
    y0, y1 = (100 - h / 2) * k, (100 + h / 2) * k + 2
    crop = im.crop((int(x0), int(y0), int(x1), int(y1)))
    return sum(1 for px in crop.getdata() if px < 200)


def test_single_blank_certificate_needs_no_recipients(client):
    pid = make_project(client, rows=None, mode="blank_name")
    blank(client, pid)
    j, a = export_ok(client, pid)
    rep = a["report"]
    assert rep["completion"] == "checked", rep["issues"]
    assert rep["pdf_pages"] == 1 and rep["mode"] == "blank_name" and rep["recipient_matching"] == "not_applicable"
    assert rep["manifest"] is None
    assert "BLANK-NAME" in a["meta"]["pdf"]
    t = texts(pdf_bytes(client, pid, a))[0]
    assert "Test Summit 2026" in t and "Dr. Test Signer" in t and "12 October 2026" in t   # fixed details intact
    for banned in ("Name", "Recipient", "John Doe", "{{name}}", "Priya"):
        assert banned not in t


def test_handwriting_line_toggle_changes_the_actual_pdf(client):
    pid = make_project(client, rows=None, mode="blank_name")
    blank(client, pid, line=True)
    _, a_on = export_ok(client, pid)
    blank(client, pid, line=False)
    _, a_off = export_ok(client, pid)
    assert name_area_ink(client, pid, a_on) > 200       # a printed line
    assert name_area_ink(client, pid, a_off) == 0       # genuinely clean whitespace


def test_writing_area_size_is_configurable_within_bounds(client):
    pid = make_project(client, rows=None, mode="blank_name")
    blank(client, pid, width_mm=200, height_mm=28)
    _, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", a["report"]["issues"]
    assert name_area_ink(client, pid, a, 200, 28) > 200
    for bad in ({"width_mm": 30}, {"height_mm": 80}, {"copies": 0}):
        r = client.patch(f"/api/projects/{pid}", json={"blank": {"copies": 1, "line": True, "width_mm": 120, "height_mm": 18, **bad}})
        assert r.status_code == 422, bad


def test_repeated_blank_pages_are_valid_not_duplicates(client):
    pid = make_project(client, rows=None, mode="blank_name")
    blank(client, pid, copies=5)
    _, a = export_ok(client, pid)
    assert a["report"]["pdf_pages"] == 5 and a["report"]["completion"] == "checked"
    assert "DUPLICATE_OUTPUT_RECORD" not in codes(a) and "x5" in a["meta"]["pdf"]
    assert len(set(texts(pdf_bytes(client, pid, a)))) == 1            # identical pages, by intent


def test_copy_count_must_be_confirmed_and_is_capped(client):
    pid = make_project(client, rows=None, mode="blank_name")
    client.patch(f"/api/projects/{pid}", json={"blank": {"copies": 7, "confirmed_copies": None, "line": True}})
    r = client.post(f"/api/projects/{pid}/export")
    assert r.status_code == 422 and "exactly 7" in " ".join(r.json()["detail"]["blocking"])
    assert client.patch(f"/api/projects/{pid}", json={"blank": {"copies": 101}}).status_code == 422


def test_switching_personalised_to_blank_leaks_no_recipient(client):
    pid = make_project(client, NAMES)
    _, personalised = export_ok(client, pid)
    assert personalised["report"]["completion"] == "checked"
    blank(client, pid, copies=2, optional_fields={"organisation": {"mode": "omit"}, "award": {"mode": "omit"}})
    # recipient data is kept ...
    assert len(client.get(f"/api/projects/{pid}").json()["source"]["rows"]) == 3
    # ... but the earlier personalised output is now stale
    assert client.get(f"/api/projects/{pid}/artifacts/{personalised['id']}").json()["stale"] is True
    _, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", a["report"]["issues"]
    pdf = pdf_bytes(client, pid, a)
    alltext = " ".join(texts(pdf))
    import json as _j
    report_text = _j.dumps(a["report"], ensure_ascii=False)
    from pypdf import PdfReader
    meta = " ".join(str(v) for v in PdfReader(io.BytesIO(pdf)).metadata.values())
    for n in ("Priya", "Sharma", "José", "Núñez", "Zoë", "Greenfield", "Riverside", "Lakeside", "First Place"):
        assert n not in alltext and n not in report_text and n not in meta, n
    # and nothing in the raw artifact files either
    from backend.app import storage
    for f in storage.artifact_dir(pid, a["id"]).rglob("*"):
        if f.is_file() and f.suffix in (".json", ".csv"):
            assert "Priya" not in f.read_text(encoding="utf-8")


def test_per_recipient_fields_must_be_chosen_and_never_inherited(client):
    pid = make_project(client, NAMES)
    blank(client, pid)                                    # org/award are mapped but no policy chosen
    r = client.post(f"/api/projects/{pid}/export")
    assert r.status_code == 422
    msg = " ".join(r.json()["detail"]["blocking"])
    assert "organisation" in msg and "award" in msg
    # fixed text
    blank(client, pid, optional_fields={"organisation": {"mode": "fixed", "fixed_text": "Example College"}, "award": {"mode": "omit"}})
    _, a = export_ok(client, pid)
    t = texts(pdf_bytes(client, pid, a))[0]
    assert "Example College" in t and "Greenfield" not in t and "First Place" not in t
    assert a["report"]["completion"] == "checked", a["report"]["issues"]
    # handwriting field: reserved and empty, extra line drawn
    blank(client, pid, optional_fields={"organisation": {"mode": "handwriting"}, "award": {"mode": "omit"}})
    _, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", a["report"]["issues"]
    assert "Greenfield" not in texts(pdf_bytes(client, pid, a))[0]


def test_required_name_checks_are_disabled_but_fixed_checks_remain(client):
    pid = make_project(client, [{"name": ""}, {"name": "Ann"}])      # a missing name would block personalised mode
    blank(client, pid, optional_fields={"organisation": {"mode": "omit"}, "award": {"mode": "omit"}})
    _, a = export_ok(client, pid)
    assert "MISSING_SOURCE_VALUE" not in codes(a) and "MISSING_RECIPIENT" not in codes(a)
    assert a["report"]["completion"] == "checked"
    # fixed detail problems still count (a glyph the fonts cannot draw)
    pid2 = make_project(client, rows=None, mode="blank_name", organisation="李小龍 Club")
    blank(client, pid2)
    _, a2 = export_ok(client, pid2)
    assert "UNSUPPORTED_GLYPH" in codes(a2) and a2["report"]["completion"] == "blocked"


def test_obstructed_handwriting_area_is_detected_in_real_geometry(client):
    pid = make_project(client, NAMES)
    long_fixed = "An extremely long fixed award line " * 4
    blank(client, pid, optional_fields={"organisation": {"mode": "handwriting"},
                                        "award": {"mode": "fixed", "fixed_text": long_fixed[:120]}})
    _, a = export_ok(client, pid)
    assert "HANDWRITING_AREA_OBSTRUCTED" in codes(a) and a["report"]["completion"] == "blocked"


def test_blank_mode_with_no_design_changes_to_fixed_fields_invalidates(client):
    pid = make_project(client, rows=None, mode="blank_name")
    blank(client, pid)
    _, a = export_ok(client, pid)
    ev = client.get(f"/api/projects/{pid}").json()["event"]
    client.patch(f"/api/projects/{pid}", json={"event": {**ev, "event_date": "1 January 2027"}})
    assert client.get(f"/api/projects/{pid}/artifacts/{a['id']}").json()["stale"] is True
