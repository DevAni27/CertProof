import io

from PIL import Image

from tests.conftest import make_project


def test_host_header_must_be_loopback(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403


def test_ids_cannot_traverse_paths(client):
    for bad in ("..", "..%2F..%2Fetc", "0123456789abcdeg", "x" * 40):
        assert client.get(f"/api/projects/{bad}").status_code in (404, 422)
    pid = make_project(client, [{"name": "A"}])
    assert client.get(f"/api/projects/{pid}/artifacts/..%2F..%2Fx/pdf").status_code in (404, 422)
    assert client.get(f"/api/projects/{pid}/assets/..%2F..%2F..%2Fetc%2Fpasswd").status_code in (404, 422)


def test_uploads_must_be_real_png_or_jpeg(client):
    pid = make_project(client, [{"name": "A"}])
    up = lambda name, b: client.post(f"/api/projects/{pid}/assets", files={"file": (name, b)}, data={"role": "logo"})
    assert up("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>').status_code == 422
    assert up("x.png", b"<html><script>alert(1)</script>").status_code == 422
    assert up("x.exe", b"MZ\x90\x00").status_code == 422
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    assert up("x.png", gif.getvalue()).status_code == 422                    # wrong real format, even with .png name
    ok = io.BytesIO()
    Image.new("RGB", (4, 4)).save(ok, "PNG")
    r = up("../../evil name?.png", ok.getvalue())
    assert r.status_code == 200 and "/" not in r.json()["filename"] and "?" not in r.json()["filename"]


def test_image_size_limits(client, monkeypatch):
    pid = make_project(client, [{"name": "A"}])
    monkeypatch.setenv("MAX_IMAGE_PIXELS", "100")
    b = io.BytesIO()
    Image.new("RGB", (20, 20)).save(b, "PNG")
    r = client.post(f"/api/projects/{pid}/assets", files={"file": ("a.png", b.getvalue())}, data={"role": "logo"})
    assert r.status_code == 422 and "pixels" in r.json()["detail"]


def test_row_limit_enforced_for_manual_entry(client, monkeypatch):
    monkeypatch.setenv("MAX_ROWS", "3")
    pid = make_project(client, None)
    r = client.put(f"/api/projects/{pid}/recipients", json={"paste": "a\nb\nc\nd"})
    assert r.status_code == 422


def test_delete_project_removes_files_and_rows(client):
    from backend.app import storage
    pid = make_project(client, [{"name": "Ann"}])
    d = storage.project_dir(pid)
    assert d.exists()
    assert client.delete(f"/api/projects/{pid}").json()["deleted"]
    assert not d.exists() and client.get(f"/api/projects/{pid}").status_code == 404


def test_renderer_blocks_unmanaged_network_requests(client):
    """Anything outside the managed local assets is aborted and reported."""
    from backend.app.schemas import DesignSpec, EventFields
    from backend.app.services.rendering import html as H
    from backend.app.services.rendering.renderer import render_pdf
    orig = H.build_document

    def sneaky(ctx, title):
        return orig(ctx, title).replace("</body>", '<img src="http://example.com/track.png"></body>')
    import backend.app.services.rendering.renderer as R
    R.build_document = sneaky
    try:
        res = render_pdf(H.RenderContext(DesignSpec(), EventFields(event_name="x", organisation="y"), [H.PageData(name="A")]), {}, "t")
    finally:
        R.build_document = orig
    assert any("example.com" in u for u in res.blocked_requests)
