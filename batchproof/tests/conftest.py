import glob
import os
import time
from pathlib import Path

import pytest

EX = Path(__file__).resolve().parents[1] / "examples"

_chrome = glob.glob("/opt/pw-browsers/chromium-1194/chrome-linux*/chrome")
if _chrome and not os.environ.get("BATCHPROOF_CHROMIUM_PATH"):
    os.environ["BATCHPROOF_CHROMIUM_PATH"] = _chrome[0]


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("bpdata")
    os.environ["BATCHPROOF_DATA_DIR"] = str(d)
    return d


@pytest.fixture()
def client(data_dir):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    with TestClient(app) as c:
        yield c


def wait_job(c, jid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return j
        time.sleep(0.2)
    raise TimeoutError(jid)


def export_ok(c, pid):
    r = c.post(f"/api/projects/{pid}/export")
    assert r.status_code == 200, r.text
    j = wait_job(c, r.json()["job_id"])
    assert j["status"] == "completed", j
    a = c.get(f"/api/projects/{pid}/artifacts/{j['result']['artifact_id']}").json()
    return j, a


def codes(a):
    return [i["code"] for i in a["report"]["issues"]]


def pdf_bytes(c, pid, a):
    return c.get(f"/api/projects/{pid}/artifacts/{a['id']}/pdf").content


def make_project(c, rows=None, mode="personalised", signatures=True, wording="", layout="formal", **event):
    pid = c.post("/api/projects", json={"title": "t"}).json()["id"]
    ev = {"event_name": "Test Summit 2026", "organisation": "Test Org", "cert_type": "Certificate of Participation",
          "event_date": "12 October 2026", "wording": wording,
          "signatories": [{"name": "Dr. Test Signer", "title": "Chair"}], **event}
    assert c.patch(f"/api/projects/{pid}", json={"event": ev}).status_code == 200
    d = c.post(f"/api/projects/{pid}/design/fallback", json={"layout": layout}).json()
    assert c.put(f"/api/projects/{pid}/design", json=d).status_code == 200
    if rows is not None:
        r = c.put(f"/api/projects/{pid}/recipients", json={"rows": rows})
        assert r.status_code == 200, r.text
    if mode == "blank_name":
        c.patch(f"/api/projects/{pid}", json={"output_mode": "blank_name"})
    return pid
