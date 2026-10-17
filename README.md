# CertProof

Describe an event, add your branding and recipients, and get a **checked** batch of printable certificates — or export
certificates with an **empty name area to fill in by hand**. You can also **check a certificate batch made elsewhere**
(spreadsheet + searchable PDF) for missing, repeated, unexpected and altered certificates.

* Local-first, single user. No account, no cloud database, no paid API. Recipient lists and signature images stay on your computer.
* A local open-weight model (default `gemma3:4b` via [Ollama](https://ollama.com)) *proposes* a design and a column mapping.
  Everything that matters afterwards — rendering, matching, verification — is deterministic code. The app works without the model.
* The PDF is the print master. After rendering, a separate verifier re-reads the **actual PDF bytes** and compares what is printed with what you confirmed.

> **Status (15 Oct 2026).** Built and tested on Linux (Python 3.13, Chromium 141). **Not yet run on Windows 11, and not yet run against a real Gemma model** —
> the AI adapter is tested against a fake Ollama server only. See [docs/status.md](docs/status.md) for exactly what was and was not verified.

## Quick start (Windows 11, PowerShell)

No activation script is needed; call the venv's Python directly.

```powershell
cd <this folder>                      # the folder containing serve.py
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m playwright install chromium    # one-time browser download (needs internet)
ollama list                                                # optional: confirm gemma3:4b is installed
.venv\Scripts\python.exe serve.py
```

Open **http://127.0.0.1:8000**. Stop with **Ctrl+C** in that window. The UI is pre-built (`frontend/dist`), so Node is not needed to run it.

Linux / WSL: same, with `.venv/bin/python`. If `pip install -r requirements.lock.txt` complains about a version, use `requirements.txt` instead.

### Optional: local AI
```powershell
ollama serve            # if it is not already running
ollama pull gemma3:4b   # only if `ollama list` does not show it; CertProof never downloads models itself
```
Use another installed model with `OLLAMA_MODEL=...` (copy `.env.example` to `.env`). The home page shows whether Ollama and the model are reachable.
The model is not kept loaded forever (`OLLAMA_KEEP_ALIVE`, default 2 min); press **Unload model from memory** on the home page or run `ollama stop gemma3:4b` to free VRAM immediately.
Gemma 3 4B has not been timed on a 6 GB GPU here; expect the first call to be slow while the model loads.

### Offline use
Needs internet **once** for: Python packages, the Chromium download, and Ollama model weights. After that the app makes no network requests:
fonts are bundled, the renderer blocks every request except its own in-memory assets, and Ollama is called on localhost.

## Using it

1. **Home** → *New certificate project*, *Load the sample project* (synthetic data, labelled DEMO), or *Check an existing batch*.
2. **Design**: type the event details (date is printed exactly as typed), upload a PNG/JPEG logo and optional signature images, pick brand colours,
   then *Generate design with local AI* or start from one of three templates (modern academic / formal bordered / contemporary event). Edit anything; manual edits win. Logos are placed as-is and never stretched or redrawn.
3. **Recipients**: import CSV/XLSX (choose worksheet and header row), paste names, or type rows. Review and **confirm** the column mapping (rule-based or AI suggestion — never applied automatically).
4. **Export**: choose **Personalised names** or **Blank name — fill by hand**.
   * Blank mode needs no recipients. Choose copies (1–100, you must confirm the number), a handwriting line on/off, and the writing-area size (default 120 × 18 mm). Per-recipient fields (organisation, award) must each be set to *omit*, *fixed text* or *extra handwriting area* — they are never inherited from a recipient.
   * Print the PDF at **Actual size / 100%** to keep the writing-area dimensions.
5. **Batch review**: thumbnails, search, filters, and a details drawer showing page, source row, expected vs. found text and the next action. Download the PDF and the JSON/CSV report. Warnings can be acknowledged with an audit note; errors cannot.

Status words: **Checked**, **Needs review**, **Blocked**, **Not checked**, **Not applicable**. *Checked* means the implemented checks passed against the inputs you confirmed. It does **not** certify identity, that the event happened, who may sign, the spelling you supplied, or legal validity.
Changing the design, source, mapping, event details or output mode marks earlier previews/exports as **out of date**.

### Check an existing batch
Upload the spreadsheet, confirm the mapping, upload a **searchable** PDF (one certificate per page, one recipient name per certificate), click the lines on page 1 that hold the name (and optional organisation/award/ID), optionally list fixed text that must appear on every page (e.g. the date), and run the checks.
Scanned/image-only PDFs are rejected (OCR is out of scope). A searchable PDF can still extract badly; unreadable pages show *Needs review*, never a pass.
Matching ignores page order, never lets one source row satisfy two pages, treats repeated names as unresolved until you choose a row, and only *suggests* near-matches (`Wei Chenn` vs `Wei Chen` is a mismatch, not a pass). Equal page counts are never treated as evidence.

## Tests
```powershell
.venv\Scripts\python.exe -m pytest                  # everything (needs Chromium installed; e2e needs frontend/dist)
.venv\Scripts\python.exe -m pytest tests/unit       # fast, no browser
.venv\Scripts\python.exe -m pytest tests/integration tests/e2e
.venv\Scripts\python.exe scripts\benchmark.py       # 100-certificate timing on your machine
.venv\Scripts\python.exe scripts\ai_eval.py         # needs Ollama + model; compares model vs rule-based baseline
.venv\Scripts\python.exe examples\make_fixtures.py  # rebuild example CSV/XLSX/PDF fixtures
```
Rebuild the UI (optional): `cd frontend; npm ci; npm run build`. Development: `npm run dev` (port 5173, proxies `/api` to 8000).

## Configuration
See `.env.example`: `BATCHPROOF_DATA_DIR`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_S`, `OLLAMA_KEEP_ALIVE`, `MAX_UPLOAD_MB`, `MAX_IMAGE_PIXELS`, `MAX_PDF_PAGES`, `MAX_ROWS`, `MAX_BLANK_COPIES`. Data (SQLite, uploads, PDFs, local AI trace without names or prompts) lives in `data/` — delete a project in the UI to remove its files.

## Troubleshooting
| Symptom | Fix |
| --- | --- |
| `Executable doesn't exist ... chromium` | Run `.venv\Scripts\python.exe -m playwright install chromium`. |
| Export fails with `NotImplementedError` (Windows) | Start with `serve.py`, not `uvicorn --reload`. |
| “Ollama is not reachable” | Start `ollama serve`; check `OLLAMA_BASE_URL`. Everything else still works manually. |
| “Model 'gemma3:4b' is not installed” | `ollama pull gemma3:4b` or set `OLLAMA_MODEL` to an installed model. |
| AI design fails validation twice | Use a template (labelled *Built-in starter*, never “AI-generated”); try a shorter brief. |
| CSV rejected as not UTF-8 | Re-save as “CSV UTF-8”. CertProof will not guess an encoding because that corrupts names. |
| `UNSUPPORTED_GLYPH` | The bundled fonts cannot draw that character (Latin scripts only for now). Names are never transliterated for you. |
| `NAME_OVERFLOW` | Allow two-line names in the design, lower the minimum size, or widen the name area. |
| Port 8000 busy | `BATCHPROOF_PORT=8001`. |

## Repository map
```
backend/app/        FastAPI app, storage (SQLite + folders), jobs, export pipeline
  services/rendering   layouts, trusted HTML builder, Playwright renderer, glyph check
  services/verification independent PDF reader + generated-output checks
  services/matching    source checks + external-PDF association
  services/imports     CSV/XLSX
  services/ai          Ollama client + design/mapping/field operations (validated, retried once)
backend/fonts/      bundled OFL fonts      frontend/   React + TypeScript + Vite (dist/ is pre-built)
tests/              unit · integration · e2e   examples/  sample data, fixtures, output   docs/  notes
```
More: [docs/architecture.md](docs/architecture.md) · [docs/status.md](docs/status.md) · [docs/evaluation.md](docs/evaluation.md) · [docs/benchmark.md](docs/benchmark.md) · [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
