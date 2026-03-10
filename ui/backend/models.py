"""
Response Models — Pydantic schemas for all API responses.
Centralising schemas here prevents duplication across routers
and ensures every endpoint returns a stable, documented contract.
"""
from pydantic import BaseModel, Field
from typing import Any


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    library_modules: int


class ScanRequest(BaseModel):
    path: str = Field(..., description="Absolute or relative filesystem path to scan")


class ScanResponse(BaseModel):
    path: str
    fingerprint: dict[str, Any]
    metrics: dict[str, Any]
    action_required: list[str] = Field(default_factory=list)


class PlanRequest(BaseModel):
    problem: str = Field(..., min_length=3,
                         description="Natural language description of the architectural challenge")
    language: str | None = Field(None, description="Optional: filter library by language (python / typescript)")


class PlanResponse(BaseModel):
    problem: str
    workspace: str
    recommendation: str
    library_matches: list[dict[str, Any]]
    agent_prompt: str
    steps: list[dict[str, Any]] = Field(default_factory=list)


class LibrarySearchResponse(BaseModel):
    query: str
    count: int
    matches: list[dict[str, Any]]


class PatternInstantiateResponse(BaseModel):
    pattern_id: str
    output_dir: str
    files: list[str]
