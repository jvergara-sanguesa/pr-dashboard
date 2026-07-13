#!/usr/bin/env python3
"""Lightweight local server for the PR dashboard.

Serves the dashboard on http://127.0.0.1:8787 and exposes a /refresh endpoint
so the page can rebuild itself on demand. Also rebuilds automatically every
30 min during work hours. Stdlib only — no dependencies.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import build  # local module (build.py in the same directory)
from build import OUTPUT

HOST = "127.0.0.1"
PORT = 8787
AUTO_REFRESH_SECONDS = 1800  # 30 min

# Shared build state, guarded by _lock (only one build at a time).
_lock = threading.Lock()
STATUS: dict = {"running": False, "last": None}


def _run_build() -> None:
    """Run one build and record the outcome in STATUS. Assumes _lock is held."""
    STATUS["running"] = True
    started = datetime.now().isoformat(timespec="seconds")
    try:
        stats = build.build_dashboard()
        STATUS["last"] = {"ok": True, "at": started, **stats}
    except Exception as exc:  # keep serving the previous HTML on failure
        STATUS["last"] = {"ok": False, "at": started, "error": str(exc)}
    finally:
        STATUS["running"] = False


def trigger_build() -> bool:
    """Start a background build if none is running. Returns True if started."""
    if not _lock.acquire(blocking=False):
        return False

    def worker() -> None:
        try:
            _run_build()
        finally:
            _lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


def build_sync() -> None:
    """Run a build synchronously (used for the initial build on startup)."""
    with _lock:
        _run_build()


def auto_refresh_loop() -> None:
    """Rebuild every AUTO_REFRESH_SECONDS while within work hours."""
    last = 0.0
    while True:
        time.sleep(60)
        if build.within_work_hours() and (time.monotonic() - last) >= AUTO_REFRESH_SECONDS:
            if trigger_build():
                last = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    """Routes: GET / (dashboard), GET /status, GET /health, POST /refresh."""

    def _send(self, code: int, body, ctype: str = "text/html; charset=utf-8") -> None:
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html", "/dashboard.html"):
            if not OUTPUT.exists():
                build_sync()
            self._send(200, OUTPUT.read_bytes())
        elif path == "/status":
            payload = {**STATUS, "log": list(build.LOG_LINES)}
            self._send(200, json.dumps(payload), "application/json")
        elif path == "/health":
            self._send(200, "ok", "text/plain; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/refresh":
            started = trigger_build()
            code = 202 if started else 409
            self._send(code, json.dumps({"started": started, "busy": not started}),
                       "application/json")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # silence per-request stderr noise
        pass


def main() -> None:
    """Build once if needed, start auto-refresh, and serve forever."""
    if not OUTPUT.exists():
        print("build inicial...", flush=True)
        build_sync()
    threading.Thread(target=auto_refresh_loop, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"PR dashboard en http://{HOST}:{PORT}/  (Ctrl-C para salir)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
