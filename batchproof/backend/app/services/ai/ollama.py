"""Thin local-Ollama client. Server-side only; never called from the browser."""
from __future__ import annotations

import json
import threading
import time
from typing import Optional

import httpx

from ...config import get_settings
from ...schemas import now_iso


class AIError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


def status() -> dict:
    s = get_settings()
    out = {"base_url": s.ollama_base_url, "model": s.ollama_model, "reachable": False, "model_installed": False,
           "installed_models": [], "error": None}
    try:
        r = httpx.get(f"{s.ollama_base_url}/api/tags", timeout=3.0)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        out.update(reachable=True, installed_models=names,
                   model_installed=any(n == s.ollama_model or n.split(":")[0] == s.ollama_model and ":" not in s.ollama_model
                                       for n in names))
        if not out["model_installed"]:
            out["error"] = f"Model '{s.ollama_model}' is not installed. Run: ollama pull {s.ollama_model}"
    except Exception as e:
        out["error"] = f"Ollama is not reachable at {s.ollama_base_url} ({type(e).__name__}). Start it with 'ollama serve'."
    return out


def chat_json(messages: list[dict], schema: dict, cancel: Optional[threading.Event] = None,
              num_predict: int = 900, temperature: float = 0.2) -> tuple[dict, dict]:
    s = get_settings()
    body = {"model": s.ollama_model, "messages": messages, "stream": True, "format": schema,
            "keep_alive": s.ollama_keep_alive, "options": {"temperature": temperature, "num_predict": num_predict}}
    t0 = time.time()
    text, evals = "", 0
    try:
        with httpx.stream("POST", f"{s.ollama_base_url}/api/chat", json=body,
                          timeout=httpx.Timeout(connect=3.0, read=s.ollama_timeout_s, write=10.0, pool=5.0)) as r:
            if r.status_code == 404:
                raise AIError("model_missing", f"Model '{s.ollama_model}' is not installed. Run: ollama pull {s.ollama_model}")
            if r.status_code >= 400:
                raise AIError("http", f"Ollama returned HTTP {r.status_code}.")
            for line in r.iter_lines():
                if cancel is not None and cancel.is_set():
                    raise AIError("cancelled", "Cancelled.")
                if time.time() - t0 > s.ollama_timeout_s:
                    raise AIError("timeout", f"The model did not finish within {int(s.ollama_timeout_s)} s.")
                if not line:
                    continue
                d = json.loads(line)
                text += d.get("message", {}).get("content", "")
                if d.get("done"):
                    evals = d.get("eval_count", 0)
    except AIError:
        raise
    except httpx.ConnectError as e:
        raise AIError("unavailable", f"Ollama is not reachable at {s.ollama_base_url}. Start it with 'ollama serve'.") from e
    except httpx.TimeoutException as e:
        raise AIError("timeout", f"The model did not answer within {int(s.ollama_timeout_s)} s.") from e
    except httpx.HTTPError as e:
        raise AIError("http", f"Ollama request failed ({type(e).__name__}).") from e
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise AIError("invalid_output", "The model did not return valid JSON.") from e
    if not isinstance(obj, dict):
        raise AIError("invalid_output", "The model returned JSON that is not an object.")
    return obj, {"duration_ms": int((time.time() - t0) * 1000), "eval_count": evals}


def unload() -> bool:
    s = get_settings()
    try:
        r = httpx.post(f"{s.ollama_base_url}/api/generate", json={"model": s.ollama_model, "keep_alive": 0}, timeout=10.0)
        return r.status_code < 400
    except Exception:
        return False


def trace(op: str, outcome: str, attempts: int, duration_ms: int, extra: Optional[dict] = None) -> None:
    """Local trace: operation, model, timing, validation outcome. Never names, signatures or prompts."""
    s = get_settings()
    rec = {"ts": now_iso(), "operation": op, "model": s.ollama_model, "attempts": attempts,
           "duration_ms": duration_ms, "outcome": outcome, **(extra or {})}
    try:
        s.data_dir.mkdir(parents=True, exist_ok=True)
        with open(s.data_dir / "ai_trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass
