"""Pydantic data contracts (conceptual models from the handoff, section 9)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HEX = r"^#[0-9a-fA-F]{6}$"
FontKey = Literal["lora", "inter", "poppins"]
LayoutId = Literal["academic", "formal", "event", "luxe", "custom"]
Ornament = Literal["none", "corners", "rule", "band"]
OutputMode = Literal["personalised", "blank_name"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Palette(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: str = Field("#1f3a5f", pattern=HEX)
    accent: str = Field("#c8963e", pattern=HEX)
    text: str = Field("#222222", pattern=HEX)
    background: str = Field("#ffffff", pattern=HEX)


class Fonts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: FontKey = "lora"
    body: FontKey = "inter"
    name: FontKey = "lora"


class Composition(BaseModel):
    """Building blocks the AI (or the user) combines into a custom design. Only used when layout_id == 'custom'.
    Every field is an allowlisted choice or a clamped number, so a model can never inject markup or break the layout."""
    model_config = ConfigDict(extra="forbid")
    background: Literal["solid", "gradient"] = "solid"
    background_color2: str = Field("#f3efe6", pattern=HEX)
    gradient_angle: int = Field(160, ge=0, le=360)
    frame: Literal["none", "single", "double", "triple", "rounded", "thick_thin"] = "double"
    frame_inset_mm: float = Field(8, ge=4, le=14)
    corners: Literal["none", "flourish", "triangles", "quarter_circles", "rings", "brackets"] = "none"
    corner_size_mm: float = Field(30, ge=14, le=70)
    band: Literal["none", "left", "right", "top", "bottom", "top_bottom", "left_right"] = "none"
    band_mm: float = Field(8, ge=3, le=12)
    band_accent_line: bool = True
    pattern: Literal["none", "rosette", "dots", "stripes", "arcs", "grid", "waves"] = "none"
    pattern_opacity: float = Field(0.08, ge=0.03, le=0.2)
    divider: Literal["none", "line", "diamond", "dots", "double"] = "diamond"
    title_tracking_em: float = Field(0.05, ge=0, le=0.3)
    name_italic: bool = False


class DesignSpec(BaseModel):
    """Allowlisted, validated design specification. Never HTML, never paths."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    layout_id: LayoutId = "formal"
    palette: Palette = Palette()
    fonts: Fonts = Fonts()
    density: float = Field(1.0, ge=0.85, le=1.15)
    border_mm: float = Field(1.5, ge=0, le=4)
    ornament: Ornament = "corners"
    preamble_text: str = Field("This certificate is proudly presented to", max_length=80)
    body_text: str = Field(
        "in recognition of valuable participation in {event_name}, held on {event_date}.",
        max_length=240,
    )
    composition: Composition = Composition()
    name_font_max_pt: float = Field(40, ge=28, le=60)
    name_font_min_pt: float = Field(24, ge=18, le=40)
    allow_two_lines: bool = False
    name_box_width_mm: float = Field(180, ge=100, le=230)
    name_box_height_mm: float = Field(20, ge=14, le=30)
    warnings: list[str] = []
    source: Literal["ai", "fallback", "manual"] = "manual"
    model_id: Optional[str] = None

    @model_validator(mode="after")
    def _range(self):
        if self.name_font_min_pt > self.name_font_max_pt:
            raise ValueError("name_font_min_pt must be <= name_font_max_pt")
        return self


class Signatory(BaseModel):
    name: str = Field("", max_length=80)
    title: str = Field("", max_length=80)
    signature_asset_id: Optional[str] = None


class EventFields(BaseModel):
    event_name: str = Field("", max_length=120)
    organisation: str = Field("", max_length=120)
    cert_type: str = Field("Certificate of Participation", max_length=80)
    event_date: str = Field("", max_length=60)  # display text, confirmed verbatim
    wording: str = Field("", max_length=240)  # optional user wording; overrides draft
    signatories: list[Signatory] = []
    logo_asset_id: Optional[str] = None

    @field_validator("signatories")
    @classmethod
    def _max4(cls, v):
        if len(v) > 4:
            raise ValueError("at most 4 signatories are supported")
        return v


class Brand(BaseModel):
    primary: Optional[str] = Field(None, pattern=HEX)
    accent: Optional[str] = Field(None, pattern=HEX)
    brief: str = Field("", max_length=1500)


class SourceRow(BaseModel):
    row_id: str
    sheet: str
    row_index: int  # 1-based row number in the original file
    cells: dict[str, str]
    findings: list[str] = []


class SourceData(BaseModel):
    filename: str = ""
    kind: Literal["manual", "csv", "xlsx"] = "manual"
    sheet: str = ""
    sheets: list[str] = []
    header_row: int = 1
    headers: list[str] = []
    rows: list[SourceRow] = []
    warnings: list[str] = []
    version: int = 0


TARGETS = ("name", "organisation", "award", "recipient_id")


class ConfirmedMapping(BaseModel):
    name: Optional[str] = None
    organisation: Optional[str] = None
    award: Optional[str] = None
    recipient_id: Optional[str] = None
    normalisation: Literal["nfc_whitespace"] = "nfc_whitespace"
    confirmed_at: str = ""
    method: Literal["manual", "ai", "rule_based", "auto_manual_entry"] = "manual"
    version: int = 0


class FieldPolicy(BaseModel):
    mode: Literal["omit", "fixed", "handwriting"] = "omit"
    fixed_text: str = Field("", max_length=120)


class BlankOptions(BaseModel):
    copies: int = Field(1, ge=1, le=100)
    line: bool = True
    width_mm: float = Field(120, ge=60, le=220)
    height_mm: float = Field(18, ge=10, le=30)
    optional_fields: dict[str, FieldPolicy] = {}
    confirmed_copies: Optional[int] = None  # user must confirm count before export


class Project(BaseModel):
    id: str
    title: str = "Untitled project"
    kind: Literal["generate", "check"] = "generate"
    is_demo: bool = False
    event: EventFields = EventFields()
    brand: Brand = Brand()
    design: Optional[DesignSpec] = None
    design_version: int = 0
    source: SourceData = SourceData()
    mapping: Optional[ConfirmedMapping] = None
    output_mode: OutputMode = "personalised"
    blank: BlankOptions = BlankOptions()
    acknowledgements: dict[str, str] = {}  # issue_id -> audit note
    created_at: str = ""
    updated_at: str = ""


class Issue(BaseModel):
    id: str
    code: str
    severity: Literal["error", "warning", "info"]
    page: Optional[int] = None  # 1-based
    row_id: Optional[str] = None
    source_row_index: Optional[int] = None
    field: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    rect: Optional[list[float]] = None  # fractional [x0,y0,x1,y1] of page
    message: str = ""
    next_action: str = ""
    candidates: list[str] = []
    acknowledged: bool = False
    ack_note: str = ""
