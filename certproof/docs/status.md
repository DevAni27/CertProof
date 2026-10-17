# What was built, tested, and not verified (15 Oct 2026)

## Built (all required MVP items)
Design generation + editing, manual/paste/CSV/XLSX recipients with worksheet and header-row selection, confirmed mapping,
personalised **and blank-name** PDFs, batch review grid with search/filters/details drawer, independent post-render
verification, external searchable-PDF checking with field-zone marking and manual resolution, JSON/CSV reports, local save/reopen/delete,
sample project, example data and fixtures, Windows setup instructions.
Not built (listed as “after the core works” or out of scope in the handoff): per-recipient ZIP, optional reference image, resumable partial exports,
hosted demo, sponsor instrumentation (no Sentry, Mastra, Backboard, Entire/DevRelay, Copilot, ElevenLabs, .tech/Render/DigitalOcean hosting was added or used).
A lightweight in-browser editing preview was not built: the preview is always the canonical Chromium render (a few seconds per update).

## Automated tests actually run — 91 collected, 91 passed (Linux, Python 3.13, Chromium 141, 2 CPUs)
* `tests/unit` (39): normalisation, CSV/XLSX import rules, matching/association cases, AI adapter against a **fake** Ollama server.
* `tests/integration` (49): valid batch with logo/signature (logo proportion measured in the PDF), diacritics/punctuation/HTML-like names rendered literally,
  long-name adjustment + acknowledgement, name that cannot fit (one and two lines), unsupported glyphs, stale invalidation after every kind of edit,
  cancel and interrupted jobs, blank mode (line on/off measured from rendered pixels, N copies, no recipient leakage into text/metadata/report/files,
  per-recipient field policy, obstructed writing area), verifier against deliberately altered PDFs (repeated recipient replacing another, wrong organisation, wrong date,
  missing page, recipient text/metadata in a “blank” PDF), external PDFs made with ReportLab (clean, reordered, flawed-with-equal-page-count, scanned, corrupt, oversize, too many pages,
  shared names, report CSV formula-injection sanitising), upload/path/host security checks.
* `tests/e2e` (3): real browser through the built UI: sample → preview → export → review drawer → acknowledge; blank-name flow; check-existing-batch with evidence highlight.
Visual review: first, longest-name, last and blank certificates of `examples/output/*.pdf` were inspected as images.

## Not verified — please do these before relying on it
1. **Windows 11 / PowerShell.** Instructions are written for it and the renderer sets the Proactor loop policy there, but nothing has run on Windows.
2. **Real Gemma / Ollama.** The model path is only exercised against a fake server (validation, retry, timeout, missing model, unavailable). Design quality, mapping accuracy,
   latency and VRAM fit on an RTX 3060 6 GB are **unknown**. Run `scripts/ai_eval.py` and record what it prints. Note: `gemma3:4b` may follow the JSON schema imperfectly; the retry and manual fallback exist for that reason.
3. **Real users.** No first user, no timing with a real organiser, no pricing evidence.
4. **Offline operation.** Designed so (blocked renderer network, bundled fonts, localhost-only Ollama) and the renderer’s blocking is tested, but a full disconnected run was not done.
5. **Non-Latin names, accessibility audit, large screens/phones, browsers other than Chromium.** Not tested. Keyboard handling (focus order, Escape to close drawers) was not tested.
6. **Font licences:** Lora and Poppins OFL text files still need to be added (see THIRD_PARTY_NOTICES.md).

## Known limitations
* Preview/export render in a fresh Chromium per job (~1–2 s overhead).
* Cancellation takes effect between 25-page render chunks and between PDF pages while reading; an in-flight Chromium chunk finishes first. A model call cancels mid-stream.
* Fixed-text checks ignore whitespace (so wrapped lines pass) and are containment checks; name checks are exact after NFC/whitespace normalisation.
* Hyphenated names that wrap after the hyphen are re-joined without a space when read back from the PDF.
* The external-PDF checker compares only zones you mark; text elsewhere on the page is not examined except via the fixed-text list.
* AI suggestions for PDF fields (`suggest_pdf_fields`) exist in the backend but are not wired into the UI; zone suggestion in the UI is deterministic (it finds the line equal to a source name).
* Per-rectangle “mark an area” on the PDF is done by clicking detected text lines (the zone becomes a full-width band around the line), not by free drawing.
