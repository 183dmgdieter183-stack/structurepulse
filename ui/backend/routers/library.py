"""Library router — delegates all logic to sp_bridge service layer."""
from fastapi import APIRouter, Query
from backend.services import sp_bridge

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("")
def list_library(limit: int = Query(80, ge=1, le=200)):
    return sp_bridge.library_list(limit=limit)


@router.get("/search")
def search_library(
    q: str = Query(""),
    language: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    return sp_bridge.library_search(q, language=language, limit=limit)


@router.get("/{entry_id}")
def get_entry(entry_id: str):
    entry = sp_bridge.library_get(entry_id)
    if entry is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Entry not found: {entry_id}")
    return entry
