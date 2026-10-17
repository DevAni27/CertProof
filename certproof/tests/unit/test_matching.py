"""Matching/verification logic on synthetic extracted pages (no PDF needed)."""
from backend.app.schemas import ConfirmedMapping, SourceRow
from backend.app.services.matching.external import check_external
from backend.app.services.verification.pdf_extract import Ch, ExtractedPage

W, H = 842.0, 595.0
ZONES = {"name": [0.1, 0.30, 0.9, 0.40], "organisation": [0.1, 0.42, 0.9, 0.48], "award": [0.1, 0.50, 0.9, 0.56]}
MAP = ConfirmedMapping(name="N", organisation="O", award="A", recipient_id="I")


def page(i, name, org="", award="", extra=""):
    cs = []

    def put(text, y):
        x = 100.0
        for ch in text:
            cs.append(Ch(ch, x, x + 8, y, y + 12, 12))
            x += 8
    put(name, 0.35 * H)
    if org:
        put(org, 0.45 * H)
    if award:
        put(award, 0.53 * H)
    if extra:
        put(extra, 0.8 * H)
    return ExtractedPage(i, W, H, cs)


def rows(*spec):
    return [SourceRow(row_id=f"r{i+1}", sheet="s", row_index=i + 2, cells={"N": n, "O": o, "A": a, "I": idv})
            for i, (n, o, a, idv) in enumerate(spec)]


def run(rs, pgs, fixed=(), res=None):
    return check_external(rs, MAP, pgs, ZONES, list(fixed), res)


def codes(issues):
    return sorted(i.code for i in issues)


def test_valid_batch_has_no_issues_and_correct_associations():
    rs = rows(("Ann Lee", "X", "1st", "1"), ("Bo Kim", "Y", "2nd", "2"))
    issues, assoc, *_ = run(rs, [page(1, "Ann Lee", "X", "1st"), page(2, "Bo Kim", "Y", "2nd")])
    assert issues == [] and assoc[1].row_id == "r1" and assoc[2].row_id == "r2"


def test_reordered_pages_do_not_cause_false_mismatches():
    rs = rows(("Ann Lee", "X", "", ""), ("Bo Kim", "Y", "", ""), ("Cy Day", "Z", "", ""))
    issues, assoc, *_ = run(rs, [page(1, "Cy Day", "Z"), page(2, "Ann Lee", "X"), page(3, "Bo Kim", "Y")])
    assert issues == [] and [assoc[i].row_id for i in (1, 2, 3)] == ["r3", "r1", "r2"]


def test_missing_recipient_and_unexpected_page_even_when_page_counts_match():
    rs = rows(("Ann Lee", "", "", ""), ("Bo Kim", "", "", ""), ("Cy Day", "", "", ""))
    issues, *_ = run(rs, [page(1, "Ann Lee"), page(2, "Cy Day"), page(3, "Xavier Unknown")])
    assert len(rs) == 3 == 3
    assert codes(issues) == ["MISSING_RECIPIENT", "UNEXPECTED_PAGE"]
    assert next(i for i in issues if i.code == "MISSING_RECIPIENT").expected == "Bo Kim"


def test_repeated_page_does_not_satisfy_two_rows():
    rs = rows(("Ann Lee", "", "", ""), ("Bo Kim", "", "", ""))
    issues, *_ = run(rs, [page(1, "Ann Lee"), page(2, "Ann Lee")])
    assert codes(issues) == ["DUPLICATE_OUTPUT_RECORD", "MISSING_RECIPIENT"]


def test_correct_name_wrong_organisation():
    rs = rows(("Ann Lee", "Alpha College", "", ""))
    issues, *_ = run(rs, [page(1, "Ann Lee", "Beta College")])
    [i] = issues
    assert i.code == "FIELD_MISMATCH" and i.field == "organisation" and i.expected == "Alpha College" and i.actual == "Beta College"


def test_changed_name_is_suggested_never_silently_passed():
    rs = rows(("Wei Chen", "", "", ""))
    issues, assoc, *_ = run(rs, [page(1, "Wei Chenn")])
    assert codes(issues) == ["FIELD_MISMATCH"]          # not also UNEXPECTED_PAGE / MISSING_RECIPIENT
    assert assoc[1].state == "suggested" and assoc[1].row_id is None


