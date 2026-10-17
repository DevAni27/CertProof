# AI evaluation

## What exists
`scripts/ai_eval.py` compares model-assisted mapping with a rule-based baseline on 12 held-out header sets (written by the tool's author — a smoke test, not a benchmark)
and measures design-schema validity (first attempt / after the one retry / failure), renders each valid design with the real renderer and counts layout violations, and records cold vs warm timings.
Correct, wrong and abstained are reported **separately**.

## Results so far
**Rule-based baseline (measured, 15 Oct 2026):** of 38 gold fields — 21 correct, 3 wrong, 15 abstained (24 attempted).
**Model (Gemma):** *not run.* No Ollama/Gemma was available in the build environment, so there are no model numbers, no valid-JSON rate, and no timings. Run:

```powershell
ollama list     # make sure the model is installed
.venv\Scripts\python.exe scripts\ai_eval.py      # writes docs\evaluation_results.json
```
The adapter's behaviour under bad output (invalid schema, invented columns, invented dates/numbers, markup, unreadable colours, timeouts, model missing, Ollama down) is covered by unit tests against a fake server — that shows the guard rails work, not that Gemma produces good designs.

## Guard rails (what a model can and cannot do)
Mapping: only real header names or null; each column and target used once; one retry with bounded feedback; otherwise a clear failure and the rule-based suggestion; always requires your confirmation.
Design: allowlisted fonts/layouts/colours/ornaments, bounded numbers, three placeholders only, no digits that are not already in your event fields, no markup, text colour contrast ≥ 4.5 on white (brand colours you set are kept with a warning instead).
A fallback template is labelled “Built-in starter”, never “AI-generated”. Traces (`data/ai_trace.jsonl`) hold operation, model id, timing and outcome — no names, briefs or prompts.
