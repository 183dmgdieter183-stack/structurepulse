"""
StructurePulse UI — Application Configuration
Centralises all runtime settings. No business logic here.
"""
from pathlib import Path
import os

# Resolve paths relative to this file so the app works from any CWD
_UI_ROOT = Path(__file__).parent.parent          # …/ui/
_SP_CODE  = _UI_ROOT.parent / "code"             # …/sstructurepulse/code/

SP_WORKSPACE = os.environ.get("SP_WORKSPACE", str(_SP_CODE))
CORS_ORIGINS  = os.environ.get("CORS_ORIGINS", "*").split(",")
APP_TITLE     = "StructurePulse UI"
APP_VERSION   = "1.0.0"
HOST          = os.environ.get("UI_HOST", "0.0.0.0")
PORT          = int(os.environ.get("UI_PORT", "8000"))
