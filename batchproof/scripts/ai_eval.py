"""Evaluate local-model assistance honestly against a rule-based baseline.

Run (Ollama running, model installed):   .venv\\Scripts\\python.exe scripts\\ai_eval.py
  --skip-ai       only run the rule-based baseline
  --out FILE      write JSON results (default docs/evaluation_results.json)

What it measures
  * Mapping: held-out header sets with a gold answer. Reported separately: correct / wrong / abstained,
    for the rule-based baseline and for the model. 'Abstained' = null where the gold has a column.
  * Design: schema validity on first attempt vs after the single retry vs failure, then every valid design is
    rendered with the real renderer and checked for layout violations. Cold (first call) and warm timings.
Nothing is pre-filled: if the model is unavailable, AI sections say so and no numbers are invented.
The header sets are small and written by the author of the tool: treat results as a smoke test, not a benchmark.
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.schemas import Brand, EventFields  # noqa: E402
from backend.app.services.ai import ollama, ops  # noqa: E402
from backend.app.services.ai.ollama import AIError  # noqa: E402

T = ("name", "organisation", "award", "recipient_id")
# (headers, sample row, gold mapping). Gold None = no suitable column exists.
HELDOUT = [
    (["Participant Full Name", "College / University", "Prize Position", "Reg No"], ["Ann Lee", "Alpha Univ", "1st", "007"], ["Participant Full Name", "College / University", "Prize Position", "Reg No"]),
    (["Nombre completo", "Universidad", "Puesto", "Matrícula"], ["José Núñez", "UNAM", "Segundo", "A0192"], ["Nombre completo", "Universidad", "Puesto", "Matrícula"]),
    (["Who", "From", "Result"], ["Bo Kim", "Beta Tech", "Winner"], ["Who", "From", "Result", None]),
    (["S.No", "Student", "Institution", "Rank", "Contact"], ["1", "Cy Day", "Gamma Inst", "3", "x@y.z"], ["Student", "Institution", "Rank", "S.No"]),
    (["Attendee", "Company", "Ticket No."], ["Di Eve", "Acme", "T-1002"], ["Attendee", "Company", None, "Ticket No."]),
    (["Team Lead", "Team Name", "Track"], ["Ed Fox", "Pixel Pirates", "AI"], ["Team Lead", "Team Name", "Track", None]),
    (["Email", "Phone", "Notes"], ["a@b.c", "123", "vegan"], [None, None, None, None]),
    (["Awardee", "Dept.", "Achievement", "UID"], ["Fay Gray", "Physics", "Best Poster", "U77"], ["Awardee", "Dept.", "Achievement", "UID"]),
    (["Full name (as on ID)", "School", "Category"], ["Gus Hill", "Hill School", "Junior"], ["Full name (as on ID)", "School", "Category", None]),
    (["Candidate", "Employer", "Certification", "Cert ID"], ["Hal Ito", "Initech", "Level 2", "C-9"], ["Candidate", "Employer", "Certification", "Cert ID"]),
    (["Name of winner", "Affiliation", "Place"], ["Ivy Jo", "Jo Labs", "2"], ["Name of winner", "Affiliation", "Place", None]),
    (["Ref", "Delegate", "Org"], ["R1", "Kai Lo", "Lo & Co"], ["Delegate", "Org", None, "Ref"]),
]
BRIEFS = ["Calm and academic, deep blue, understated", "Bold contemporary hackathon, orange and navy", "Traditional formal with gold accents",
          "Friendly workshop for kids, bright but still legible", "Minimal black and white conference", "Elegant gala dinner, burgundy"]
EVENT = EventFields(event_name="HackNova 2026", organisation="Tech Club", cert_type="Certificate of Participation", event_date="12 October 2026")


def score(pred: dict, gold: list):
    c = w = a = 0
    for t, g in zip(T, gold):
        p = (pred.get(t) or {}).get("column")
        if p == g:
            c += 1 if g is not None else 0   # null==null is not credited as a hit
        elif p is None:
            a += 1 if g is not None else 0
        else:
            w += 1
    attempted = sum(1 for t in T if (pred.get(t) or {}).get("column"))
    expected = sum(1 for g in gold if g is not None)
    return {"correct": c, "wrong": w, "abstained": a, "attempted": attempted, "gold_fields": expected}


def total(rs):
    return {k: sum(r[k] for r in rs) for k in rs[0]} if rs else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ai", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "evaluation_results.json"))
    a = ap.parse_args()
    res = {"model": os.environ.get("OLLAMA_MODEL", "gemma3:4b"), "mapping": {}, "design": {}}

    base = [score(ops.rule_based_mapping(h), g) for h, _, g in HELDOUT]
    res["mapping"]["rule_based"] = total(base)
    st = ollama.status()
    res["ollama_status"] = {k: st[k] for k in ("reachable", "model_installed", "error")}
    if a.skip_ai or not (st["reachable"] and st["model_installed"]):
        res["mapping"]["model"] = "not run: " + ("--skip-ai" if a.skip_ai else (st["error"] or "unavailable"))
        res["design"] = "not run"
    else:
        rows, fails, times = [], 0, []
        for h, row, g in HELDOUT:
            t = time.time()
            try:
                pred, meta = ops.suggest_mapping(h, [dict(zip(h, row))])
                rows.append(score(pred, g))
            except AIError as e:
                fails += 1
            times.append(round(time.time() - t, 1))
        res["mapping"]["model"] = {**(total(rows) if rows else {}), "calls_failed_validation_or_unavailable": fails,
                                   "seconds_per_call": times}
        # design
        from backend.app.schemas import DesignSpec
        from backend.app.services.rendering.html import PageData, RenderContext
        from backend.app.services.rendering.renderer import render_pdf
        first_ok = retried_ok = failed = 0
        viol, layouts, timings = [], [], []
        for i, brief in enumerate(BRIEFS):
            t = time.time()
            try:
                spec, meta = ops.generate_design(brief, Brand(), EVENT)
            except AIError:
                failed += 1
                timings.append(round(time.time() - t, 1))
                continue
            timings.append(round(time.time() - t, 1))
            first_ok += meta["attempts"] == 1
            retried_ok += meta["attempts"] == 2
            layouts.append((spec.layout_id, spec.palette.primary, spec.fonts.heading, spec.ornament))
            ctx = RenderContext(spec, EVENT, [PageData("Priya Sharma-Iyer", "Greenfield College", "First Place"),
                                              PageData("Konstantinos Papadopoulos-Lee")])
            r = render_pdf(ctx, {}, "eval")
            viol.append({"brief": brief, "geometry": [g["code"] for g in r.geometry],
                         "name_overflow": sum(f["overflow"] for f in r.fits)})
        res["design"] = {"briefs": len(BRIEFS), "valid_first_attempt": first_ok, "valid_after_retry": retried_ok, "failed": failed,
                         "distinct_designs": len(set(layouts)), "designs": layouts, "rendering_violations": viol,
                         "seconds_per_call_first_is_cold": timings,
                         "median_warm_seconds": statistics.median(timings[1:]) if len(timings) > 1 else None}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
