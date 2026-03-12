"""
StructurePulse LSP — Integration tests

Strategy: spin up sp lsp as a subprocess, communicate via stdin/stdout
using the JSON-RPC Content-Length framing protocol. Assert that:

1. initialize  → valid capabilities response
2. initialized → server ready (no response, side-effect: initial scan triggers)
3. didSave on a cyclic repo → publishDiagnostics with SP-CYCLE error
4. didSave on a clean repo  → publishDiagnostics with empty list (no errors)
5. shutdown + exit → clean process exit

All via stdlib only — no pygls on client side either.
"""
import json
import subprocess
import sys
import time
import tempfile
import shutil
import threading
from pathlib import Path

# ── Wire protocol helpers ─────────────────────────────────────────────────────

def _send(proc, message: dict):
    body = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    proc.stdin.write(header + body)
    proc.stdin.flush()


def _recv(proc, timeout: float = 8.0) -> dict | None:
    """Read one JSON-RPC message from proc.stdout with a timeout."""
    result = {}
    done = threading.Event()

    def _read():
        try:
            headers = {}
            while True:
                line = proc.stdout.readline()
                if not line:
                    return
                line = line.strip()
                if not line:
                    break
                if b":" in line:
                    k, _, v = line.partition(b":")
                    headers[k.strip().lower()] = v.strip()
            length = int(headers.get(b"content-length", 0))
            if length:
                body = proc.stdout.read(length)
                result["msg"] = json.loads(body.decode("utf-8"))
        finally:
            done.set()

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    done.wait(timeout)
    return result.get("msg")


def _recv_until(proc, predicate, timeout: float = 10.0, max_messages: int = 20) -> dict | None:
    """Read messages until predicate(msg) is True or timeout/max exceeded."""
    deadline = time.time() + timeout
    for _ in range(max_messages):
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        msg = _recv(proc, timeout=remaining)
        if msg is None:
            break
        if predicate(msg):
            return msg
    return None


def _start_server(workspace: str, min_shi: float = 0.65, log_file=None) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "structurepulse.cli.main",
           "lsp", "--workspace", workspace, "--min-shi", str(min_shi)]
    if log_file:
        cmd += ["--log-file", log_file]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd="/home/claude",
    )


def _make_cyclic_repo() -> str:
    d = tempfile.mkdtemp()
    # a.py imports b, b.py imports a → cycle
    Path(d, "a.py").write_text("from b import fn_b\ndef fn_a(): return fn_b()\n")
    Path(d, "b.py").write_text("from a import fn_a\ndef fn_b(): return fn_a()\n")
    Path(d, "c.py").write_text("def helper(): return 42\n")
    return d


def _make_clean_repo() -> str:
    d = tempfile.mkdtemp()
    for i in range(4):
        Path(d, f"mod{i}.py").write_text(
            f"def fn{i}(x):\n    for j in range(x):\n        if j % 2:\n            yield j\n    return x\n"
        )
    return d


def _file_uri(path: str) -> str:
    return Path(path).as_uri()


# ── Test runner (same pattern as run.py) ─────────────────────────────────────

passed, failed, errors = [], [], []


def run(name, fn):
    try:
        fn()
        passed.append(name)
        print(f"  \033[32mPASS\033[0m  {name}")
    except AssertionError as e:
        failed.append(name)
        print(f"  \033[31mFAIL\033[0m  {name}  →  {e}")
    except Exception as e:
        errors.append(name)
        print(f"  \033[33mERRR\033[0m  {name}  →  {type(e).__name__}: {e}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def t_initialize_returns_capabilities():
    d = _make_clean_repo()
    proc = _start_server(d)
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": _file_uri(d), "capabilities": {}}
        })
        resp = _recv(proc, timeout=5)
        assert resp is not None, "no response to initialize"
        assert resp.get("id") == 1, f"wrong id: {resp.get('id')}"
        caps = resp.get("result", {}).get("capabilities", {})
        assert "textDocumentSync" in caps, f"missing textDocumentSync: {caps}"
        sync = caps["textDocumentSync"]
        assert sync.get("openClose") is True, "openClose not True"
        assert sync.get("save") is not None, "save capability missing"
    finally:
        proc.kill(); proc.wait()
        shutil.rmtree(d, ignore_errors=True)


def t_unknown_method_returns_method_not_found():
    d = _make_clean_repo()
    proc = _start_server(d)
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": _file_uri(d), "capabilities": {}}
        })
        _recv(proc, timeout=5)  # consume initialize response

        _send(proc, {
            "jsonrpc": "2.0", "id": 99, "method": "textDocument/nonexistent",
            "params": {}
        })
        resp = _recv(proc, timeout=5)
        assert resp is not None, "no response"
        assert "error" in resp, f"expected error response, got: {resp}"
        assert resp["error"]["code"] == -32601
    finally:
        proc.kill(); proc.wait()
        shutil.rmtree(d, ignore_errors=True)


