"""Canonical renderer: trusted HTML -> Chromium (Playwright) -> PDF bytes.

Network is blocked except for explicitly managed local assets served from memory.
"""
from __future__ import annotations

import glob
import io
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pypdf import PdfReader, PdfWriter

from ...config import FONT_DIR, get_settings
from .html import BASE, PageData, RenderContext, build_document, font_files

CHUNK = 25


class Cancelled(Exception):
    pass


@dataclass
class RenderResult:
    pdf: bytes
    page_count: int
    fits: list[dict] = field(default_factory=list)
    geometry: list[dict] = field(default_factory=list)
    blocked_requests: list[str] = field(default_factory=list)


def _chromium_exe() -> Optional[str]:
    s = get_settings()
    if s.chromium_path:
        return s.chromium_path
    return None


def render_pdf(
    ctx: RenderContext,
    assets: dict[str, tuple[Path, str]],  # asset_id -> (path, mime)
    doc_title: str,
    cancel: Optional[threading.Event] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> RenderResult:
    import sys
    if sys.platform == "win32":
        # Playwright needs subprocess support, which only the Proactor loop has on Windows
        # (uvicorn --reload would otherwise leave the Selector policy active in this thread).
        import asyncio
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    from playwright.sync_api import sync_playwright

    ctx.asset_urls = {aid: f"{BASE}/asset/{aid}" for aid in assets}
    fonts = {fn: p.read_bytes() for fn, p in font_files(ctx.spec).items()}
    pages = ctx.pages
    chunks = [pages[i:i + CHUNK] for i in range(0, len(pages), CHUNK)] or [[]]
    writer = PdfWriter()
    fits: list[dict] = []
    geom: list[dict] = []
    blocked: list[str] = []
    offset = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_chromium_exe())
        try:
            for ci, chunk in enumerate(chunks):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                sub = RenderContext(ctx.spec, ctx.event, chunk, ctx.blank, ctx.asset_urls)
                html = build_document(sub, doc_title).encode("utf-8")
                bctx = browser.new_context(service_workers="block", accept_downloads=False)
                page = bctx.new_page()

                def handler(route, _request=None, html=html):
                    url = route.request.url
                    if url == f"{BASE}/doc.html":
                        route.fulfill(body=html, content_type="text/html; charset=utf-8")
                    elif url.startswith(f"{BASE}/fonts/") and url.rsplit("/", 1)[-1] in fonts:
                        route.fulfill(body=fonts[url.rsplit("/", 1)[-1]], content_type="font/ttf")
                    elif url.startswith(f"{BASE}/asset/") and url.rsplit("/", 1)[-1] in assets:
                        path, mime = assets[url.rsplit("/", 1)[-1]]
                        route.fulfill(body=path.read_bytes(), content_type=mime)
                    else:
                        blocked.append(url)
                        route.abort()

                page.route("**/*", handler)
                page.emulate_media(media="print")
                page.goto(f"{BASE}/doc.html", wait_until="load")
                page.evaluate("document.fonts.ready.then(()=>true)")
                page.evaluate("Promise.all([...document.images].map(i=>i.decode().catch(()=>0))).then(()=>true)")
                cf = page.evaluate("window.__bp.fitAll()")
                cg = page.evaluate("window.__bp.geometry()")
                for r in cf:
                    r["page"] += offset
                for r in cg:
                    if r["page"]:
                        r["page"] += offset
                fits += cf
                geom += cg
                pdf = page.pdf(width="297mm", height="210mm", print_background=True,
                               prefer_css_page_size=True, display_header_footer=False,
                               margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
                bctx.close()
                writer.append(PdfReader(io.BytesIO(pdf)))
                offset += len(chunk)
                if progress:
                    progress(ci + 1, len(chunks))
        finally:
            browser.close()
    writer.add_metadata({"/Title": doc_title, "/Producer": "CertProof", "/Creator": "CertProof"})
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()
    return RenderResult(data, len(PdfReader(io.BytesIO(data)).pages), fits, geom, blocked)
