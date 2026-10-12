from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.battery_core import guard
from app.context import get_ctx

router = APIRouter(prefix="/api", tags=["routing"])


class PlanRequest(BaseModel):
    destinations: list[str]
    origin: str | None = None
    soc: float | None = None


@router.get("/network")
def network():
    return get_ctx().net.to_dict()


@router.post("/route/plan")
def plan(req: PlanRequest):
    """Plan without activating (the assistant's navigate_to activates)."""
    ctx = get_ctx()
    origin = req.origin or ctx.state.location
    nodes = []
    for d in req.destinations:
        t = ctx.net.resolve(d, origin)
        if not t:
            raise HTTPException(404, f"Unknown place: {d}")
        nodes.append(t["node"])
    soc = req.soc if req.soc is not None else ctx.state.soc
    p = ctx.planner.plan(origin, nodes, soc, ctx.battery.conditions(ctx.state))
    return {"plan": p, "guard": guard.assess_plan(p).to_dict()}
