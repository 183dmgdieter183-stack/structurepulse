"""
Error Handlers — centralises all HTTP exception handling.
Registers custom exception handlers on the FastAPI app so that
any part of the backend gets consistent JSON error shapes.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class SPBridgeError(Exception):
    """Raised when the StructurePulse bridge encounters an unrecoverable error."""
    def __init__(self, message: str, detail: str = ""):
        self.message = message
        self.detail  = detail
        super().__init__(message)


class PathNotFoundError(Exception):
    """Raised when a requested filesystem path does not exist."""
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Path not found: {path}")


def register_handlers(app: FastAPI) -> None:
    """Attach all custom exception handlers to the FastAPI application."""

    @app.exception_handler(SPBridgeError)
    async def sp_bridge_error_handler(request: Request, exc: SPBridgeError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "error": "sp_bridge_error",
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(PathNotFoundError)
    async def path_not_found_handler(request: Request, exc: PathNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "path_not_found",
                "path": exc.path,
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "validation_error", "message": str(exc)},
        )
