"""
StructurePulse UI — FastAPI Application Entry Point

Architecture (router → service → sp_bridge):
  main.py imports config, includes all routers
  Routers import sp_bridge functions directly (not via main)
  sp_bridge is the only module that imports structurepulse.*
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from backend.config import APP_TITLE, APP_VERSION, CORS_ORIGINS
from backend.routers import library, scanner, planner, patterns, health

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(library.router)
app.include_router(scanner.router)
app.include_router(planner.router)
app.include_router(patterns.router)
app.include_router(health.router)

_FRONTEND = Path(__file__).parent.parent / "frontend"

if (_FRONTEND / "src").exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND / "src")), name="assets")


@app.get("/", include_in_schema=False)
def serve_homepage():
    return FileResponse(str(_FRONTEND / "homepage.html"))


@app.get("/dashboard", include_in_schema=False)
def serve_dashboard():
    return FileResponse(str(_FRONTEND / "dashboard.html"))
