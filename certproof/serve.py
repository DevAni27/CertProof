"""Start CertProof on loopback only.   .venv\\Scripts\\python.exe serve.py"""
import uvicorn

from backend.app.config import get_settings

if __name__ == "__main__":
    s = get_settings()
    print(f"CertProof: http://{s.host}:{s.port}   (Ctrl+C to stop)")
    uvicorn.run("backend.app.main:app", host=s.host, port=s.port, log_level="info")
