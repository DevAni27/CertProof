"""A tiny fake Ollama server so the adapter (retry, validation, error states) can be tested offline.
It is NOT a model: tests using it prove plumbing and validation, not output quality."""
import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

BEHAVIOUR = {"mode": "valid", "calls": 0, "installed": ["gemma3:4b"], "payload": None, "sleep": 0.0}
app = FastAPI()


@app.get("/api/tags")
def tags():
    return {"models": [{"name": n} for n in BEHAVIOUR["installed"]]}


@app.post("/api/chat")
def chat(body: dict):
    BEHAVIOUR["calls"] += 1
    BEHAVIOUR["last_request"] = body
    if BEHAVIOUR["mode"] == "model_missing":
        return JSONResponse({"error": "model not found"}, status_code=404)
    time.sleep(BEHAVIOUR["sleep"])
    payload = BEHAVIOUR["payload"]
    if callable(payload):
        payload = payload(BEHAVIOUR["calls"])
    text = payload if isinstance(payload, str) else json.dumps(payload)

    def gen():
        mid = len(text) // 2
        yield json.dumps({"message": {"content": text[:mid]}, "done": False}) + "\n"
        yield json.dumps({"message": {"content": text[mid:]}, "done": True, "eval_count": 7}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/generate")
def gen(body: dict):
    BEHAVIOUR["unloaded"] = body.get("keep_alive") == 0
    return {"done": True}


def start():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    return server, port
