"""Browser end-to-end checks of the main user flows against the real server (built frontend)."""
import glob
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "examples"
SHOTS = Path(os.environ.get("BP_SHOTS", "/tmp/bp-shots"))


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        pytest.skip("frontend not built")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "BATCHPROOF_DATA_DIR": str(tmp_path_factory.mktemp("e2e")), "BATCHPROOF_PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import httpx
    for _ in range(60):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health").status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()


@pytest.fixture(scope="module")
def page(server):
    SHOTS.mkdir(parents=True, exist_ok=True)
    exe = os.environ.get("BATCHPROOF_CHROMIUM_PATH") or None
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe)
        pg = b.new_page(viewport={"width": 1366, "height": 800})
        pg.set_default_timeout(60000)
        yield pg
        b.close()


def test_sample_to_checked_pdf(server, page):
    page.goto(server)
    page.get_by_role("button", name="See a sample project").click()
    expect(page.get_by_text("Sample data")).to_be_visible()
    expect(page.get_by_alt_text("Certificate preview")).to_be_visible()      # live preview, no button press
    page.screenshot(path=str(SHOTS / "01_design.png"))
    page.get_by_role("tab", name="Export").click()
    page.get_by_role("button", name="Generate PDF and run checks").click()
    expect(page.locator(".thumb")).to_have_count(7)
    page.locator(".thumb").nth(4).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.get_by_role("dialog").get_by_text("NAME_FONT_ADJUSTED")).to_be_visible()
    page.wait_for_function("document.querySelector('[role=dialog] img.cert').naturalWidth > 0")
    page.screenshot(path=str(SHOTS / "02_review_drawer.png"))
    page.get_by_role("button", name="Close").click()
    page.screenshot(path=str(SHOTS / "03_review_grid.png"), full_page=True)
    expect(page.get_by_role("link", name="Download PDF (DRAFT — not fully checked)")).to_be_visible()
    # acknowledge the font-size warning -> overall Checked
    page.locator(".thumb").nth(4).click()
    page.get_by_placeholder("Audit note (required) — why this is acceptable").fill("24pt is legible, checked by eye")
    page.get_by_role("button", name="Acknowledge").click()
    expect(page.get_by_role("dialog").get_by_text("Acknowledged")).to_be_visible()
    page.get_by_role("button", name="Close").click()
    expect(page.get_by_role("link", name="Download PDF", exact=True)).to_be_visible()


def test_blank_name_flow(server, page):
    page.goto(server)
    page.get_by_role("button", name="See a sample project").click()
    page.get_by_role("tab", name="Export").click()
    page.get_by_role("radio", name="Blank name — fill by hand").click()
    expect(page.get_by_text("Per-recipient “organisation” field")).to_be_visible()
    page.get_by_label("How many blank certificates? (1–100)").fill("3")
    page.get_by_role("checkbox", name="I confirm: export exactly 3 certificates").check()
    exp = page.get_by_role("button", name="Generate PDF and run checks")
    expect(exp).to_be_disabled()                                                  # per-recipient field policy not chosen
    page.locator("select").nth(0).select_option("omit")
    page.locator("select").nth(1).select_option("omit")
    expect(exp).to_be_enabled()
    page.screenshot(path=str(SHOTS / "04_blank_options.png"), full_page=True)
    exp.click()
    expect(page.get_by_text("Recipient matching:")).to_be_visible()
    expect(page.locator(".thumb")).to_have_count(3)
    expect(page.get_by_text("Blank #1")).to_be_visible()
    page.screenshot(path=str(SHOTS / "05_blank_review.png"), full_page=True)


def test_check_existing_batch(server, page):
    page.goto(server)
    page.get_by_role("button", name="Check an existing batch").click()
    page.locator("input[type=file]").first.set_input_files(str(EX / "recipients_sample.csv"))
    expect(page.get_by_role("heading", name="Column mapping")).to_be_visible()
    page.get_by_role("button", name="Suggest (rule-based)").click()
    page.get_by_role("button", name="Confirm mapping").click()
    expect(page.get_by_text("Mapping confirmed (rule based)")).to_be_visible()
    page.get_by_label("Certificate PDF").set_input_files(str(EX / "external_flawed.pdf"))
    expect(page.get_by_text("Click a line on the sample page")).to_be_visible()
    page.get_by_role("button", name="Run checks").click()
    expect(page.get_by_text("rows without a page")).to_be_visible()
    expect(page.get_by_text("MISSING_RECIPIENT").first).to_be_visible()
    page.screenshot(path=str(SHOTS / "06_check_result.png"), full_page=True)
    page.get_by_role("button", name="Details").nth(1).click()
    expect(page.get_by_role("dialog").get_by_text("Riverside College")).to_be_visible()
    img = page.get_by_role("dialog").locator("img.cert")
    expect(img).to_be_visible()
    page.wait_for_function("document.querySelector('[role=dialog] img.cert').naturalWidth > 0")
    expect(page.get_by_role("dialog").locator(".hl")).to_have_count(1)           # evidence rectangle is drawn on the page
    page.screenshot(path=str(SHOTS / "07_check_drawer.png"))


def test_live_preview_and_signatures(server, page):
    page.goto(server)
    page.get_by_role("button", name="Create certificates →").first.click()
    page.get_by_placeholder("Northlight Design Summit 2026").fill("Autumn Showcase 2026")
    page.get_by_placeholder("Northlight Collective").fill("Test Collective")
    page.get_by_placeholder("12 October 2026").fill("3 November 2026")
    img = page.get_by_alt_text("Certificate preview")
    expect(img).to_be_visible()
    first = img.get_attribute("src")
    # a style change refreshes the preview by itself
    page.get_by_role("button", name="Midnight").click()
    page.wait_for_function("(s) => document.querySelector('img.cert') && document.querySelector('img.cert').getAttribute('src') !== s", arg=first)
    # zero signatures by default; add two, then remove one
    expect(page.get_by_text("No signature lines on this certificate.")).to_be_visible()
    page.get_by_role("button", name="+ Add a signature").click()
    page.get_by_role("button", name="+ Add a signature").click()
    expect(page.get_by_text("Signature 2")).to_be_visible()
    page.get_by_role("button", name="Remove").first.click()
    expect(page.get_by_text("Signature 2")).to_have_count(0)
    expect(page.get_by_text("All changes saved")).to_be_visible()
    page.screenshot(path=str(SHOTS / "08_design_live.png"), full_page=True)
