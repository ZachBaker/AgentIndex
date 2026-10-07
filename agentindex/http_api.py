"""HTTP JSON API (``agentindex serve``), built on the standard library's http.server.

Binds to localhost by default. Every request reads the index; the sources are
re-scanned at most once per ``sync_interval`` seconds, so edits to docs show up
without restarting the server.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__, render
from .config import Config
from .errors import AgentIndexError, NotFoundError, QueryError
from .store import KnowledgeIndex

ENDPOINTS = {
    "GET /search?q=<terms>[&limit=8][&tag=<tag>]": "ranked docs with best-matching sections",
    "GET /docs[?tag=<tag>]": "every doc with its title and summary",
    "GET /docs/<id>[?section=<anchor>][&format=text]": "a whole doc, or one section",
    "GET /docs/<id>?outline=1": "a doc's headings with anchors and word counts",
    "GET /status": "index status",
    "POST /sync": "re-scan the sources now (also happens automatically)",
    "GET /health": "liveness check",
}


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: Config, sync_interval: float = 1.0):
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, _Handler)
        self.config = config
        self.sync_interval = sync_interval
        self.quiet = False
        self._sync_lock = threading.Lock()
        self._synced_at: float | None = None
        # Every request opens its own connection, and each in-memory database starts empty.
        self._always_sync = config.db_path == ":memory:"

    def open_index(self, force_sync: bool = False) -> KnowledgeIndex:
        """A per-request index (SQLite connections are per-thread), synced if due."""
        index = KnowledgeIndex(self.config, auto_sync=False)
        try:
            with self._sync_lock:
                now = time.monotonic()
                due = self._synced_at is None or now - self._synced_at >= self.sync_interval
                if force_sync or due or self._always_sync:
                    index.sync()
                    self._synced_at = now
        except BaseException:
            index.close()
            raise
        return index


class _Handler(BaseHTTPRequestHandler):
    server: ApiServer
    server_version = f"agentindex/{__version__}"

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def _handle(self, method: str) -> None:
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        path = unquote(url.path).rstrip("/") or "/"
        try:
            status, body = self._route(method, path, params)
        except NotFoundError as exc:
            status, body = 404, {"error": str(exc), "suggestions": exc.suggestions}
        except (QueryError, ValueError) as exc:
            status, body = 400, {"error": str(exc)}
        except AgentIndexError as exc:
            status, body = 500, {"error": str(exc)}
        except Exception as exc:  # report, but keep serving
            self.log_error("internal error on %s: %r", self.path, exc)
            status, body = 500, {"error": f"internal error: {exc}"}
        self._send(status, body)

    def _route(self, method: str, path: str, params: dict) -> tuple[int, object]:
        if path == "/health":
            return 200, {"status": "ok", "version": __version__}
        if path == "/":
            return 200, {"name": "agentindex", "version": __version__, "endpoints": ENDPOINTS}
        if path == "/sync":
            if method != "POST":
                return 405, {"error": "use POST /sync"}
            with self.server.open_index(force_sync=True) as index:
                return 200, index.last_report.to_dict()
        if method != "GET":
            return 405, {"error": f"{method} is not supported on {path}"}
        if path not in ("/search", "/docs", "/status") and not path.startswith("/docs/"):
            return 404, {"error": f"no endpoint {path}", "endpoints": ENDPOINTS}
        with self.server.open_index() as index:
            if path == "/search":
                query = _one(params, "q") or _one(params, "query")
                if not query:
                    raise ValueError("missing ?q=<search terms>")
                limit = _int(params, "limit", 8)
                return 200, index.search(query, limit=limit, tags=params.get("tag", []))
            if path == "/docs":
                return 200, index.list_docs(tags=params.get("tag", []))
            if path == "/status":
                return 200, index.status()
            ref = path[len("/docs/") :]
            if _one(params, "outline") not in (None, "", "0", "false"):
                return 200, index.outline(ref)
            doc = index.read(ref, section=_one(params, "section"))
            if _one(params, "format") in ("text", "md", "markdown"):
                return 200, render.render_doc(doc)
            return 200, doc

    def _send(self, status: int, body: object) -> None:
        if isinstance(body, str):
            data, content_type = body.encode("utf-8"), "text/markdown; charset=utf-8"
        else:
            text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
            data, content_type = text.encode("utf-8"), "application/json; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        if not self.server.quiet:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")


def _one(params: dict, name: str) -> str | None:
    values = params.get(name)
    return values[-1] if values else None


def _int(params: dict, name: str, default: int) -> int:
    value = _one(params, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def serve(config: Config, host: str = "127.0.0.1", port: int = 8765, quiet: bool = False) -> None:
    server = ApiServer((host, port), config)
    server.quiet = quiet
    url = f"http://{f'[{host}]' if ':' in host else host}:{server.server_address[1]}"
    print(f"agentindex API serving {config.root} at {url}", file=sys.stderr)
    print(f"  try: curl '{url}/search?q=getting+started'", file=sys.stderr)
    if not _is_loopback(host):
        print(
            f"  note: {host} is reachable from other machines; the API has no auth", file=sys.stderr
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
