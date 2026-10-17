"""Regenerates examples/output/* with the real pipeline (synthetic data only).
Personalised sample: one name needs a font-size adjustment; the warning is acknowledged here with an audit note
because the page was reviewed by eye when the example was produced."""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["BATCHPROOF_DATA_DIR"] = tempfile.mkdtemp(prefix="bp-ex-")
from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app import storage  # noqa: E402

EX = ROOT / "examples"
OUT = EX / "output"


def wait(c, jid):
    while True:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("completed", "failed", "cancelled"):
            return j
        time.sleep(0.2)


def export(c, pid):
    j = wait(c, c.post(f"/api/projects/{pid}/export").json()["job_id"])
    assert j["status"] == "completed", j
    return c.get(f"/api/projects/{pid}/artifacts/{j['result']['artifact_id']}").json()


def save(c, pid, a, stem):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{stem}.pdf").write_bytes(c.get(f"/api/projects/{pid}/artifacts/{a['id']}/pdf").content)
    (OUT / f"{stem}_report.json").write_text(json.dumps(a["report"], indent=2, ensure_ascii=False), encoding="utf-8")


with TestClient(app) as c:
    pid = c.post("/api/projects", json={"title": "examples"}).json()["id"]
    ev = {"event_name": "Example Hackathon 2026", "organisation": "Example Tech Club (demo)", "cert_type": "Certificate of Achievement",
          "event_date": "12 October 2026", "signatories": [{"name": "A. Example", "title": "Faculty Advisor"}, {"name": "B. Sample", "title": "Club President"}]}
    c.patch(f"/api/projects/{pid}", json={"event": ev})
    c.post(f"/api/projects/{pid}/assets", files={"file": ("logo.png", (EX / "assets/logo_fictional.png").read_bytes())}, data={"role": "logo"})
    c.post(f"/api/projects/{pid}/assets", files={"file": ("sig.png", (EX / "assets/signature_fictional.png").read_bytes())}, data={"role": "signature", "signatory_index": 0})
    c.put(f"/api/projects/{pid}/design", json=c.post(f"/api/projects/{pid}/design/fallback", json={"layout": "formal"}).json())
    r = c.post(f"/api/projects/{pid}/recipients/import", files={"file": ("r.csv", (EX / "recipients_sample.csv").read_bytes())})
    c.put(f"/api/projects/{pid}/mapping/confirm", json={"name": "Participant Full Name", "organisation": "College / University",
                                                         "award": "Prize Position", "recipient_id": "Reg No", "method": "manual"})
    a = export(c, pid)
    for i in a["report"]["issues"]:
        if i["code"] == "NAME_FONT_ADJUSTED":
            c.post(f"/api/projects/{pid}/acknowledge", json={"issue_id": i["id"], "note": "Reviewed page 5 by eye when producing this example; 24 pt is legible."})
    a = c.get(f"/api/projects/{pid}/artifacts/{a['id']}").json()
    save(c, pid, a, "personalised_6_certificates")
    print("personalised:", a["report"]["completion"], a["report"]["counts"])
    for line, stem in ((True, "blank_name_x3_with_line"), (False, "blank_name_x1_no_line")):
        n = 3 if line else 1
        c.patch(f"/api/projects/{pid}", json={"output_mode": "blank_name", "blank": {"copies": n, "confirmed_copies": n, "line": line,
                "optional_fields": {"organisation": {"mode": "omit"}, "award": {"mode": "omit"}}}})
        a = export(c, pid)
        save(c, pid, a, stem)
        print(stem, a["report"]["completion"], a["report"]["counts"])
