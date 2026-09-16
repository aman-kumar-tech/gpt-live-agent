"""Static file server for the browser demo (index.html + app.js).

Serves this directory as-is, plus a synthesized /config.js that tells app.js
which token server to call -- read from TOKEN_SERVER_URL/WEB_PORT at request
time, not baked into a file on disk. Two stacks (e.g. a "main" and a
"development" docker-compose project) bind-mount this same directory, so
writing a generated config file here would have one stack's value clobber
the other's; reading the env var per-request avoids that entirely.
"""

from __future__ import annotations

import http.server
import os
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("WEB_PORT", "5500"))
TOKEN_SERVER_URL = os.environ.get("TOKEN_SERVER_URL", "http://localhost:8080")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self):
        # This is a dev server for actively-changing index.html/app.js --
        # without this, browsers happily cache the page/script indefinitely
        # (no validators to bust), so an edit here can silently keep serving
        # a stale copy that looks like the fix "didn't work" (observed: the
        # caller-name field/JS missing client-side after it was added here).
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _config_js_body(self) -> bytes:
        return f"window.TOKEN_SERVER_URL = {TOKEN_SERVER_URL!r};\n".encode()

    def do_GET(self):
        if self.path == "/config.js":
            body = self._config_js_body()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_HEAD(self):
        if self.path == "/config.js":
            body = self._config_js_body()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        super().do_HEAD()


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("", PORT), Handler) as httpd:
        print(f"Serving {WEB_DIR} on port {PORT} (token server: {TOKEN_SERVER_URL})")
        httpd.serve_forever()
