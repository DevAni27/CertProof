"""Workflow C: check a spreadsheet against a PDF produced elsewhere (ReportLab fixtures, not CertProof's renderer)."""
import json
import sys

import pytest

from tests.conftest import EX, wait_job

sys.path.insert(0, str(EX))
import make_fixtures as mf  # noqa: E402

MAPPING = {"name": "Participant Full Name", "organisation": "College / University", "award": "Prize Position", "recipient_id": "Reg No"}
FIXED = ["Example Hackathon 2026, 12 October 2026"]


def new_check(c, csv_path=None):
    pid = c.post("/api/projects", json={"kind": "check", "title": "ext"}).json()["id"]
    r = c.post(f"/api/projects/{pid}/recipients/import", files={"file": ("r.csv", (csv_path or EX / "recipients_sample.csv").read_bytes())})
    assert r.status_code == 200, r.text
    assert c.put(f"/api/projects/{pid}/mapping/confirm", json=MAPPING).status_code == 200
    return pid


def inspect(c, pid, pdf):
    return c.post(f"/api/projects/{pid}/verify-external/inspect", files={"file": ("x.pdf", pdf.read_bytes() if hasattr(pdf, "read_bytes") else pdf)})


def run(c, pid, zones, fixed=FIXED, res=None):
    r = c.post(f"/api/projects/{pid}/verify-external", json={"zones": zones, "fixed_texts": fixed, "resolutions": res or {}})
    assert r.status_code == 200, r.text
    j = wait_job(c, r.json()["job_id"])
    assert j["status"] == "completed", j
    return c.get(f"/api/projects/{pid}/artifacts/{j['result']['artifact_id']}").json()


def check(c, pdf, **kw):
    pid = new_check(c)
    ins = inspect(c, pid, pdf)
    assert ins.status_code == 200, ins.text
    zones = ins.json()["suggested_zones"]
    assert "name" in zones, ins.json()["notes"]
    return pid, run(c, pid, zones, **kw)


def issues(a, code=None):
    return [i for i in a["report"]["issues"] if code is None or i["code"] == code]


def test_clean_external_pdf_is_checked(client):
    pid, a = check(client, EX / "external_clean.pdf")
    assert a["report"]["completion"] == "checked", a["report"]["issues"]
    assert a["report"]["counts"]["pages_checked"] == 6 and a["report"]["counts"]["rows_without_page"] == 0


def test_reordered_pages_give_no_false_mismatches(client):
    pid, a = check(client, EX / "external_reordered.pdf")
    assert a["report"]["completion"] == "checked", a["report"]["issues"]
    first = a["report"]["page_statuses"][0]
    assert first["extracted"]["name"] == "Wei Chen" and first["method"] in ("id", "name", "name+secondary")


def test_flawed_pdf_with_equal_page_count_is_not_waved_through(client):
    pid, a = check(client, EX / "external_flawed.pdf")
    rep = a["report"]
    assert rep["pdf_pages"] == 6 and rep["counts"]["source_rows"] == 6          # same totals ...
    assert rep["completion"] == "blocked"                                        # ... still not OK
    assert rep["counts"]["rows_without_page"] == 2 and rep["counts"]["unexpected_pages"] == 1
    by = {}
    for i in rep["issues"]:
        by.setdefault(i["code"], []).append(i)
    org = [i for i in by["FIELD_MISMATCH"] if i["field"] == "organisation"][0]
    assert (org["page"], org["expected"], org["actual"]) == (2, "Riverside University", "Riverside College") and org["rect"]
    assert any(i["field"] == "name" and i["expected"] == "Wei Chen" and i["actual"] == "Wei Chenn" for i in by["FIELD_MISMATCH"])
    assert [i["page"] for i in by["FIXED_TEXT_MISMATCH"]] == [3]
    assert by["DUPLICATE_OUTPUT_RECORD"][0]["page"] == 4
    assert sorted(i["expected"] for i in by["MISSING_RECIPIENT"]) == ["Alexandria Konstantinopoulos-Montgomery", "Mohammed Al-Farsi"]
    assert by["UNEXPECTED_PAGE"][0]["actual"] == "Taylor Unknown"
    # every issue is explainable: next action present, source row number where there is a row
    assert all(i["next_action"] for i in rep["issues"])
    assert all(i["source_row_index"] for i in by["MISSING_RECIPIENT"])
    statuses = {p["page"]: p["status"] for p in rep["page_statuses"]}
    assert statuses[1] == "Checked" and statuses[2] == "Blocked"


def test_report_downloads_json_exact_csv_sanitised(client):
    pid = new_check(client)
    csv_bytes = (EX / "recipients_sample.csv").read_bytes().replace(b"Wei Chen", b'"=HYPERLINK(""http://x"",""go"")"')
    client.post(f"/api/projects/{pid}/recipients/import", files={"file": ("r.csv", csv_bytes)})
    client.put(f"/api/projects/{pid}/mapping/confirm", json=MAPPING)
    ins = inspect(client, pid, EX / "external_clean.pdf").json()
    a = run(client, pid, ins["suggested_zones"])
    j = json.loads(client.get(f"/api/projects/{pid}/artifacts/{a['id']}/report.json").text)
    exact = [i for i in j["issues"] if i["code"] == "MISSING_RECIPIENT" and i["expected"].startswith("=")][0]["expected"]
    assert exact == '=HYPERLINK("http://x","go")'                                  # JSON keeps the exact value
    csv_text = client.get(f"/api/projects/{pid}/artifacts/{a['id']}/report.csv").text
    assert "'=HYPERLINK" in csv_text and ",=HYPERLINK" not in csv_text and '"=HYPERLINK' not in csv_text


