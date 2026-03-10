"""Health router — lightweight liveness and readiness checks."""
from fastapi import APIRouter

_VERSION = "1.0.0"
router = APIRouter(prefix="/api/health", tags=["health"])



@router.get("")
def liveness():
    """Kubernetes-style liveness probe."""
    return {"status": "ok", "version": _VERSION}


@router.get("/ready")
def readiness():
    """Checks that the StructurePulse library is reachable."""
    from backend.services.sp_bridge import library_list
    try:
        result = library_list(limit=1)
        count = result.get("count", 0)
        return {"status": "ready", "library_modules": count}
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"SP bridge unavailable: {exc}")
