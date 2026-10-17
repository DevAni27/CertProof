"""Product-level behaviour: any number of signatories, every layout verifies, preview works before recipients exist."""
import pytest
from tests.conftest import codes, export_ok, make_project, pdf_bytes

ROWS = [{"name": "Priya Sharma-Iyer"}, {"name": "José Ñúñez"}]


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4])
def test_any_number_of_signatories_exports_and_checks(client, n):
    sigs = [{"name": f"Signer {i+1}", "title": f"Role {i+1}"} for i in range(n)]
    pid = make_project(client, ROWS, signatories=sigs)
    j, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", codes(a)
    assert a["pages"] == 2


@pytest.mark.parametrize("layout", ["formal", "academic", "event", "luxe"])
def test_every_layout_passes_independent_check(client, layout):
    pid = make_project(client, ROWS, layout=layout)
    j, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", (layout, codes(a))


def test_luxe_blank_mode_has_empty_name_area(client):
    pid = make_project(client, None, mode="blank_name", layout="luxe")
    client.patch(f"/api/projects/{pid}", json={"blank": {"copies": 2, "confirmed_copies": 2, "line": True}})
    j, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", codes(a)


def test_five_signatories_rejected(client):
    pid = make_project(client, ROWS)
    r = client.patch(f"/api/projects/{pid}", json={"event": {"event_name": "x", "organisation": "y", "event_date": "z",
                     "signatories": [{"name": str(i)} for i in range(5)]}})
    assert r.status_code == 422


def test_preview_works_before_any_recipients_and_is_marked_sample(client):
    pid = make_project(client, None)
    r = client.post(f"/api/projects/{pid}/preview", json={})
    assert r.status_code == 200, r.text
    assert r.json().get("sample") is True
    png = client.get(f"/api/projects/{pid}/artifacts/{r.json()['artifact_id']}/preview.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    # the sample is never exportable
    assert client.post(f"/api/projects/{pid}/export").status_code in (409, 422)


# ---- custom (AI-composed) designs: every building block must stay verifiable -----------------------------------
import itertools

OPTS = {"frame": ["none", "single", "double", "triple", "rounded", "thick_thin"],
        "corners": ["none", "flourish", "triangles", "quarter_circles", "rings", "brackets"],
        "band": ["none", "left", "right", "top", "bottom", "top_bottom", "left_right"],
        "pattern": ["none", "rosette", "dots", "stripes", "arcs", "grid", "waves"],
        "divider": ["none", "line", "diamond", "dots", "double"]}


def _custom(client, pid, comp, palette=None):
    d = client.post(f"/api/projects/{pid}/design/fallback", json={"layout": "formal"}).json()
    d["layout_id"] = "custom"
    d["composition"] = {**d["composition"], **comp}
    if palette:
        d["palette"] = {**d["palette"], **palette}
    assert client.put(f"/api/projects/{pid}/design", json=d).status_code == 200, d
    return d


@pytest.mark.parametrize("key", list(OPTS))
def test_every_building_block_passes_independent_check(client, key):
    pid = make_project(client, ROWS, signatories=[{"name": f"S{i}", "title": f"T{i}"} for i in range(3)])
    for val in OPTS[key]:
        _custom(client, pid, {key: val, "corners": "triangles" if key != "corners" else val, "band": "left" if key != "band" else val})
        j, a = export_ok(client, pid)
        assert a["report"]["completion"] == "checked", (key, val, codes(a))


def test_dark_gradient_four_signatories_everything_on(client):
    pid = make_project(client, ROWS, signatories=[{"name": f"S{i}", "title": f"T{i}"} for i in range(4)])
    _custom(client, pid, {"background": "gradient", "background_color2": "#18232f", "frame": "triple", "corners": "rings", "band": "left_right",
                          "pattern": "waves", "divider": "double", "name_italic": True},
            {"background": "#0f1720", "text": "#e8edf3", "primary": "#7fe0d4", "accent": "#f0a35c"})
    j, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", codes(a)


def test_custom_design_blank_name_mode_keeps_area_clear(client):
    pid = make_project(client, None, mode="blank_name")
    client.patch(f"/api/projects/{pid}", json={"blank": {"copies": 2, "confirmed_copies": 2, "line": True}})
    _custom(client, pid, {"pattern": "rosette", "corners": "quarter_circles", "frame": "rounded", "band": "top_bottom"})
    j, a = export_ok(client, pid)
    assert a["report"]["completion"] == "checked", codes(a)


def test_unreadable_text_colour_is_corrected_at_render_time(client):
    """Even a hand-edited or corrupted palette cannot produce unreadable text on the page."""
    from backend.app.schemas import DesignSpec
    from backend.app.services.rendering.html import _contrast, theme_colours
    spec = DesignSpec(layout_id="custom", palette={"primary": "#fafafa", "accent": "#fdfdfd", "text": "#ffffff", "background": "#ffffff"})
    t = theme_colours(spec)
    assert _contrast(t["fg"], "#ffffff") >= 4.5 and _contrast(t["head"], "#ffffff") >= 4.5 and _contrast(t["accent"], "#ffffff") >= 3.0