def test_scanned_corrupt_oversize_and_too_many_pages(client, monkeypatch):
    pid = new_check(client)
    r = inspect(client, pid, EX / "external_scanned.pdf")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "NO_TEXT_LAYER" and "OCR" in r.json()["detail"]["message"]
    r = inspect(client, pid, EX / "external_corrupt.pdf")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "CORRUPT_PDF"
    r = inspect(client, pid, b"hello")
    assert r.status_code == 422
    monkeypatch.setenv("MAX_PDF_PAGES", "3")
    r = inspect(client, pid, EX / "external_clean.pdf")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TOO_MANY_PAGES"
    monkeypatch.setenv("MAX_PDF_PAGES", "300")
    monkeypatch.setenv("MAX_UPLOAD_MB", "0")
    assert inspect(client, pid, EX / "external_clean.pdf").status_code == 413


def test_ambiguous_name_location_requires_manual_marking(client):
    pid = new_check(client)
    # a PDF whose names match nothing in the source: auto-detection must not guess
    mf.cert_pdf(EX.parent / "tests" / "_tmp_other.pdf", [{"name": "Nobody Known", "college": "X", "prize": "Y"}])
    ins = inspect(client, pid, EX.parent / "tests" / "_tmp_other.pdf").json()
    (EX.parent / "tests" / "_tmp_other.pdf").unlink()
    assert "name" not in ins["suggested_zones"] and ins["notes"] and ins["lines"]
    r = client.post(f"/api/projects/{pid}/verify-external", json={"zones": {}, "fixed_texts": []})
    assert r.status_code == 422
    # user marks the line manually -> check runs and reports the unmatched page honestly
    name_line = max(ins["lines"], key=lambda l: l["size"] if l["text"] == "Nobody Known" else 0)
    a = run(client, pid, {"name": name_line["rect"]})
    assert {i["code"] for i in a["report"]["issues"]} >= {"UNEXPECTED_PAGE", "MISSING_RECIPIENT"}


def test_shared_names_stay_unresolved_until_manual_confirmation(client):
    csv = b"Participant Full Name,College / University,Prize Position,Reg No\nSam Lee,,Participant,1\nSam Lee,,Participant,2\n"
    pid = client.post("/api/projects", json={"kind": "check"}).json()["id"]
    client.post(f"/api/projects/{pid}/recipients/import", files={"file": ("r.csv", csv)})
    client.put(f"/api/projects/{pid}/mapping/confirm", json={**MAPPING, "organisation": None, "recipient_id": None})
    pdf = EX.parent / "tests" / "_tmp_dup.pdf"
    mf.cert_pdf(pdf, [{"name": "Sam Lee", "college": "", "prize": "Participant"}] * 2)
    ins = inspect(client, pid, pdf).json()
    pdf.unlink()
    a = run(client, pid, ins["suggested_zones"], fixed=[])
    amb = [i for i in a["report"]["issues"] if i["code"] == "AMBIGUOUS_PAGE_MATCH"]
    assert len(amb) == 2 and a["report"]["completion"] == "needs_review"
    assert amb[0]["candidates"] == ["2", "3"]
    r2 = [p for p in a["report"]["page_statuses"]]
    assert all(p["state"] == "ambiguous" and p["status"] == "Needs review" for p in r2)
    rows = client.get(f"/api/projects/{pid}").json()["source"]["rows"]
    a2 = run(client, pid, ins["suggested_zones"], fixed=[], res={1: rows[1]["row_id"], 2: rows[0]["row_id"]})
    assert a2["report"]["completion"] == "checked", a2["report"]["issues"]


def test_external_result_goes_stale_when_source_or_mapping_changes(client):
    pid, a = check(client, EX / "external_clean.pdf")
    assert client.get(f"/api/projects/{pid}/artifacts/{a['id']}").json()["stale"] is False
    client.put(f"/api/projects/{pid}/mapping/confirm", json={**MAPPING, "award": None})
    assert client.get(f"/api/projects/{pid}/artifacts/{a['id']}").json()["stale"] is True


def test_xlsx_source_with_sheet_selection_via_api(client):
    pid = client.post("/api/projects", json={"kind": "check"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/recipients/import", files={"file": ("r.xlsx", (EX / "recipients_sample.xlsx").read_bytes())})
    assert r.json()["source"]["sheets"] == ["Winners", "Notes"] and r.json()["source"]["rows"][0]["cells"]["Reg No"] == "001"
    r = client.post(f"/api/projects/{pid}/recipients/import", data={"sheet": "Notes", "header_row": "1"})   # re-parse stored upload
    assert r.json()["source"]["sheet"] == "Notes" and r.json()["mapping"] is None
