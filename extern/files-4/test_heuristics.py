"""
Tests for Role-Inconsistency Detection (Sprint 19).

Each test builds a minimal GraphResult with the exact structure
needed to trigger (or not trigger) the target heuristic.
"""
import tempfile
import shutil
from pathlib import Path


# ── Fixture builder ───────────────────────────────────────────────────────────

def _make_repo(files: dict) -> str:
    d = tempfile.mkdtemp()
    for name, content in files.items():
        Path(d, name).write_text(content)
    return d


def _scan(workspace: str):
    """Return (metrics, graph) for workspace."""
    from structurepulse.parser import parse_path
    from structurepulse.graph.builder import GraphBuilder
    from structurepulse.metrics.engine import MetricsEngine
    pr = parse_path(workspace)
    graph = GraphBuilder().build(pr)
    metrics = MetricsEngine().compute(graph)
    return metrics, graph


def _cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)


# ── H1: Hidden Hub ────────────────────────────────────────────────────────────

def t_h1_hidden_hub_detected():
    """utils.py imported by >50% of modules → H1 warning."""
    files = {
        "utils.py":   "def helper(): return 42\n",
        "alpha.py":   "from utils import helper\ndef do_alpha(): return helper()\n",
        "beta.py":    "from utils import helper\ndef do_beta(): return helper()\n",
        "gamma.py":   "from utils import helper\ndef do_gamma(): return helper()\n",
        "delta.py":   "def do_delta(): return 1\n",  # doesn't import utils
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        codes = [w.code for w in metrics.inconsistencies]
        h1 = [w for w in metrics.inconsistencies if w.code == "H1"]
        assert len(h1) >= 1, f"Expected H1 warning, got: {metrics.inconsistencies}"
        assert "utils.py" in h1[0].module, f"Wrong module: {h1[0].module}"
    finally:
        _cleanup(d)


def t_h1_not_triggered_on_thin_utils():
    """utils.py imported by only 1 module, low coupling → no H1."""
    files = {
        "utils.py":   "def helper(): return 42\n",
        "alpha.py":   "from utils import helper\ndef do_alpha(): return helper()\n",
        "beta.py":    "def do_beta(): return 1\n",
        "gamma.py":   "def do_gamma(): return 2\n",
        "delta.py":   "def do_delta(): return 3\n",
        "epsilon.py": "def do_epsilon(): return 4\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        h1 = [w for w in metrics.inconsistencies if w.code == "H1"]
        assert len(h1) == 0, f"Unexpected H1 on thin utils: {h1}"
    finally:
        _cleanup(d)


# ── H2: Layer Inversion ───────────────────────────────────────────────────────

def t_h2_layer_inversion_detected():
    """model.py importing user_service.py → H2 warning."""
    files = {
        "user_model.py":   "from user_service import UserService\nclass User:\n    pass\n",
        "user_service.py": "class UserService:\n    def get(self): return None\n",
        "main.py":         "from user_model import User\nfrom user_service import UserService\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        h2 = [w for w in metrics.inconsistencies if w.code == "H2"]
        assert len(h2) >= 1, f"Expected H2, got: {metrics.inconsistencies}"
        assert "user_model.py" in h2[0].module_path
    finally:
        _cleanup(d)


def t_h2_not_triggered_on_clean_layers():
    """service.py importing model.py is correct — no H2."""
    files = {
        "user_model.py":   "class User:\n    def __init__(self, name): self.name = name\n",
        "user_service.py": "from user_model import User\nclass UserService:\n    def create(self, name): return User(name)\n",
        "main.py":         "from user_service import UserService\nif __name__ == '__main__': UserService().create('x')\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        h2 = [w for w in metrics.inconsistencies if w.code == "H2"]
        assert len(h2) == 0, f"Unexpected H2 on clean layers: {h2}"
    finally:
        _cleanup(d)


# ── H3: Responsibility Leak ───────────────────────────────────────────────────

def t_h3_responsibility_leak_detected():
    """config.py importing business_logic.py → H3 warning."""
    files = {
        "config.py":          "from business_logic import compute\nSETTING = compute(1)\n",
        "business_logic.py":  "def compute(x):\n    for i in range(x): pass\n    return x * 2\n",
        "main.py":            "from config import SETTING\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        h3 = [w for w in metrics.inconsistencies if w.code == "H3"]
        assert len(h3) >= 1, f"Expected H3, got: {metrics.inconsistencies}"
        assert "config.py" in h3[0].module_path
    finally:
        _cleanup(d)


def t_h3_not_triggered_on_passive_config():
    """config.py with only constants → no H3."""
    files = {
        "config.py":    "DB_URL = 'postgresql://localhost/db'\nDEBUG = False\nMAX_RETRIES = 3\n",
        "service.py":   "from config import DB_URL\nclass Svc:\n    def connect(self): return DB_URL\n",
        "main.py":      "from service import Svc\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        h3 = [w for w in metrics.inconsistencies if w.code == "H3"]
        assert len(h3) == 0, f"Unexpected H3 on passive config: {h3}"
    finally:
        _cleanup(d)


# ── H4: Dead Weight ───────────────────────────────────────────────────────────

def t_h4_dead_weight_detected():
    """payment_service.py with functions but no outgoing imports → H4."""
    files = {
        "payment_service.py": "def process(amount):\n    return amount * 1.0\ndef refund(amount):\n    return amount\n",
        "order_service.py":   "from payment_service import process\ndef place(amount): return process(amount)\n",
        "main.py":            "from order_service import place\nplace(100)\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        h4 = [w for w in metrics.inconsistencies if w.code == "H4"]
        assert len(h4) >= 1, f"Expected H4, got: {metrics.inconsistencies}"
        assert "payment_service.py" in h4[0].module_path
    finally:
        _cleanup(d)


def t_h4_not_triggered_on_active_service():
    """payment_service.py with outgoing imports → no H4."""
    files = {
        "payment_gateway.py": "def charge(amount): return True\n",
        "payment_service.py": "from payment_gateway import charge\ndef process(a): return charge(a)\n",
        "main.py":            "from payment_service import process\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        h4 = [w for w in metrics.inconsistencies if w.code == "H4"]
        ps_h4 = [w for w in h4 if "payment_service" in w.module_path]
        assert len(ps_h4) == 0, f"Unexpected H4 on active service: {ps_h4}"
    finally:
        _cleanup(d)


# ── All four smells in one repo ───────────────────────────────────────────────

def t_all_four_smells_in_one_scan():
    """
    A single repo with all four smell patterns.
    Expect at least one warning per code: H1, H2, H3, H4.
    """
    files = {
        # H1: helper imported by 3 of 4 peers
        "helpers.py":         "def fmt(x): return str(x)\n",
        "alpha.py":           "from helpers import fmt\ndef fa(): return fmt(1)\n",
        "beta.py":            "from helpers import fmt\ndef fb(): return fmt(2)\n",
        "gamma.py":           "from helpers import fmt\ndef fc(): return fmt(3)\n",
        # H2: model imports controller
        "invoice_model.py":   "from invoice_controller import InvoiceCtrl\nclass Invoice: ctrl = InvoiceCtrl()\n",
        "invoice_controller.py": "class InvoiceCtrl:\n    def create(self): return {}\n",
        # H3: settings leaking into business logic
        "settings.py":        "from invoice_controller import InvoiceCtrl\nDEFAULT_CTRL = InvoiceCtrl()\n",
        # H4: notification_service with no outgoing edges
        "notification_service.py": "def notify(msg):\n    return f'sent: {msg}'\n",
    }
    d = _make_repo(files)
    try:
        metrics, _ = _scan(d)
        found_codes = {w.code for w in metrics.inconsistencies}
        missing = {"H1", "H2", "H3", "H4"} - found_codes
        assert not missing, (
            f"Missing smell codes: {missing}. "
            f"Found: {[(w.code, w.module) for w in metrics.inconsistencies]}"
        )
    finally:
        _cleanup(d)


# ── AgentAPI exposes inconsistencies ─────────────────────────────────────────

def t_agent_api_scan_exposes_inconsistencies():
    """AgentAPI.scan() must include 'inconsistencies' key with at least one entry."""
    files = {
        "helpers.py": "def h(): return 1\n",
        "a.py": "from helpers import h\ndef fa(): return h()\n",
        "b.py": "from helpers import h\ndef fb(): return h()\n",
        "c.py": "from helpers import h\ndef fc(): return h()\n",
        "d.py": "def fd(): return 0\n",
    }
    d = _make_repo(files)
    try:
        from structurepulse.agent.api import AgentAPI
        result = AgentAPI(d).scan()
        assert "inconsistencies" in result, f"missing 'inconsistencies' key: {result.keys()}"
        inc = result["inconsistencies"]
        assert isinstance(inc, list)
        codes = [i["code"] for i in inc]
        assert "H1" in codes, f"H1 not in agent scan result: {inc}"
    finally:
        _cleanup(d)
