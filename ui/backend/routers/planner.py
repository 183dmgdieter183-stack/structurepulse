"""Planner router — delegates all logic to sp_bridge service layer."""
from fastapi import APIRouter
from pydantic import BaseModel
from backend.services import sp_bridge

router = APIRouter(prefix="/api/plan", tags=["planner"])


class PlanRequest(BaseModel):
    problem: str
    language: str | None = None


@router.post("")
def plan(req: PlanRequest):
    return sp_bridge.plan_problem(req.problem, language=req.language)
