"""Scanner router — delegates all logic to sp_bridge service layer."""
from fastapi import APIRouter
from pydantic import BaseModel
from backend.services import sp_bridge

router = APIRouter(prefix="/api/scan", tags=["scanner"])


class ScanRequest(BaseModel):
    path: str


@router.post("")
def scan(req: ScanRequest):
    return sp_bridge.scan_path(req.path)


@router.get("/browse")
def browse():
    path = sp_bridge.browse_directory()
    return {"path": path}
