#!/usr/bin/env python3
"""
dashboard_api.py — OpenClaw Dashboard API (hardened).

Legacy routes: /api/status, /api/inbox, /api/outputs, /api/out/{name},
               /api/submit, /graph.json
New routes:    /api/ops/* (delegated to ops.api)

Security:
  - Bind 127.0.0.1 by default (MC_BIND_ALL=1 for 0.0.0.0)
  - API key required for /api/* except /api/status (MC_API_KEY)
  - Request body limit (MC_MAX_BODY, default 1MB)
  - CORS restricted (MC_CORS_ORIGIN, default localhost:8787)
  - Security headers: X-Content-Type-Options, X-Frame-Options, Referrer-Policy
  - Path traversal protection on /api/out/{name} and /api/logs
"""
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, "workspace")
INBOX = os.path.join(BASE, "inbox")
OUT = os.path.join(BASE, "outputs")
APPROVALS = os.path.join(BASE, "approvals")
LOGS_DIR = os.path.join(BASE, "logs")

# --- Security config from env ---
API_KEY = os.environ.get("MC_API_KEY", "")
BIND_ALL = os.environ.get("MC_BIND_ALL", "0") == "1"
CORS_ORIGIN = os.environ.get("MC_CORS_ORIGIN", "http://localhost:8787")
MAX_BODY = int(os.environ.get("MC_MAX_BODY", "1048576"))  # 1MB

BIND_HOST = "0.0.0.0" if BIND_ALL else "127.0.0.1"
PORT = int(os.environ.get("MC_PORT", "8787"))


def sh(cmd):
    p = subprocess.run(cmd, text=True, capture_output=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def list_dir(path, exts=None, limit=200):
    try:
        files = []
        for name in os.listdir(path):
            if exts and not any(name.endswith(e) for e in exts):
                continue
            full = os.path.join(path, name)
            if os.path.isfile(full):
                st = os.stat(full)
                files.append({"name": name, "size": st.st_size, "mtime": int(st.st_mtime)})
        files.sort(key=lambda x: x["mtime"], reverse=True)
        return files[:limit]
    except FileNotFoundError:
        return []


def safe_filename(name: str) -> str:
    name = (name or "").strip()
    if not name:
        name = "tarea_web"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    name = name.replace("..", "_")
    if not name.endswith(".txt"):
        name += ".txt"
    return name


def _is_safe_path(base_dir: str, requested_name: str) -> bool:
    """Validate that resolved path stays within base_dir (anti-traversal)."""
    resolved = os.path.realpath(os.path.join(base_dir, requested_name))
    return resolved.startswith(os.path.realpath(base_dir) + os.sep) or \
           resolved == os.path.realpath(base_dir)


class H(BaseHTTPRequestHandler):

    # --- Security helpers ---

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _cors(self):
        origin = CORS_ORIGIN
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self._security_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _check_auth(self, path: str) -> bool:
        """
        Returns True if request is authorized.
        /api/status is exempt. All other /api/* require valid API key.
        If MC_API_KEY is not set, all requests are allowed (dev mode).
        """
        if not API_KEY:
            return True
        if path == "/api/status":
            return True
        if not path.startswith("/api/"):
            return True

        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()
            return token == API_KEY
        return False

    def _read_body(self) -> bytes | None:
        """Read request body with size limit. Returns None if too large."""
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n > MAX_BODY:
            return None
        return self.rfile.read(n) if n else b"{}"

    # --- Request handlers ---

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self._security_headers()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path

        if not self._check_auth(path):
            self._json(401, {"error": "Unauthorized"})
            return

        # --- Legacy routes ---

        if path == "/api/status":
            code, out = sh(["systemctl", "--user", "is-active", "agent-mvp.service"])
            self._json(200, {"active": out.strip() == "active"})
            return

        if path == "/api/inbox":
            self._json(200, {"files": list_dir(INBOX, exts=[".txt", ".done"])})
            return

        if path == "/api/outputs":
            self._json(200, {"files": list_dir(OUT, exts=[".md"])})
            return

        if path.startswith("/api/out/"):
            name = path.split("/api/out/", 1)[1]
            # Path traversal protection
            if not _is_safe_path(OUT, name):
                self._json(403, {"error": "Invalid path"})
                return
            full = os.path.join(OUT, name)
            if not os.path.isfile(full):
                self._json(404, {"error": "not found"})
                return
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            self._json(200, {"name": name, "content": txt})
            return

        if path == "/graph.json":
            try:
                subprocess.run(
                    ["python3", os.path.join(os.path.dirname(__file__), "graph_build.py")],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except Exception:
                self._json(200, {"nodes": [], "edges": []})
                return

            graph_file = os.path.join(OUT, "graph.json")
            if not os.path.isfile(graph_file):
                self._json(200, {"nodes": [], "edges": []})
                return

            try:
                with open(graph_file, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
            except Exception:
                data = {"nodes": [], "edges": []}

            self._json(200, data)
            return

        # --- /api/ops/* routes ---
        if path.startswith("/api/ops/"):
            try:
                from ops.api import handle_ops_request
                code, result = handle_ops_request("GET", path)
                self._json(code, result)
            except ImportError:
                self._json(503, {"error": "Ops engine not available (missing psycopg)"})
            return

        self._json(404, {"error": "unknown route"})

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path

        if not self._check_auth(path):
            self._json(401, {"error": "Unauthorized"})
            return

        raw_body = self._read_body()
        if raw_body is None:
            self._json(413, {"error": "Request body too large"})
            return

        body_str = raw_body.decode("utf-8", errors="replace")
        try:
            data = json.loads(body_str or "{}")
        except Exception:
            data = {}

        # --- Legacy routes ---
        if path in ("/api/submit", "/api/inbox"):
            try:
                os.makedirs(INBOX, exist_ok=True)
                fname = safe_filename(data.get("name") or data.get("filename") or "tarea_web")
                full = os.path.join(INBOX, fname)

                text = data.get("text") or data.get("content") or ""
                if not text.strip():
                    text = "@pm:\nOBJETIVO: (vacio)\nDONE:\n- [ ] ...\n"

                if os.path.exists(full):
                    base, ext = os.path.splitext(fname)
                    i = 2
                    while True:
                        alt = os.path.join(INBOX, f"{base}_{i}{ext}")
                        if not os.path.exists(alt):
                            full = alt
                            fname = os.path.basename(alt)
                            break
                        i += 1

                with open(full, "w", encoding="utf-8") as f:
                    f.write(text.rstrip() + "\n")

                # Compat: also emit event to ops DB if available
                try:
                    from ops.db import emit_event
                    emit_event(
                        "file.task_created",
                        source="dashboard_api",
                        payload={"filename": fname},
                    )
                except Exception:
                    pass

                self._json(200, {"ok": True, "file": fname})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return

        # --- /api/ops/* routes ---
        if path.startswith("/api/ops/"):
            try:
                from ops.api import handle_ops_request
                code, result = handle_ops_request("POST", path, data)
                self._json(code, result)
            except ImportError:
                self._json(503, {"error": "Ops engine not available (missing psycopg)"})
            return

        self._json(404, {"error": "unknown route"})

    def log_message(self, format, *args):
        """Suppress default stderr logging for cleaner output."""
        pass


if __name__ == "__main__":
    print(f"Dashboard API en http://{BIND_HOST}:{PORT} "
          f"(CORS: {CORS_ORIGIN}, auth: {'required' if API_KEY else 'disabled'})")
    HTTPServer((BIND_HOST, PORT), H).serve_forever()
