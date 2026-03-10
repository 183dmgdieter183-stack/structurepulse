"""
StructurePulse — Language Server Protocol Server (stdlib, no pygls)

Transport: JSON-RPC 2.0 over stdio (Content-Length framing).
Compatible with VS Code, Neovim, Emacs LSP-mode, Helix, etc.

Supported LSP methods:
  initialize                → capabilities handshake
  initialized               → server ready notification
  textDocument/didOpen      → trigger scan + publish diagnostics
  textDocument/didSave      → trigger scan + publish diagnostics
  textDocument/didClose     → clear diagnostics for closed file
  workspace/didChangeConfiguration → update min_shi threshold
  shutdown                  → orderly shutdown
  exit                      → process exit

Start via:
  structurepulse lsp [--workspace .] [--min-shi 0.65] [--log-file /tmp/sp-lsp.log]
"""
from __future__ import annotations

import os
import sys
import logging
import threading
from pathlib import Path
from typing import Callable

from .jsonrpc import JsonRpcReader, JsonRpcWriter


# ── Logging (to file — never stdout, that's the LSP wire) ────────────────────

def _setup_logging(log_file: str | None):
    if log_file:
        logging.basicConfig(
            filename=log_file,
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
    else:
        logging.disable(logging.CRITICAL)

log = logging.getLogger("sp.lsp")


# ── Server ────────────────────────────────────────────────────────────────────

class StructurePulseLSP:
    """
    Minimal LSP server. Reads requests/notifications from stdin,
    writes responses and publishDiagnostics notifications to stdout.
    """

    SERVER_INFO = {
        "name": "structurepulse-lsp",
        "version": "0.1.0",
    }

    def __init__(self, workspace_root: str = ".", min_shi: float = 0.65,
                 reader: JsonRpcReader = None, writer: JsonRpcWriter = None):
        self.workspace_root = str(Path(workspace_root).resolve())
        self.min_shi = min_shi

        self._reader = reader or JsonRpcReader(sys.stdin.buffer)
        self._writer = writer or JsonRpcWriter(sys.stdout.buffer)

        self._shutdown_requested = False
        self._initialized = False
        self._scan_lock = threading.Lock()   # one scan at a time

        # Method → handler mapping
        self._handlers: dict[str, Callable] = {
            "initialize":                          self._handle_initialize,
            "initialized":                         self._handle_initialized,
            "shutdown":                            self._handle_shutdown,
            "exit":                                self._handle_exit,
            "textDocument/didOpen":                self._handle_did_open,
            "textDocument/didSave":                self._handle_did_save,
            "textDocument/didClose":               self._handle_did_close,
            "workspace/didChangeConfiguration":    self._handle_config_change,
            # Common editor pings — respond gracefully
            "textDocument/didChange":              self._noop,
            "$/cancelRequest":                     self._noop,
            "$/setTrace":                          self._noop,
        }

    # ── Main loop ─────────────────────────────────────────────────────────────

    def serve(self):
        """Blocking read-dispatch loop."""
        log.info("StructurePulse LSP server started (workspace: %s)", self.workspace_root)
        while True:
            message = self._reader.read_message()
            if message is None:
                log.info("Client disconnected — exiting.")
                break

            method  = message.get("method", "")
            msg_id  = message.get("id")      # None for notifications
            params  = message.get("params", {}) or {}

            log.debug("← %s (id=%s)", method, msg_id)

            if self._shutdown_requested and method != "exit":
                if msg_id is not None:
                    self._writer.send_error(msg_id, -32600, "Server is shutting down")
                continue

            handler = self._handlers.get(method)
            if handler is None:
                log.debug("Unhandled method: %s", method)
                if msg_id is not None:
                    # LSP spec: unknown request → MethodNotFound
                    self._writer.send_error(msg_id, -32601, f"Method not found: {method}")
                continue

            try:
                result = handler(params)
                if msg_id is not None and result is not None:
                    log.debug("→ response to %s (id=%s)", method, msg_id)
                    self._writer.send_response(msg_id, result)
            except Exception as e:
                log.exception("Handler error for %s: %s", method, e)
                if msg_id is not None:
                    self._writer.send_error(msg_id, -32603, f"Internal error: {e}")

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _handle_initialize(self, params: dict) -> dict:
        # Client may supply a workspaceFolders or rootUri — prefer those
        root_uri = (
            params.get("rootUri") or
            params.get("rootPath") or
            self.workspace_root
        )
        if root_uri and root_uri.startswith("file://"):
            from urllib.parse import unquote
            self.workspace_root = unquote(root_uri[7:])

        log.info("initialize: workspace=%s", self.workspace_root)

        return {
            "capabilities": {
                "textDocumentSync": {
                    "openClose": True,
                    "save":      {"includeText": False},
                    "change":    0,   # None = we don't need incremental updates
                },
                "diagnosticProvider": {
                    "interFileDependencies": True,
                    "workspaceDiagnostics":  False,
                },
            },
            "serverInfo": self.SERVER_INFO,
        }

    def _handle_initialized(self, _params) -> None:
        self._initialized = True
        log.info("Server is ready.")
        # Trigger an initial scan so diagnostics appear without saving
        self._trigger_scan(None)
        return None

    def _handle_shutdown(self, _params) -> dict:
        self._shutdown_requested = True
        log.info("Shutdown requested.")
        return {}   # LSP: respond with null/empty

    def _handle_exit(self, _params) -> None:
        log.info("Exit.")
        sys.exit(0 if self._shutdown_requested else 1)

    def _handle_did_open(self, params: dict) -> None:
        uri = params.get("textDocument", {}).get("uri", "")
        log.debug("didOpen: %s", uri)
        self._trigger_scan(uri)
        return None

    def _handle_did_save(self, params: dict) -> None:
        uri = params.get("textDocument", {}).get("uri", "")
        log.debug("didSave: %s", uri)
        self._trigger_scan(uri)
        return None

    def _handle_did_close(self, params: dict) -> None:
        uri = params.get("textDocument", {}).get("uri", "")
        log.debug("didClose: %s — clearing diagnostics", uri)
        # Clear diagnostics for the closed file
        self._writer.send_notification("textDocument/publishDiagnostics", {
            "uri": uri, "diagnostics": []
        })
        return None

    def _handle_config_change(self, params: dict) -> None:
        settings = params.get("settings", {}).get("structurepulse", {})
        if "minShi" in settings:
            self.min_shi = float(settings["minShi"])
            log.info("min_shi updated to %s", self.min_shi)
        return None

    def _noop(self, _params) -> None:
        return None

    # ── Scan + publish ─────────────────────────────────────────────────────────

    def _trigger_scan(self, trigger_uri: str | None):
        """Run scan in a background thread to avoid blocking the read loop."""
        t = threading.Thread(
            target=self._scan_and_publish,
            args=(trigger_uri,),
            daemon=True,
        )
        t.start()

    def _scan_and_publish(self, trigger_uri: str | None):
        from .diagnostics import DiagnosticsProducer

        with self._scan_lock:   # serialize concurrent saves
            log.info("Scanning %s ...", self.workspace_root)
            try:
                producer = DiagnosticsProducer(
                    workspace_root=self.workspace_root,
                    min_shi=self.min_shi,
                )
                diag_map = producer.scan()
            except Exception as e:
                log.exception("DiagnosticsProducer failed: %s", e)
                return

        # Publish results for every file that has diagnostics
        published_uris = set()
        for uri, diags in diag_map.items():
            log.debug("Publishing %d diagnostic(s) for %s", len(diags), uri)
            self._writer.send_notification("textDocument/publishDiagnostics", {
                "uri": uri,
                "diagnostics": [d.to_dict() for d in diags],
            })
            published_uris.add(uri)

        # Clear diagnostics for the triggering file if it has none
        if trigger_uri and trigger_uri not in published_uris:
            self._writer.send_notification("textDocument/publishDiagnostics", {
                "uri": trigger_uri,
                "diagnostics": [],
            })