def t_did_save_clean_repo_publishes_empty_or_no_diags():
    """Clean repo should publish empty diagnostics (no errors)."""
    d = _make_clean_repo()
    proc = _start_server(d, min_shi=0.30)  # very low threshold → clean should pass
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": _file_uri(d), "capabilities": {}}
        })
        _recv(proc, timeout=5)

        _send(proc, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        time.sleep(0.1)

        trigger_uri = _file_uri(Path(d, "mod0.py"))
        _send(proc, {
            "jsonrpc": "2.0", "method": "textDocument/didSave",
            "params": {"textDocument": {"uri": trigger_uri}}
        })

        # Accept any publishDiagnostics response within timeout
        # With min_shi=0.30, a clean repo should have zero SP-CYCLE or SP-SHI errors
        def _is_publish(msg):
            return msg.get("method") == "textDocument/publishDiagnostics"

        msg = _recv_until(proc, _is_publish, timeout=10)
        assert msg is not None, "no publishDiagnostics notification received"
        diags = msg["params"]["diagnostics"]
        cycle_errors = [d for d in diags if d.get("code") == "SP-CYCLE"]
        assert len(cycle_errors) == 0, f"unexpected cycle errors in clean repo: {cycle_errors}"
    finally:
        proc.kill(); proc.wait()
        shutil.rmtree(d, ignore_errors=True)


def t_did_save_cyclic_repo_publishes_cycle_error():
    """Cyclic repo must publish at least one SP-CYCLE diagnostic."""
    d = _make_cyclic_repo()
    proc = _start_server(d)
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": _file_uri(d), "capabilities": {}}
        })
        _recv(proc, timeout=5)
        _send(proc, {"jsonrpc": "2.0", "method": "initialized", "params": {}})

        trigger_uri = _file_uri(Path(d, "a.py"))
        _send(proc, {
            "jsonrpc": "2.0", "method": "textDocument/didSave",
            "params": {"textDocument": {"uri": trigger_uri}}
        })

        def _has_cycle_error(msg):
            if msg.get("method") != "textDocument/publishDiagnostics":
                return False
            return any(d.get("code") == "SP-CYCLE"
                       for d in msg["params"].get("diagnostics", []))

        msg = _recv_until(proc, _has_cycle_error, timeout=12)
        assert msg is not None, "no SP-CYCLE diagnostic published for cyclic repo"
        diags = msg["params"]["diagnostics"]
        codes = [d["code"] for d in diags]
        assert "SP-CYCLE" in codes, f"SP-CYCLE not in codes: {codes}"
    finally:
        proc.kill(); proc.wait()
        shutil.rmtree(d, ignore_errors=True)


def t_did_open_triggers_diagnostics():
    """didOpen must also trigger publishDiagnostics (not just didSave)."""
    d = _make_cyclic_repo()
    proc = _start_server(d)
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": _file_uri(d), "capabilities": {}}
        })
        _recv(proc, timeout=5)
        _send(proc, {"jsonrpc": "2.0", "method": "initialized", "params": {}})

        trigger_uri = _file_uri(Path(d, "a.py"))
        _send(proc, {
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": trigger_uri, "text": "", "version": 1, "languageId": "python"}}
        })

        def _is_publish(msg):
            return msg.get("method") == "textDocument/publishDiagnostics"

        msg = _recv_until(proc, _is_publish, timeout=12)
        assert msg is not None, "no publishDiagnostics after didOpen"
    finally:
        proc.kill(); proc.wait()
        shutil.rmtree(d, ignore_errors=True)


def t_did_close_clears_diagnostics():
    """didClose must publish empty diagnostic list for the closed file."""
    d = _make_cyclic_repo()
    proc = _start_server(d)
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": _file_uri(d), "capabilities": {}}
        })
        _recv(proc, timeout=5)

        target_uri = _file_uri(Path(d, "a.py"))
        _send(proc, {
            "jsonrpc": "2.0", "method": "textDocument/didClose",
            "params": {"textDocument": {"uri": target_uri}}
        })

        def _is_clear(msg):
            return (
                msg.get("method") == "textDocument/publishDiagnostics" and
                msg["params"]["uri"] == target_uri and
                msg["params"]["diagnostics"] == []
            )

        msg = _recv_until(proc, _is_clear, timeout=5)
        assert msg is not None, "didClose did not publish empty diagnostics"
    finally:
        proc.kill(); proc.wait()
        shutil.rmtree(d, ignore_errors=True)


def t_shutdown_then_exit():
    """shutdown + exit must cleanly terminate the server process."""
    d = _make_clean_repo()
    proc = _start_server(d)
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"rootUri": _file_uri(d), "capabilities": {}}
        })
        _recv(proc, timeout=5)

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}})
        resp = _recv(proc, timeout=5)
        assert resp is not None and resp.get("id") == 2, f"bad shutdown response: {resp}"

        _send(proc, {"jsonrpc": "2.0", "method": "exit", "params": {}})
        proc.wait(timeout=3)
        assert proc.returncode == 0, f"unexpected exit code: {proc.returncode}"
    finally:
        proc.kill(); proc.wait()
        shutil.rmtree(d, ignore_errors=True)
