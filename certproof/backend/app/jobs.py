"""Single bounded local worker with persisted job states."""
from __future__ import annotations

import json
import queue
import threading
from typing import Callable, Optional

from .schemas import now_iso
from .services.rendering.renderer import Cancelled
from .storage import db, new_id


class JobFailure(Exception):
    def __init__(self, message: str, result: Optional[dict] = None):
        super().__init__(message)
        self.message, self.result = message, result or {}


class JobCtx:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.cancel = threading.Event()

    def progress(self, done: int, total: int, msg: str = "") -> None:
        # Only measurable progress (completed units of work) is reported.
        _update(self.job_id, progress=(done / total if total else 0.0), message=msg)


def _update(job_id: str, **kw) -> None:
    sets = ", ".join(f"{k}=?" for k in kw) + ", updated_at=?"
    vals = [json.dumps(v) if k == "result" else v for k, v in kw.items()] + [now_iso(), job_id]
    with db() as c:
        c.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)


class Runner:
    def __init__(self):
        self.q: "queue.Queue[tuple[str, Callable]]" = queue.Queue()
        self.ctxs: dict[str, JobCtx] = {}
        self.t: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def _ensure(self):
        with self.lock:
            if not self.t or not self.t.is_alive():
                self.t = threading.Thread(target=self._loop, daemon=True, name="certproof-worker")
                self.t.start()

    def submit(self, project_id: str, kind: str, fn: Callable[[JobCtx], dict]) -> str:
        jid = new_id()
        with db() as c:
            c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
                      (jid, project_id, kind, "queued", 0.0, "Queued", "{}", now_iso(), now_iso()))
        self.ctxs[jid] = JobCtx(jid)
        self.q.put((jid, fn))
        self._ensure()
        return jid

    def _loop(self):
        while True:
            jid, fn = self.q.get()
            ctx = self.ctxs[jid]
            if ctx.cancel.is_set():
                _update(jid, status="cancelled", message="Cancelled before it started.")
                continue
            _update(jid, status="running", message="Running")
            try:
                res = fn(ctx)
                if ctx.cancel.is_set():
                    raise Cancelled()
                _update(jid, status="completed", progress=1.0, message="Done", result=res or {})
            except (Cancelled, InterruptedError):
                _update(jid, status="cancelled", message="Cancelled. No file was kept.")
            except JobFailure as e:
                _update(jid, status="failed", message=e.message, result=e.result)
            except Exception as e:  # never leak recipient data into the message
                _update(jid, status="failed", message=f"Unexpected {type(e).__name__}. See the server console.")
                import traceback
                traceback.print_exc()

    def cancel(self, jid: str) -> bool:
        c = self.ctxs.get(jid)
        if not c:
            return False
        c.cancel.set()
        return True


runner = Runner()


def get_job(jid: str) -> Optional[dict]:
    with db() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["result"] = json.loads(d["result"] or "{}")
    return d
