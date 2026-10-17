# Architecture note

```
Browser (React)  ──HTTP──▶  FastAPI (127.0.0.1)  ──▶  SQLite + data/projects/<id>/…
                                 │
                                 ├─ jobs.py       one worker thread, persisted states, cancel between 25-page chunks
                                 ├─ pipeline.py   intent snapshot → pre-checks → render → independent verify → artifacts
                                 ├─ rendering/    DesignSpec → trusted HTML → Chromium (Playwright) → PDF
                                 ├─ verification/ pdfplumber re-reads the PDF bytes; knows nothing about the HTML
                                 ├─ matching/     external PDF ↔ source rows (injective, order-independent)
                                 └─ ai/           Ollama on localhost; JSON-schema output, validated, one retry
```

**Design spec, not markup.** The model can only return an allowlisted spec (layout id, three font keys, two hex colours,
bounded spacing numbers, short draft wording using three placeholders). Pydantic validates it, wording may not contain
digits that are not already in your event fields, and `html.py` is the only place HTML is produced — every string is escaped.
Nothing from the model is executed, and no file paths or SVG are accepted.

**One renderer.** The preview, thumbnails and PDF all come from the same Chromium print path (A4 landscape, backgrounds on,
no headers/footers, local fonts via an in-memory route; every other request is aborted and reported). The page's own script
only fits names (shrinks within your min/max, optional two lines) and measures geometry; it never receives model output.

**Independent verification.** `verify_generated` takes PDF bytes + the immutable export intent. It checks page count,
extracts positioned characters, compares name / organisation / award zones and every fixed string, reconciles counts
(missing / unexpected / repeated), and — in blank mode — requires the name area to be empty and scans text and metadata for
recipient strings. Browser geometry (overlap, clipping, writing-area clearance, name fit) is a separate, complementary check.

**Staleness is content-addressed.** An artifact stores the SHA-256 of its intent (event fields, design, mapped rows, mapping,
mode, blank options, asset hashes). It is “out of date” whenever the current intent hashes differently. Restoring the inputs restores validity.
Cancelled or interrupted jobs never write an artifact; interrupted jobs are marked on restart and can simply be run again.

**Blank mode.** The blank intent carries no recipient rows at all (so none can reach the PDF, its metadata, or the report manifest).
The name area is a reserved rectangle; only the optional line may enter it.

## Supported / not supported
Supported: A4 landscape, one certificate per page, one template per batch, three flexible layouts, English UI, Latin-script
names (Unicode kept exactly; unsupported glyphs block), up to 100 certificates per batch benchmarked (limit configurable),
CSV/XLSX import, text-based PDFs for checking.
Not supported: scanned PDFs/OCR, multiple certificates per page, multi-template batches, CMYK/PDF-X/bleed, SVG logos, non-Latin
scripts (not tested), per-recipient ZIP export, digital signatures, identity verification, public verification pages, email sending, accounts, cloud sync.