def test_case_and_accent_changes_are_mismatches():
    for shown in ("jose nunez", "Jose Nunez", "JOSÉ NÚÑEZ"):
        issues, *_ = run(rows(("José Núñez", "", "", "")), [page(1, shown)])
        assert issues, shown


def test_two_legitimate_recipients_sharing_a_name_need_manual_resolution():
    rs = rows(("Sam Lee", "", "", "1"), ("Sam Lee", "", "", "2"))
    issues, assoc, *_ = run(rs, [page(1, "Sam Lee"), page(2, "Sam Lee")])
    assert codes(issues) == ["AMBIGUOUS_PAGE_MATCH", "AMBIGUOUS_PAGE_MATCH"]
    assert all(a.state == "ambiguous" for a in assoc.values())
    # not reported as missing while the ambiguity is unresolved
    assert "MISSING_RECIPIENT" not in codes(issues)


def test_shared_name_resolved_by_secondary_evidence():
    rs = rows(("Sam Lee", "Alpha", "", ""), ("Sam Lee", "Beta", "", ""))
    issues, assoc, *_ = run(rs, [page(1, "Sam Lee", "Beta"), page(2, "Sam Lee", "Alpha")])
    assert issues == [] and assoc[1].row_id == "r2" and assoc[2].row_id == "r1"
    assert assoc[1].method == "name+secondary"


def test_shared_name_resolved_by_id_zone():
    zones = {**ZONES, "recipient_id": [0.1, 0.60, 0.9, 0.66]}
    rs = rows(("Sam Lee", "", "", "A1"), ("Sam Lee", "", "", "B2"))
    p1 = page(1, "Sam Lee")
    for ch, x in zip("B2", (100.0, 108.0)):
        p1.chars.append(Ch(ch, x, x + 8, 0.63 * H, 0.63 * H + 12, 12))
    issues, assoc, *_ = check_external(rs, MAP, [p1], zones, [], None)
    assert assoc[1].row_id == "r2" and assoc[1].method == "id"


def test_manual_resolution_is_honoured():
    rs = rows(("Sam Lee", "", "", "1"), ("Sam Lee", "", "", "2"))
    issues, assoc, *_ = run(rs, [page(1, "Sam Lee"), page(2, "Sam Lee")], res={1: "r2", 2: "r1"})
    assert issues == [] and assoc[1].method == "manual"


def test_wrong_fixed_text_found_per_page():
    rs = rows(("Ann Lee", "", "", ""))
    issues, *_ = run(rs, [page(1, "Ann Lee", extra="Held on 12 November 2026")], fixed=["12 October 2026"])
    assert codes(issues) == ["FIXED_TEXT_MISMATCH"]
    issues, *_ = run(rs, [page(1, "Ann Lee", extra="Held on 12 October 2026")], fixed=["12 October 2026"])
    assert issues == []


def test_wrapped_whitespace_is_normalised_but_punctuation_is_not():
    issues, *_ = run(rows(("Anna Maria", "", "", "")), [page(1, "Anna  Maria")])
    assert issues == []
    issues, *_ = run(rows(("O'Brien", "", "", "")), [page(1, "OBrien")])
    assert issues


def test_unreadable_page_is_needs_review_not_a_pass():
    bad = page(1, "Ann Lee")
    bad.chars[0].t = "�"
    issues, assoc, *_ = run(rows(("Ann Lee", "", "", "")), [bad])
    assert "PDF_EXTRACTION_UNRELIABLE" in codes(issues) and assoc[1].state == "unreliable"
    empty = ExtractedPage(1, W, H, [])
    issues, assoc, *_ = run(rows(("Ann Lee", "", "", "")), [empty])
    assert "PDF_EXTRACTION_UNRELIABLE" in codes(issues)


def test_source_row_problems_are_reported():
    rs = rows(("Ann Lee", "X", "", "1"), ("", "X", "", "2"), ("Ann Lee", "X", "", "1"), ("Bo", "", "", "1"))
    issues, *_ = run(rs, [])
    c = codes(issues)
    assert "MISSING_SOURCE_VALUE" in c and "DUPLICATE_SOURCE_ROW" in c and "CONFLICTING_RECIPIENT_ID" in c
