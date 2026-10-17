"""SQLite for metadata + local directories for files. Generated IDs only; no user path segments."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from PIL import Image

from .config import get_settings
from .schemas import Project, now_iso

ID_RE = re.compile(r"^[0-9a-f]{16}$")
_lock = threading.RLock()


class StorageError(Exception):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def check_id(i: str) -> str:
    if not ID_RE.match(i or ""):
        raise StorageError("invalid id")
    return i


def data_dir() -> Path:
    d = get_settings().data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextmanager
def db():
    with _lock:
        con = sqlite3.connect(str(data_dir() / "batchproof.sqlite3"), check_same_thread=False, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def init_db() -> None:
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, project_id TEXT, mime TEXT, path TEXT, sha256 TEXT,
            filename TEXT, width INT, height INT);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, status TEXT, progress REAL,
            message TEXT, result TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, intent_hash TEXT,
            sha256 TEXT, pages INT, completion TEXT, meta TEXT, created_at TEXT);
        """)
        c.execute("UPDATE jobs SET status='interrupted', message='Interrupted by a restart; safe to run again.', updated_at=? "
                  "WHERE status IN ('queued','running')", (now_iso(),))


def project_dir(pid: str) -> Path:
    d = data_dir() / "projects" / check_id(pid)
    d.mkdir(parents=True, exist_ok=True)
    return d


# projects -------------------------------------------------------------------
def create_project(title: str, kind: str = "generate", is_demo: bool = False) -> Project:
    p = Project(id=new_id(), title=title, kind=kind, is_demo=is_demo, created_at=now_iso(), updated_at=now_iso())
    with db() as c:
        c.execute("INSERT INTO projects VALUES(?,?,?,?)", (p.id, p.model_dump_json(), p.created_at, p.updated_at))
    project_dir(p.id)
    return p


def get_project(pid: str) -> Optional[Project]:
    with db() as c:
        r = c.execute("SELECT data FROM projects WHERE id=?", (check_id(pid),)).fetchone()
    return Project.model_validate_json(r["data"]) if r else None


def save_project(p: Project) -> Project:
    p.updated_at = now_iso()
    with db() as c:
        c.execute("UPDATE projects SET data=?, updated_at=? WHERE id=?", (p.model_dump_json(), p.updated_at, p.id))
    return p


def list_projects() -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT data FROM projects ORDER BY updated_at DESC").fetchall()
    out = []
    for r in rows:
        p = Project.model_validate_json(r["data"])
        out.append({"id": p.id, "title": p.title, "kind": p.kind, "is_demo": p.is_demo, "updated_at": p.updated_at,
                    "recipients": len(p.source.rows)})
    return out


def delete_project(pid: str) -> bool:
    check_id(pid)
    with db() as c:
        n = c.execute("DELETE FROM projects WHERE id=?", (pid,)).rowcount
        c.execute("DELETE FROM assets WHERE project_id=?", (pid,))
        c.execute("DELETE FROM jobs WHERE project_id=?", (pid,))
        c.execute("DELETE FROM artifacts WHERE project_id=?", (pid,))
    shutil.rmtree(data_dir() / "projects" / pid, ignore_errors=True)
    return bool(n)


# assets ---------------------------------------------------------------------
def add_image_asset(pid: str, data: bytes, filename: str) -> dict:
    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise StorageError(f"Image is larger than {s.max_upload_mb} MB.")
    try:
        im = Image.open(__import__("io").BytesIO(data))
        fmt, (w, h) = im.format, im.size
        if w * h > s.max_image_pixels:
            raise StorageError(f"Image has {w*h:,} pixels; the limit is {s.max_image_pixels:,}.")
        im.verify()
    except StorageError:
        raise
    except Exception:
        raise StorageError("This is not a valid PNG or JPEG image.")
    if fmt not in ("PNG", "JPEG"):
        raise StorageError("Only PNG and JPEG images are accepted (no SVG or other formats).")
    ext, mime = ("png", "image/png") if fmt == "PNG" else ("jpg", "image/jpeg")
    aid = new_id()
    path = project_dir(pid) / "assets" / f"{aid}.{ext}"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename or "image")[:80]
    with db() as c:
        c.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)", (aid, pid, mime, str(path), sha, safe_name, w, h))
    return {"id": aid, "mime": mime, "sha256": sha, "filename": safe_name, "width": w, "height": h}


def get_asset(pid: str, aid: str) -> Optional[dict]:
    with db() as c:
        r = c.execute("SELECT * FROM assets WHERE id=? AND project_id=?", (check_id(aid), check_id(pid))).fetchone()
    return dict(r) if r else None


def project_assets(p: Project) -> dict[str, tuple[Path, str]]:
    ids = [p.event.logo_asset_id] + [s.signature_asset_id for s in p.event.signatories]
    out = {}
    for aid in ids:
        if aid:
            a = get_asset(p.id, aid)
            if a:
                out[aid] = (Path(a["path"]), a["mime"])
    return out


def asset_hashes(p: Project) -> dict[str, str]:
    return {aid: get_asset(p.id, aid)["sha256"] for aid in project_assets(p)}


# artifacts ------------------------------------------------------------------
def add_artifact(pid: str, kind: str, intent_hash: str, sha: str, pages: int, completion: str, meta: dict) -> str:
    aid = new_id()
    with db() as c:
        c.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)",
                  (aid, pid, kind, intent_hash, sha, pages, completion, json.dumps(meta), now_iso()))
    return aid


def get_artifact(pid: str, aid: str) -> Optional[dict]:
    with db() as c:
        r = c.execute("SELECT * FROM artifacts WHERE id=? AND project_id=?", (check_id(aid), check_id(pid))).fetchone()
    if not r:
        return None
    d = dict(r)
    d["meta"] = json.loads(d["meta"])
    return d


def list_artifacts(pid: str, kind: Optional[str] = None) -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT id FROM artifacts WHERE project_id=? ORDER BY created_at DESC", (check_id(pid),)).fetchall()
    out = [get_artifact(pid, r["id"]) for r in rows]
    return [a for a in out if not kind or a["kind"] == kind]


def artifact_dir(pid: str, aid: str) -> Path:
    d = project_dir(pid) / "artifacts" / check_id(aid)
    d.mkdir(parents=True, exist_ok=True)
    return d
