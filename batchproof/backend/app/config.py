"""Runtime settings, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
REPO = ROOT.parent
FONT_DIR = ROOT / "fonts"


def _load_dotenv() -> None:
    for p in (REPO / ".env",):
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_s: float
    ollama_keep_alive: str
    max_upload_mb: int
    max_image_pixels: int
    max_pdf_pages: int
    max_rows: int
    max_blank_copies: int
    host: str
    port: int
    chromium_path: str | None


def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        data_dir=Path(e("BATCHPROOF_DATA_DIR", str(REPO / "data"))).resolve(),
        ollama_base_url=e("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=e("OLLAMA_MODEL", "gemma3:4b"),
        ollama_timeout_s=float(e("OLLAMA_TIMEOUT_S", "240")),
        ollama_keep_alive=e("OLLAMA_KEEP_ALIVE", "2m"),
        max_upload_mb=int(e("MAX_UPLOAD_MB", "15")),
        max_image_pixels=int(e("MAX_IMAGE_PIXELS", "25000000")),
        max_pdf_pages=int(e("MAX_PDF_PAGES", "300")),
        max_rows=int(e("MAX_ROWS", "1000")),
        max_blank_copies=int(e("MAX_BLANK_COPIES", "100")),
        host=e("BATCHPROOF_HOST", "127.0.0.1"),
        port=int(e("BATCHPROOF_PORT", "8000")),
        chromium_path=e("BATCHPROOF_CHROMIUM_PATH") or None,
    )
