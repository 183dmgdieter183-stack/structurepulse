"""
StructurePulse — HTTP Transport Server
Exposes the local library as a bundle endpoint for remote peers.

Stdlib only: http.server + threading. No Flask, no FastAPI.

Endpoints:
  GET  /api/bundle?min_shi=0.65        → .sptgz bundle download
  GET  /api/status                     → JSON: entry_count, version, node_id
  GET  /api/manifest                   → JSON: entry list with SHI/tags (no sources)

Usage:
  structurepulse network serve [--port 8765] [--min-shi 0.65] [--host 0.0.0.0]
"""
import json
import threading
import hashlib
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime, timezone


class BundleHandler(BaseHTTPRequestHandler):
    """HTTP request handler. workspace_root and min_shi injected via server attrs."""

    def log_message(self, format, *args):
        # suppress default access log — StructurePulse uses its own
        pass

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_binary(self, data: bytes, filename: str):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _parse_min_shi(self, query: str) -> float:
        params = urllib.parse.parse_qs(query)
        try:
            return float(params.get("min_shi", ["0.65"])[0])
        except (ValueError, IndexError):
            return 0.65

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path.rstrip("/")
        query  = parsed.query

        if path == "/api/status":
            self._handle_status()
        elif path == "/api/manifest":
            self._handle_manifest(self._parse_min_shi(query))
        elif path == "/api/bundle":
            self._handle_bundle(self._parse_min_shi(query))
        else:
            self._send_json({"error": f"Unknown endpoint: {path}"}, 404)

    def _handle_status(self):
        from structurepulse.library.agent_library import AgentLibrary
        lib = AgentLibrary(self.server.workspace_root)
        entries = lib.read_all()
        node_id = hashlib.sha256(
            str(self.server.workspace_root).encode()
        ).hexdigest()[:12]
        self._send_json({
            "node_id": node_id,
            "version": "0.5.0",
            "entry_count": len(entries),
            "min_shi_export": self.server.min_shi,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _handle_manifest(self, min_shi: float):
        from structurepulse.library.agent_library import AgentLibrary
        from dataclasses import asdict
        lib = AgentLibrary(self.server.workspace_root)
        entries = [
            e for e in lib.read_all()
            if e.shi >= min_shi
        ]
        self._send_json({
            "entry_count": len(entries),
            "min_shi": min_shi,
            "entries": [
                {
                    "id": e.id,
                    "name": e.name,
                    "language": e.language,
                    "shi": e.shi,
                    "tags": e.tags,
                    "added_at": e.added_at,
                }
                for e in entries
            ],
        })

    def _handle_bundle(self, min_shi: float):
        from structurepulse.library.agent_library import AgentLibrary
        from structurepulse.network.bundle import BundleBuilder
        import tempfile
        try:
            lib = AgentLibrary(self.server.workspace_root)
            builder = BundleBuilder()
            tmp = tempfile.mktemp(suffix=".sptgz")
            builder.build(library=lib, output_path=tmp, shi_threshold=min_shi)
            data = Path(tmp).read_bytes()
            Path(tmp).unlink(missing_ok=True)
            self._send_binary(data, "export.sptgz")
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


class BundleServer:
    """
    Manages the lifecycle of the HTTP server thread.
    """

    def __init__(self, workspace_root: str, port: int = 8765,
                 host: str = "127.0.0.1", min_shi: float = 0.65):
        self.workspace_root = workspace_root
        self.port = port
        self.host = host
        self.min_shi = min_shi
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, background: bool = False):
        self._server = HTTPServer((self.host, self.port), BundleHandler)
        self._server.workspace_root = self.workspace_root
        self._server.min_shi = self.min_shi

        if background:
            self._thread = threading.Thread(
                target=self._server.serve_forever, daemon=True
            )
            self._thread.start()
        else:
            self._server.serve_forever()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None

    def url(self) -> str:
        host = "localhost" if self.host in ("0.0.0.0", "127.0.0.1") else self.host
        return f"http://{host}:{self.port}"
