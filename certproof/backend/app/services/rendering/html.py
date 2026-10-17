"""Turns a validated DesignSpec + confirmed fields into trusted HTML/CSS.

The model never emits markup: every string is escaped, every colour/font/size is
validated by the schema before it reaches this module.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import Optional

from ...config import FONT_DIR
from ...schemas import BlankOptions, DesignSpec, EventFields
from .layouts import PAGE_H, PAGE_W, geometry, signatory_rects

FONT_FACES = {
    "lora": [("Lora-Variable.ttf", "normal", "400 700"), ("Lora-Italic-Variable.ttf", "italic", "400 700")],
    "inter": [("Inter-Regular.otf", "normal", "400"), ("Inter-Medium.otf", "normal", "500"),
              ("Inter-SemiBold.otf", "normal", "600"), ("Inter-Bold.otf", "normal", "700")],
    "poppins": [("Poppins-Regular.ttf", "normal", "400"), ("Poppins-Medium.ttf", "normal", "500"),
                ("Poppins-Bold.ttf", "normal", "700")],
}
FALLBACK_STACK = {"lora": "serif", "inter": "sans-serif", "poppins": "sans-serif"}
BASE = "http://bp.local"


@dataclass
class PageData:
    name: Optional[str] = None
    organisation: Optional[str] = None
    award: Optional[str] = None
    row_id: Optional[str] = None


@dataclass
class RenderContext:
    spec: DesignSpec
    event: EventFields
    pages: list[PageData]
    blank: Optional[BlankOptions] = None  # set => blank-name mode
    asset_urls: dict[str, str] = field(default_factory=dict)  # asset_id -> url


def esc(s: str) -> str:
    return _html.escape(s or "", quote=True)


def render_body_text(spec: DesignSpec, event: EventFields) -> str:
    t = event.wording.strip() or spec.body_text
    return (t.replace("{event_name}", event.event_name)
             .replace("{organisation}", event.organisation)
             .replace("{event_date}", event.event_date))


def used_fonts(spec: DesignSpec) -> list[str]:
    return sorted({spec.fonts.heading, spec.fonts.body, spec.fonts.name})


def font_files(spec: DesignSpec) -> dict[str, "Path"]:
    out = {}
    for key in used_fonts(spec):
        for fn, _, _ in FONT_FACES[key]:
            out[fn] = FONT_DIR / fn
    return out


def expected_fixed_texts(ctx: RenderContext) -> list[dict]:
    """Fixed strings that must appear on every page (label, text)."""
    s, e = ctx.spec, ctx.event
    out = []
    if e.organisation:
        out.append({"label": "organisation", "text": e.organisation})
    if e.cert_type:
        out.append({"label": "certificate type", "text": e.cert_type})
    if s.preamble_text:
        out.append({"label": "preamble", "text": s.preamble_text})
    body = render_body_text(s, e)
    if body:
        out.append({"label": "award wording", "text": body})
    for i, sg in enumerate(e.signatories):
        if sg.name:
            out.append({"label": f"signatory {i+1} name", "text": sg.name})
        if sg.title:
            out.append({"label": f"signatory {i+1} title", "text": sg.title})
    if ctx.blank:
        for fld, pol in ctx.blank.optional_fields.items():
            if pol.mode == "fixed" and pol.fixed_text:
                out.append({"label": f"fixed {fld}", "text": pol.fixed_text})
    return out


def _rect_style(r) -> str:
    x, y, w, h = r
    return f"left:{x:.3f}mm;top:{y:.3f}mm;width:{w:.3f}mm;height:{h:.3f}mm;"


def _font_css(spec: DesignSpec) -> str:
    css = []
    for key in used_fonts(spec):
        for fn, style, weight in FONT_FACES[key]:
            css.append(
                f"@font-face{{font-family:'BP-{key}';src:url('{BASE}/fonts/{fn}');"
                f"font-style:{style};font-weight:{weight};font-display:block;}}"
            )
    return "\n".join(css)


def _lum(hexc: str) -> float:
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def ensure_contrast(fg: str, bgs: list[str], target: float) -> str:
    """Nudge fg toward black or white (whichever helps) until it meets `target` against every background."""
    def ok(c): return all(_contrast(c, bg) >= target for bg in bgs)
    if ok(fg):
        return fg
    avg = sum(_lum(b) for b in bgs) / len(bgs)
    end = "#000000" if avg > 0.4 else "#ffffff"
    for i in range(1, 21):
        c = _mix(fg, end, i / 20)
        if ok(c):
            return c
    return end


def bg_stops(spec: DesignSpec) -> list[str]:
    c = spec.composition
    if spec.layout_id == "custom" and c.background == "gradient":
        return [spec.palette.background, c.background_color2]
    return [spec.palette.background]


def theme_colours(spec: DesignSpec) -> dict:
    """Page, text, heading and name colours. 'luxe' paints the page with the primary colour; 'custom' follows the palette."""
    p = spec.palette
    if spec.layout_id == "luxe":
        bg = p.primary
        fg = "#f6f1e4" if _contrast(bg, "#f6f1e4") >= 4.5 else "#1a1a1a"
        head = p.accent if _contrast(bg, p.accent) >= 3.0 else fg
        return {"bg": bg, "bg_css": bg, "fg": fg, "head": head, "name": fg, "accent": head, "line": head, "dark": fg == "#f6f1e4"}
    if spec.layout_id == "custom":
        stops = bg_stops(spec)
        c = spec.composition
        bg_css = p.background if len(stops) == 1 else f"linear-gradient({c.gradient_angle}deg,{stops[0]},{stops[1]})"
        fg = ensure_contrast(p.text, stops, 4.5)
        head = ensure_contrast(p.primary, stops, 4.5)
        accent = ensure_contrast(p.accent, stops, 3.0)
        dark = sum(_lum(x) for x in stops) / len(stops) < 0.3
        return {"bg": stops[0], "bg_css": bg_css, "fg": fg, "head": head, "name": head, "accent": accent, "line": fg, "dark": dark}
    return {"bg": p.background, "bg_css": p.background, "fg": p.text, "head": p.primary, "name": p.primary, "accent": p.accent, "line": p.text, "dark": False}


def _svg(w: float, h: float, inner: str, style: str, frame: bool = False) -> str:
    extra = ' data-frame="1"' if frame else ""
    return (f'<div class="decor" data-decor="1"{extra} style="{style}"><svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {w} {h}" width="{w}mm" height="{h}mm">{inner}</svg></div>')


def _corner(color: str, x: float, y: float, fx: int, fy: int, size: float = 26) -> str:
    """Quarter flourish: two nested rounded rules, a diamond and a dot. Top-left base, mirrored by scale."""
    inner = (f'<g fill="none" stroke="{color}" stroke-linecap="round">'
             f'<path d="M1 {size} V9 Q1 1 9 1 H{size}" stroke-width="0.55"/>'
             f'<path d="M4.2 {size-4} V11 Q4.2 4.2 11 4.2 H{size-4}" stroke-width="0.25"/>'
             f'<path d="M8 8 m-2.2 0 l2.2 -2.2 l2.2 2.2 l-2.2 2.2 z" fill="{color}" stroke="none"/>'
             f'<circle cx="{size-1.5}" cy="1" r="0.7" fill="{color}" stroke="none"/>'
             f'<circle cx="1" cy="{size-1.5}" r="0.7" fill="{color}" stroke="none"/></g>')
    sc = f"transform:scale({-1 if fx else 1},{-1 if fy else 1});"
    return _svg(size, size, inner, f"left:{x}mm;top:{y}mm;width:{size}mm;height:{size}mm;{sc}")


def _rosette(color: str, opacity: float, cx: float = PAGE_W / 2, cy: float = PAGE_H / 2 - 2, r: float = 62) -> str:
    """Fine guilloche-style watermark made of rotated ellipses. Vector only, no text."""
    ell = "".join(f'<ellipse rx="{r}" ry="{r*0.34:.2f}" transform="rotate({a})"/>' for a in range(0, 180, 12))
    ring = f'<circle r="{r*0.98:.2f}"/><circle r="{r*0.62:.2f}"/><circle r="{r*0.3:.2f}"/>'
    inner = f'<g transform="translate({r} {r})" fill="none" stroke="{color}" stroke-width="0.16" opacity="{opacity}">{ell}{ring}</g>'
    return _svg(2 * r, 2 * r, inner, f"left:{cx-r:.2f}mm;top:{cy-r:.2f}mm;width:{2*r}mm;height:{2*r}mm;", frame=True)


def _divider(color: str) -> str:
    w = 96.0
    inner = (f'<g stroke="{color}" stroke-width="0.35" fill="{color}">'
             f'<line x1="0" y1="3" x2="40" y2="3"/><line x1="56" y1="3" x2="96" y2="3"/>'
             f'<path d="M48 0.4 L51 3 L48 5.6 L45 3 Z" stroke="none"/>'
             f'<circle cx="42.6" cy="3" r="0.6" stroke="none"/><circle cx="53.4" cy="3" r="0.6" stroke="none"/></g>')
    return _svg(w, 6, inner, f"left:{(PAGE_W-w)/2:.2f}mm;top:62.6mm;width:{w}mm;height:6mm;")


def _divider_style(kind: str, color: str) -> str:
    w = 96.0
    if kind == "none":
        return ""
    if kind == "diamond":
        return _divider(color)
    if kind == "line":
        inner = f'<line x1="14" y1="3" x2="82" y2="3" stroke="{color}" stroke-width="0.35"/>'
    elif kind == "dots":
        inner = "".join(f'<circle cx="{48 + dx}" cy="3" r="{r}" fill="{color}"/>' for dx, r in ((-9, 0.5), (-4.5, 0.75), (0, 1.1), (4.5, 0.75), (9, 0.5)))
    else:  # double
        inner = (f'<line x1="10" y1="2" x2="86" y2="2" stroke="{color}" stroke-width="0.35"/>'
                 f'<line x1="22" y1="4.2" x2="74" y2="4.2" stroke="{color}" stroke-width="0.2"/>')
    return _svg(w, 6, inner, f"left:{(PAGE_W-w)/2:.2f}mm;top:62.6mm;width:{w}mm;height:6mm;")


def _bg_tag(prefix: str, inner_defs: str, fill_rect: str, opacity: float) -> str:
    return _svg(PAGE_W, PAGE_H, f'<defs>{inner_defs}</defs><g opacity="{opacity}">{fill_rect}</g>',
                f"left:0;top:0;width:{PAGE_W}mm;height:{PAGE_H}mm;", frame=True)


def _pattern(kind: str, color: str, op: float) -> str:
    full = f'<rect x="0" y="0" width="{PAGE_W}" height="{PAGE_H}" fill="url(#bp-pat)"/>'
    if kind == "rosette":
        return _rosette(color, op)
    if kind == "dots":
        return _bg_tag("p", f'<pattern id="bp-pat" width="7" height="7" patternUnits="userSpaceOnUse"><circle cx="3.5" cy="3.5" r="0.45" fill="{color}"/></pattern>', full, op * 2.2)
    if kind == "stripes":
        return _bg_tag("p", f'<pattern id="bp-pat" width="3.2" height="3.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="3.2" stroke="{color}" stroke-width="0.35"/></pattern>', full, op * 1.6)
    if kind == "grid":
        return _bg_tag("p", f'<pattern id="bp-pat" width="9" height="9" patternUnits="userSpaceOnUse"><path d="M9 0 L0 0 0 9" fill="none" stroke="{color}" stroke-width="0.15"/></pattern>', full, op * 2.5)
    if kind == "arcs":
        circles = "".join(f'<circle cx="{PAGE_W}" cy="{PAGE_H}" r="{r}"/>' for r in range(26, 190, 14))
        return _bg_tag("p", "", f'<g fill="none" stroke="{color}" stroke-width="0.25">{circles}</g>', op * 2.2)
    if kind == "waves":
        paths = ""
        for i in range(9):
            y = 14 + i * 22
            paths += f'<path d="M0 {y} Q 18.5 {y-7} 37 {y} T 74 {y} T 111 {y} T 148 {y} T 185 {y} T 222 {y} T 259 {y} T 296 {y}" />'
        return _bg_tag("p", "", f'<g fill="none" stroke="{color}" stroke-width="0.25">{paths}</g>', op * 2.2)
    return ""


def _frame(kind: str, inset: float, w: float, c1: str, c2: str) -> str:
    def box(i, bw, col, rad=0, style="solid"):
        return (f'<div class="decor" data-decor="1" data-frame="1" style="left:{i}mm;top:{i}mm;width:{PAGE_W-2*i}mm;height:{PAGE_H-2*i}mm;'
                f'border:{bw}mm {style} {col};border-radius:{rad}mm;box-sizing:border-box;"></div>')
    w = max(0.3, min(w, 3.0))
    if kind == "single":
        return box(inset, w, c1)
    if kind == "double":
        return box(inset, w, c1) + box(inset + 3.5, 0.3, c2)
    if kind == "triple":
        return box(inset, 0.3, c2) + box(inset + 2.2, w, c1) + box(inset + 4.4, 0.3, c2)
    if kind == "rounded":
        return box(inset, w, c1, rad=7) + box(inset + 3, 0.3, c2, rad=5)
    if kind == "thick_thin":
        return box(inset, w * 1.8, c1) + box(inset + w * 1.8 + 1.6, 0.3, c2)
    return ""


def _corner_shape(kind: str, size: float, c1: str, c2: str, x: float, y: float, fx: int, fy: int) -> str:
    sc = f"transform:scale({-1 if fx else 1},{-1 if fy else 1});"
    st = f"left:{x}mm;top:{y}mm;width:{size}mm;height:{size}mm;{sc}"
    S = size
    if kind == "triangles":
        inner = f'<polygon points="0,0 {S},0 0,{S}" fill="{c2}" opacity="0.92"/><polygon points="0,0 {S*0.6},0 0,{S*0.6}" fill="{c1}"/>'
    elif kind == "quarter_circles":
        inner = (f'<path d="M0 0 L{S} 0 A{S} {S} 0 0 1 0 {S} Z" fill="{c1}"/>'
                 f'<path d="M0 0 L{S*0.62} 0 A{S*0.62} {S*0.62} 0 0 1 0 {S*0.62} Z" fill="none" stroke="{c2}" stroke-width="0.6"/>')
    elif kind == "rings":
        inner = "".join(f'<circle cx="0" cy="0" r="{S*f:.2f}" fill="none" stroke="{c2 if i % 2 else c1}" stroke-width="{0.5 if i % 2 else 0.9}" opacity="0.9"/>' for i, f in enumerate((0.35, 0.55, 0.78, 1.0)))
    elif kind == "brackets":
        inner = (f'<path d="M1.5 {S*0.7} V1.5 H{S*0.7}" fill="none" stroke="{c1}" stroke-width="0.9"/>'
                 f'<path d="M5 {S*0.45} V5 H{S*0.45}" fill="none" stroke="{c2}" stroke-width="0.35"/>')
    else:
        return ""
    return _svg(S, S, inner, st, frame=True)


def _decor_custom(spec: DesignSpec, n_sig: int) -> str:
    c = spec.composition
    p = spec.palette
    t = theme_colours(spec)
    d = []
    stops = bg_stops(spec)
    c1 = ensure_contrast(p.primary, stops, 3.0)
    c2 = t["accent"]
    ink = t["head"]
    if c.pattern != "none":
        d.append(_pattern(c.pattern, c2 if t["dark"] else c1, c.pattern_opacity))
    inset = min(c.frame_inset_mm, 8 if n_sig >= 4 else 14)
    d.append(_frame(c.frame, inset, spec.border_mm, c1, c2))
    # bands: capped so they never reach the signature or logo areas
    bm = min(c.band_mm, 9) if c.band in ("left", "right", "left_right") else min(c.band_mm, 12)
    def band(x, y, w, h, line):
        o = f'<div class="decor" data-decor="1" data-frame="1" style="left:{x}mm;top:{y}mm;width:{w}mm;height:{h}mm;background:{c1};"></div>'
        if c.band_accent_line:
            lx, ly, lw, lh = line
            o += f'<div class="decor" data-decor="1" data-frame="1" style="left:{lx}mm;top:{ly}mm;width:{lw}mm;height:{lh}mm;background:{c2};"></div>'
        return o
    if c.band in ("left", "left_right"):
        d.append(band(0, 0, bm, PAGE_H, (bm, 0, 0.8, PAGE_H)))
    if c.band in ("right", "left_right"):
        d.append(band(PAGE_W - bm, 0, bm, PAGE_H, (PAGE_W - bm - 0.8, 0, 0.8, PAGE_H)))
    if c.band in ("top", "top_bottom"):
        d.append(band(0, 0, PAGE_W, bm, (0, bm, PAGE_W, 0.8)))
    if c.band in ("bottom", "top_bottom"):
        d.append(band(0, PAGE_H - bm, PAGE_W, bm, (0, PAGE_H - bm - 0.8, PAGE_W, 0.8)))
    if c.corners != "none":
        top = c.corner_size_mm
        bot = min(c.corner_size_mm, 16 if n_sig >= 4 else 26)
        if c.corners == "flourish":
            col = c2
            for x, y, fx, fy, sz in ((12.5, 12.5, 0, 0, 26), (PAGE_W - 38.5, 12.5, 1, 0, 26), (12.5, PAGE_H - 12.5 - bot, 0, 1, bot), (PAGE_W - 12.5 - bot, PAGE_H - 12.5 - bot, 1, 1, bot)):
                d.append(_corner(col, x, y, fx, fy, sz))
        else:
            for x, y, fx, fy, sz in ((0, 0, 0, 0, top), (PAGE_W - top, 0, 1, 0, top), (0, PAGE_H - bot, 0, 1, bot), (PAGE_W - bot, PAGE_H - bot, 1, 1, bot)):
                if c.band in ("left", "left_right") and fx == 0 and c.corners in ("brackets",):
                    x += bm
                d.append(_corner_shape(c.corners, sz, c1, c2, x, y, fx, fy))
    d.append(_divider_style(c.divider, c2))
    return "".join(d)


def _decor(spec: DesignSpec, n_sig: int = 3) -> str:
    if spec.layout_id == "custom":
        return _decor_custom(spec, n_sig)
    p = spec.palette
    t = theme_colours(spec)
    d = []
    lid = spec.layout_id
    bw = spec.border_mm
    if lid == "formal":
        if bw > 0:
            d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:6mm;top:6mm;width:285mm;height:198mm;'
                     f'border:{bw}mm solid {p.primary};box-sizing:border-box;"></div>')
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:9.5mm;top:9.5mm;width:278mm;height:191mm;'
                 f'border:0.3mm solid {p.accent};box-sizing:border-box;"></div>')
        d.append(_rosette(p.accent, 0.22))
    elif lid == "academic":
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:0;top:0;width:10mm;height:{PAGE_H}mm;background:{p.primary};"></div>')
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:10mm;top:0;width:{max(bw,0.5):.2f}mm;height:{PAGE_H}mm;background:{p.accent};"></div>')
        arcs = "".join(f'<circle cx="90" cy="0" r="{r}"/>' for r in (30, 48, 66, 84))
        d.append(_svg(90, 90, f'<g fill="none" stroke="{p.primary}" stroke-width="0.3" opacity="0.18">{arcs}</g>',
                      f"left:{PAGE_W-90}mm;top:0;width:90mm;height:90mm;", frame=True))
        d.append(_rosette(p.primary, 0.07))
    elif lid == "event":
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:0;top:0;width:{PAGE_W}mm;height:5mm;background:{p.primary};"></div>')
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:0;top:{PAGE_H-5}mm;width:{PAGE_W}mm;height:5mm;background:{p.accent};"></div>')
        d.append(_svg(70, 46, f'<polygon points="70,0 0,0 70,46" fill="{p.accent}" opacity="0.9"/><polygon points="70,0 28,0 70,28" fill="{p.primary}"/>',
                      f"left:{PAGE_W-70}mm;top:5mm;width:70mm;height:46mm;", frame=True))
        d.append(_svg(70, 46, f'<polygon points="0,0 70,0 0,46" fill="{p.accent}" opacity="0.9"/><polygon points="0,0 42,0 0,28" fill="{p.primary}"/>',
                      "left:0;top:5mm;width:70mm;height:46mm;", frame=True))
    elif lid == "luxe":
        gold = t["accent"]
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:7mm;top:7mm;width:283mm;height:196mm;border:{max(bw,0.6)}mm solid {gold};box-sizing:border-box;"></div>')
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:10.5mm;top:10.5mm;width:276mm;height:189mm;border:0.25mm solid {gold};box-sizing:border-box;opacity:.7;"></div>')
        d.append(_rosette(gold, 0.13))
    o = spec.ornament
    if o == "corners":
        col = t["accent"] if lid in ("luxe", "formal") else p.accent
        for x, y, fx, fy in ((12.5, 12.5, 0, 0), (PAGE_W - 12.5 - 26, 12.5, 1, 0), (12.5, PAGE_H - 12.5 - 26, 0, 1), (PAGE_W - 12.5 - 26, PAGE_H - 12.5 - 26, 1, 1)):
            if lid == "academic" and x < 20:
                x += 8
            d.append(_corner(col, x, y, fx, fy))
    if o in ("corners", "rule"):
        d.append(_divider(t["accent"] if lid in ("luxe", "formal") else p.accent))
    elif o == "band":
        d.append(f'<div class="decor" data-decor="1" data-frame="1" style="left:0;top:{PAGE_H-12}mm;width:{PAGE_W}mm;height:2mm;background:{p.accent};"></div>')
    return "".join(d)


def _css(ctx: RenderContext) -> str:
    s = ctx.spec
    p = s.palette
    f = s.fonts
    t = theme_colours(s)
    dens = s.density
    lid = s.layout_id
    head = f"'BP-{f.heading}',{FALLBACK_STACK[f.heading]}"
    body = f"'BP-{f.body}',{FALLBACK_STACK[f.body]}"
    name = f"'BP-{f.name}',{FALLBACK_STACK[f.name]}"
    title_size = {"formal": 31, "academic": 29, "event": 34, "luxe": 32, "custom": 31}[lid] * dens
    title_weight = {"formal": 600, "academic": 600, "event": 700, "luxe": 500, "custom": 600}[lid]
    title_ls = {"formal": "0.05em", "academic": "0.03em", "event": "0.02em", "luxe": "0.06em", "custom": f"{s.composition.title_tracking_em:.3f}em"}[lid]
    org_ls = {"formal": "0.14em", "academic": "0.08em", "event": "0.06em", "luxe": "0.18em", "custom": f"{min(s.composition.title_tracking_em*2.2, 0.2):.3f}em"}[lid]
    name_style = "italic" if ((f.name == "lora" and lid in ("formal", "luxe")) or (lid == "custom" and s.composition.name_italic and f.name == "lora")) else "normal"
    plate = (".sig .img img, [data-el=logo] img { background:#f6f1e4; padding:1.2mm; border-radius:1mm; }" if t["dark"] else "")
    return f"""
{_font_css(s)}
@page {{ size: {PAGE_W}mm {PAGE_H}mm; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: {t['bg_css']}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
body {{ font-family: {body}; color: {t['fg']}; font-variant-ligatures: none; font-feature-settings: "liga" 0, "clig" 0; }}
.page {{ position: relative; width: {PAGE_W}mm; height: {PAGE_H}mm; overflow: hidden; background: {t['bg_css']};
        break-after: page; page-break-after: always; }}
.page:last-child {{ break-after: auto; page-break-after: auto; }}
.decor, .bp-el {{ position: absolute; }}
.decor svg {{ display: block; }}
.txt {{ display: flex; align-items: center; justify-content: center; text-align: center; line-height: 1.25; }}
.txt > span {{ display: block; max-width: 100%; }}
[data-el=org] {{ font-family: {head}; font-weight: 600; font-size: {12.5*dens:.2f}pt; color: {t['head']}; letter-spacing: {org_ls}; }}
[data-el=title] {{ font-family: {head}; font-weight: {title_weight}; font-size: {title_size:.2f}pt; color: {t['head']}; letter-spacing: {title_ls}; }}
[data-el=preamble] {{ font-size: {11.5*dens:.2f}pt; font-style: normal; letter-spacing: 0.04em; opacity: .92; }}
[data-el=name] {{ display: flex; align-items: center; justify-content: center; text-align: center; }}
[data-el=name] .nm {{ font-family: {name}; font-weight: 600; font-style: {name_style}; color: {t['name']}; display: inline-block; white-space: nowrap; line-height: 1.1; }}
.hw-line {{ position: absolute; left: 0; right: 0; bottom: 0; border-bottom: 0.4mm solid {t['line']}; }}
[data-el=field_org] {{ font-size: {14*dens:.2f}pt; font-weight: 500; }}
[data-el=field_award] {{ font-size: {15*dens:.2f}pt; font-family: {head}; color: {t['accent']}; font-weight: 600; }}
[data-el=body] {{ font-size: {11.5*dens:.2f}pt; line-height: 1.5; opacity: .95; }}
.sig {{ display: flex; flex-direction: column; align-items: center; justify-content: flex-end; text-align: center; }}
.sig .img {{ height: 14mm; width: 100%; display: flex; align-items: flex-end; justify-content: center; }}
.sig .img img {{ max-height: 14mm; max-width: 90%; object-fit: contain; }}
.sig .ln {{ width: 86%; border-top: 0.3mm solid {t['line']}; margin-top: 1mm; }}
.sig .sn {{ font-weight: 700; font-size: {10.5*dens:.2f}pt; margin-top: 1mm; }}
.sig .st {{ font-size: {9.5*dens:.2f}pt; opacity: .9; }}
[data-el=logo] {{ display: flex; align-items: center; justify-content: center; }}
[data-el=logo] img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
{plate}
"""


def _fit_js(ctx: RenderContext) -> str:
    s = ctx.spec
    return """
window.__bp = (function(){
  const MAXPT=%s, MINPT=%s, TWO=%s;
  const PT=96/72;
  function fitAll(){
    const res=[];
    document.querySelectorAll('.page').forEach((pg,i)=>{
      const el=pg.querySelector('[data-el=name] .nm'); if(!el){return;}
      const box=el.parentElement; const bw=box.clientWidth, bh=box.clientHeight;
      function apply(sz){el.style.fontSize=sz+'pt';}
      function fits(){
        if(el.style.whiteSpace==='normal'){return el.scrollWidth<=bw+0.5 && el.getBoundingClientRect().height<=bh+0.5;}
        const r=el.getBoundingClientRect(); return r.width<=bw+0.5 && r.height<=bh+0.5;
      }
      el.style.whiteSpace='nowrap'; el.style.maxWidth='none'; let sz=MAXPT; apply(sz);
      while(!fits() && sz>MINPT){sz=Math.max(MINPT,sz-0.5); apply(sz);}
      let lines=1;
      if(!fits() && TWO){
        el.style.whiteSpace='normal'; el.style.maxWidth=bw+'px'; el.style.display='block'; el.style.textAlign='center';
        sz=MAXPT; apply(sz);
        while(!fits() && sz>MINPT){sz=Math.max(MINPT,sz-0.5); apply(sz);}
      }
      const lh=parseFloat(getComputedStyle(el).lineHeight)||sz*PT*1.1;
      lines=Math.max(1,Math.round(el.getBoundingClientRect().height/lh));
      res.push({page:i+1,size:sz,lines:lines,adjusted:sz<MAXPT-0.01,overflow:!fits()});
    });
    return res;
  }
  function contentRect(el){
    const rects=[];
    const w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT);
    let n;
    while((n=w.nextNode())){
      if(n.nodeType===3){ if(!n.textContent.trim()) continue; const r=document.createRange(); r.selectNodeContents(n); for(const q of r.getClientRects()){rects.push(q);} }
      else if(n.tagName==='IMG'){rects.push(n.getBoundingClientRect());}
    }
    if(!rects.length) return null;
    let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
    rects.forEach(q=>{x0=Math.min(x0,q.left);y0=Math.min(y0,q.top);x1=Math.max(x1,q.right);y1=Math.max(y1,q.bottom);});
    return {x0,y0,x1,y1};
  }
  function inter(a,b){const w=Math.min(a.x1,b.x1)-Math.max(a.x0,b.x0), h=Math.min(a.y1,b.y1)-Math.max(a.y0,b.y0); return w>1&&h>1;}
  function boxRect(el){const r=el.getBoundingClientRect();return {x0:r.left,y0:r.top,x1:r.right,y1:r.bottom};}
  function geometry(){
    const issues=[];
    document.querySelectorAll('.page').forEach((pg,i)=>{
      const pr=boxRect(pg); const pn=i+1;
      const els=[...pg.querySelectorAll('.bp-el')];
      const info=els.map(el=>({el,id:el.dataset.el,reserved:!!el.dataset.reserved,
        c:contentRect(el)||(el.dataset.reserved?boxRect(el):null), box:boxRect(el)}));
      info.forEach(a=>{ if(!a.c) return;
        if(a.c.x0<pr.x0-0.5||a.c.y0<pr.y0-0.5||a.c.x1>pr.x1+0.5||a.c.y1>pr.y1+0.5)
          issues.push({page:pn,code:'CONTENT_OUTSIDE_PAGE',el:a.id});
      });
      for(let x=0;x<info.length;x++)for(let y=x+1;y<info.length;y++){
        const a=info[x],b=info[y]; if(!a.c||!b.c) continue;
        if(a.reserved||b.reserved) continue;
        if(inter(a.c,b.c)) issues.push({page:pn,code:'ESSENTIAL_ELEMENT_OVERLAP',el:a.id,other:b.id});
      }
      info.filter(a=>a.reserved).forEach(r=>{
        info.forEach(o=>{ if(o===r||!o.c) return; if(inter(r.box,o.c)) issues.push({page:pn,code:'HANDWRITING_AREA_OBSTRUCTED',el:o.id,other:r.id}); });
        pg.querySelectorAll('.decor:not([data-frame])').forEach(d=>{ if(inter(r.box,boxRect(d))) issues.push({page:pn,code:'HANDWRITING_AREA_OBSTRUCTED',el:'decor',other:r.id}); });
        const M=14*96/25.4; if(r.box.x0<pr.x0+M||r.box.x1>pr.x1-M||r.box.y0<pr.y0+M||r.box.y1>pr.y1-M) issues.push({page:pn,code:'CONTENT_OUTSIDE_PAGE',el:r.id});
      });
      pg.querySelectorAll('img').forEach(im=>{ if(!(im.complete&&im.naturalWidth>0)) issues.push({page:pn,code:'ASSET_LOAD_FAILURE',el:im.parentElement.dataset.el||'img'}); });
    });
    const bad=[...document.fonts].filter(f=>f.status==='error').map(f=>f.family);
    if(bad.length) issues.push({page:0,code:'ASSET_LOAD_FAILURE',el:'font:'+bad.join(',')});
    return issues;
  }
  return {fitAll,geometry};
})();
""" % (s.name_font_max_pt, s.name_font_min_pt, "true" if s.allow_two_lines else "false")


def build_document(ctx: RenderContext, doc_title: str) -> str:
    s, e = ctx.spec, ctx.event
    blank = ctx.blank
    nw = blank.width_mm if blank else s.name_box_width_mm
    nh = blank.height_mm if blank else s.name_box_height_mm
    g = geometry(nw, nh)
    sigs = list(zip(e.signatories, signatory_rects(len(e.signatories))))
    body_txt = render_body_text(s, e)
    decor = _decor(s, len(e.signatories))
    pages = []
    for i, pd in enumerate(ctx.pages):
        h = [f'<section class="page" data-page="{i+1}">', decor]
        logo_url = ctx.asset_urls.get(e.logo_asset_id or "")
        if logo_url:
            h.append(f'<div class="bp-el" data-el="logo" data-essential="1" style="{_rect_style(g["logo"])}"><img src="{esc(logo_url)}" alt=""></div>')
        def txt(key, text):
            if text:
                h.append(f'<div class="bp-el txt" data-el="{key}" data-essential="1" style="{_rect_style(g[key])}"><span>{esc(text)}</span></div>')
        txt("org", e.organisation)
        txt("title", e.cert_type)
        txt("preamble", s.preamble_text)
        if blank:
            line = '<div class="hw-line"></div>' if blank.line else ""
            h.append(f'<div class="bp-el" data-el="name" data-reserved="1" style="{_rect_style(g["name"])}">{line}</div>')
            for fld, key in (("organisation", "field_org"), ("award", "field_award")):
                pol = blank.optional_fields.get(fld)
                if not pol or pol.mode == "omit":
                    continue
                if pol.mode == "fixed":
                    txt(key, pol.fixed_text)
                else:  # handwriting
                    line2 = '<div class="hw-line"></div>' if blank.line else ""
                    h.append(f'<div class="bp-el" data-el="{key}" data-reserved="1" style="{_rect_style(g[key])}">{line2}</div>')
        else:
            h.append(f'<div class="bp-el" data-el="name" data-essential="1" style="{_rect_style(g["name"])}"><span class="nm">{esc(pd.name or "")}</span></div>')
            txt("field_org", pd.organisation or "")
            txt("field_award", pd.award or "")
        txt("body", body_txt)
        for k, (sg, r) in enumerate(sigs):
            img = ""
            url = ctx.asset_urls.get(sg.signature_asset_id or "")
            if url:
                img = f'<img src="{esc(url)}" alt="">'
            h.append(
                f'<div class="bp-el sig" data-el="sig{k+1}" data-essential="1" style="{_rect_style(r)}">'
                f'<div class="img">{img}</div><div class="ln"></div>'
                f'<div class="sn">{esc(sg.name)}</div><div class="st">{esc(sg.title)}</div></div>'
            )
        h.append("</section>")
        pages.append("".join(h))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{esc(doc_title)}</title><style>{_css(ctx)}</style></head><body>"
        + "".join(pages) + f"<script>{_fit_js(ctx)}</script></body></html>"
    )
