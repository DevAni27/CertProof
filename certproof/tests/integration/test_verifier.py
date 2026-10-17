"""The verifier must catch real defects in real PDF bytes, independent of what the app intended."""
import io

from pypdf import PdfReader, PdfWriter

from backend.app.config import get_settings
from backend.app.pipeline import _render_ctx, _verify_intent, build_intent
from backend.app.services.rendering.html import PageData
from backend.app.services.rendering.renderer import render_pdf
from backend.app.services.verification.generated import verify_generated
from tests.conftest import make_project

ROWS = [{"name": "Ann Lee", "organisation": "Alpha"}, {"name": "Bo Kim", "organisation": "Beta"},
        {"name": "Cy Day", "organisation": "Gamma"}]


def setup(client, **kw):
    from backend.app import storage
    pid = make_project(client, ROWS, **kw)
    p = storage.get_project(pid)
    intent = build_intent(p)
    ctx = _render_ctx(p, intent)
    return p, intent, ctx


def codes(issues):
    return sorted(i.code for i in issues)


def render(ctx, p):
    return render_pdf(ctx, {}, "t").pdf


def test_clean_pdf_passes(client):
    p, intent, ctx = setup(client)
    issues, _ = verify_generated(render(ctx, p), _verify_intent(p, intent, ctx), 300)
    assert issues == []


def test_repeated_output_replacing_another_recipient(client):
    p, intent, ctx = setup(client)
    ctx.pages[1] = PageData("Ann Lee", "Beta")           # Bo Kim replaced by a repeat of Ann Lee
    issues, _ = verify_generated(render(ctx, p), _verify_intent(p, intent, ctx), 300)
    # _verify_intent was built from the corrupted ctx pages? no: intent carries the immutable manifest
    assert "DUPLICATE_OUTPUT_RECORD" in codes(issues) and "MISSING_RECIPIENT" in codes(issues) and "FIELD_MISMATCH" in codes(issues)
    assert next(i for i in issues if i.code == "MISSING_RECIPIENT").expected == "Bo Kim"


def test_correct_name_wrong_organisation_in_actual_pdf(client):
    p, intent, ctx = setup(client)
    ctx.pages[0] = PageData("Ann Lee", "Omega")
    issues, _ = verify_generated(render(ctx, p), _verify_intent(p, intent, ctx), 300)
    [i] = [x for x in issues if x.code == "FIELD_MISMATCH"]
    assert i.field == "organisation" and i.expected == "Alpha" and i.actual == "Omega" and i.page == 1


def test_wrong_event_date_in_actual_pdf(client):
    p, intent, ctx = setup(client)
    wrong = ctx.event.model_copy(update={"event_date": "13 October 2026"})
    ctx.event = wrong                                       # PDF is drawn with the wrong date ...
    pdf = render(ctx, p)
    ctx.event = p.event                                     # ... but the confirmed fields say 12 October
    issues, _ = verify_generated(pdf, _verify_intent(p, intent, ctx), 300)
    assert codes(issues).count("FIXED_TEXT_MISMATCH") == 3
    i = issues[0]
    assert "12 October 2026" in i.expected and "13 October 2026" in i.actual and i.rect


def test_missing_page_changes_count(client):
    p, intent, ctx = setup(client)
    r = PdfReader(io.BytesIO(render(ctx, p)))
    w = PdfWriter()
    for pg in list(r.pages)[:2]:
        w.add_page(pg)
    b = io.BytesIO()
    w.write(b)
    issues, _ = verify_generated(b.getvalue(), _verify_intent(p, intent, ctx), 300)
    assert "PAGE_COUNT_MISMATCH" in codes(issues) and "MISSING_RECIPIENT" in codes(issues)


def test_blank_verifier_catches_text_in_name_area(client):
    p, intent, ctx = setup(client)
    pdf = render(ctx, p)                                     # a PERSONALISED pdf offered as blank
    from backend.app import storage
    client.patch(f"/api/projects/{p.id}", json={"output_mode": "blank_name", "blank": {"copies": 3}})
    p2 = storage.get_project(p.id)
    bi = build_intent(p2)
    vi = _verify_intent(p2, bi, _render_ctx(p2, bi))
    vi["stale_strings"] = ["Ann Lee", "Bo Kim", "Cy Day"]
    issues, summary = verify_generated(pdf, vi, 300)
    assert "STALE_RECIPIENT_IN_BLANK_OUTPUT" in codes(issues)
    assert summary["recipient_matching"] == "not_applicable"


def test_blank_verifier_catches_recipient_in_metadata(client):
    p, intent, ctx = setup(client)
    from backend.app import storage
    client.patch(f"/api/projects/{p.id}", json={"output_mode": "blank_name", "blank": {"copies": 3}})
    p2 = storage.get_project(p.id)
    bi = build_intent(p2)
    bctx = _render_ctx(p2, bi)
    r = PdfReader(io.BytesIO(render_pdf(bctx, {}, "t").pdf))
    w = PdfWriter(clone_from=r)
    w.add_metadata({"/Title": "Certificate for Ann Lee"})
    b = io.BytesIO()
    w.write(b)
    vi = _verify_intent(p2, bi, bctx)
    vi["stale_strings"] = ["Ann Lee"]
    issues, _ = verify_generated(b.getvalue(), vi, 300)
    assert [i.field for i in issues if i.code == "STALE_RECIPIENT_IN_BLANK_OUTPUT"] == ["metadata"]


def test_corrupt_and_scanned_pdfs_are_rejected_with_actionable_messages(client):
    import pytest
    from backend.app.services.verification.pdf_extract import PdfProblem, extract_pages, require_text_layer
    from tests.conftest import EX
    with pytest.raises(PdfProblem) as e:
        extract_pages((EX / "external_corrupt.pdf").read_bytes(), 300)
    assert e.value.code == "CORRUPT_PDF"
    with pytest.raises(PdfProblem) as e:
        extract_pages(b"not a pdf at all", 300)
    pages = extract_pages((EX / "external_scanned.pdf").read_bytes(), 300)
    with pytest.raises(PdfProblem) as e:
        require_text_layer(pages)
    assert e.value.code == "NO_TEXT_LAYER" and "OCR" in e.value.message
