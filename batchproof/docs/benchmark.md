# Benchmark (measured, not estimated)

`scripts/benchmark.py`, run on **15 Oct 2026 in the cloud build container** — Linux, Python 3.13, Chromium 141, **2 CPUs, 8 GB RAM, no GPU**.
This is *not* the target laptop; run the script on your machine and replace these numbers.

| Job (100 pages, formal layout, logo + signature) | Wall-clock | Result |
| --- | --- | --- |
| Personalised, first run | 7.8 s | 100 pages, Checked, 0 errors, 0 warnings |
| Personalised, second run | 8.0 s | same |
| Blank name × 100, line on | 6.9 s | 100 pages, Checked |

The time covers canonical rendering (4 chunks of ≤25 pages), the independent PDF re-read and checks, thumbnails and reports. It excludes any AI call (the model is called once per
design/mapping request, never per certificate). **Warm/cold model inference was not measured** because no Ollama/Gemma was available here.
