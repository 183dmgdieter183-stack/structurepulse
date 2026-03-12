"""Patterns router — delegates all logic to sp_bridge service layer."""
import os
import tempfile
from fastapi import APIRouter, HTTPException
from backend.services import sp_bridge

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


@router.get("")
def list_patterns():
    return {"patterns": sp_bridge.patterns_list()}


@router.get("/{pattern_id}")
def get_pattern(pattern_id: str):
    p = sp_bridge.pattern_get(pattern_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Pattern not found: {pattern_id}")
    return p


@router.post("/{pattern_id}/instantiate")
def instantiate_pattern(pattern_id: str):
    out_dir = tempfile.mkdtemp(prefix=f"sp_pattern_{pattern_id}_")
    try:
        files = sp_bridge.pattern_instantiate(pattern_id, out_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"pattern_id": pattern_id, "output_dir": out_dir, "files": files}
