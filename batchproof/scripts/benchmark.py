"""Times a realistic 100-certificate export (with logo + signature) and a 100-copy blank-name export.
Run:  .venv\\Scripts\\python.exe scripts\\benchmark.py
Prints measured wall-clock seconds on THIS machine. Nothing is pre-filled."""
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BATCHPROOF_DATA_DIR", tempfile.mkdtemp(prefix="bp-bench-"))

from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import app  # noqa: E402

FIRST = ["Priya", "José", "Zoë", "Mohammed", "Wei", "Aiko", "Liam", "Fatima", "Noah", "Ines"]
LAST = ["Sharma-Iyer", "Núñez", "O'Brien", "Al-Farsi", "Chen", "Tanaka", "Murphy", "Rahman", "Okafor", "Silva"]


def wait(c, jid):
    while True:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("completed", "failed", "cancelled"):
            return j
        time.sleep(0.2)


def main():
    out = {"platform": platform.platform(), "python": sys.version.split()[0], "cpu_count": os.cpu_count()}
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"title": "bench"}).json()["id"]
        ev = {"event_name": "Benchmark Summit 2026", "organisation": "Synthetic Org", "cert_type": "Certificate of Participation",
              "event_date": "12 October 2026", "signatories": [{"name": "A. Example", "title": "Chair"}, {"name": "B. Sample", "title": "Director"}]}
        c.patch(f"/api/projects/{pid}", json={"event": ev})
        for role, f in (("logo", "logo_fictional.png"), ("signature", "signature_fictional.png")):
            c.post(f"/api/projects/{pid}/assets", files={"file": (f, (ROOT / "examples/assets" / f).read_bytes())}, data={"role": role, "signatory_index": 0})
        c.put(f"/api/projects/{pid}/design", json=c.post(f"/api/projects/{pid}/design/fallback", json={"layout": "formal"}).json())
        rows = [{"name": f"{FIRST[i % 10]} {LAST[(i * 7) % 10]}", "organisation": f"College {i % 7}", "award": "Participant", "recipient_id": f"{i:03d}"} for i in range(100)]
        c.put(f"/api/projects/{pid}/recipients", json={"rows": rows})
        for label, setup in (("personalised_100_first_run", None), ("personalised_100_second_run", None), ("blank_100_copies", "blank")):
            if setup == "blank":
                c.patch(f"/api/projects/{pid}", json={"output_mode": "blank_name", "blank": {"copies": 100, "confirmed_copies": 100, "line": True,
                        "optional_fields": {"organisation": {"mode": "omit"}, "award": {"mode": "omit"}}}})
            t = time.time()
            j = wait(c, c.post(f"/api/projects/{pid}/export").json()["job_id"])
            dt = time.time() - t
            out[label] = {"seconds": round(dt, 1), "status": j["status"], "pages": j["result"].get("pages"),
                          "completion": j["result"].get("completion"), "counts": j["result"].get("counts")}
    out["note"] = "Wall-clock for the whole job: canonical render, independent PDF re-read and checks, thumbnails, reports."
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
