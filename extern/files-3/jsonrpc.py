"""
StructurePulse LSP — JSON-RPC 2.0 transport (stdlib only)

LSP wire format:
  Content-Length: <N>\r\n
  \r\n
  <N bytes of UTF-8 JSON>

Implements:
  - JsonRpcReader  — reads from a binary stream (stdin)
  - JsonRpcWriter  — writes to a binary stream (stdout)
  - dispatch()     — routes method → handler, sends response/notification
"""
import json
import sys
import threading
from typing import Callable


class JsonRpcReader:
    def __init__(self, stream=None):
        self._stream = stream or sys.stdin.buffer

    def read_message(self) -> dict | None:
        """Block until a complete JSON-RPC message is available. Return None on EOF."""
        try:
            headers = {}
            while True:
                line = self._stream.readline()
                if not line:
                    return None           # EOF — client disconnected
                line = line.strip()
                if not line:
                    break                 # blank line = end of headers
                if b":" in line:
                    key, _, val = line.partition(b":")
                    headers[key.strip().lower()] = val.strip()

            length = int(headers.get(b"content-length", 0))
            if length == 0:
                return None

            body = self._stream.read(length)
            return json.loads(body.decode("utf-8"))
        except (EOFError, ValueError, json.JSONDecodeError):
            return None


class JsonRpcWriter:
    def __init__(self, stream=None):
        self._stream = stream or sys.stdout.buffer
        self._lock = threading.Lock()

    def send(self, message: dict):
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._lock:
            self._stream.write(header + body)
            self._stream.flush()

    def send_response(self, req_id, result):
        self.send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def send_error(self, req_id, code: int, message: str):
        self.send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": code, "message": message}})

    def send_notification(self, method: str, params: dict):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})
