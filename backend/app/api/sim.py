"""Demo controls: tweak the synthetic vehicle state and advance the simulated drive."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import simulation
from app.api.hub import hub
from app.context import get_ctx

router = APIRouter(prefix="/api/sim", tags=["simulation"])


class Update(BaseModel):
    soc: float | None = Field(None, ge=0.01, le=1.0)
    ambient_temp_c: float | None = Field(None, ge=-10, le=50)
    hvac_mode: str | None = None
    payload_kg: float | None = Field(None, ge=0, le=500)
    driving_style: float | None = Field(None, ge=0, le=1)
    location: str | None = None
    plugged_in: bool | None = None


class Drive(BaseModel):
    km: float = Field(10, gt=0, le=300)


SCENARIOS = {
    "default": {},
    "low_far_from_home": {"soc": 0.18, "location": "ramanagara", "ambient_temp_c": 33, "hvac_mode": "ac"},
    "hot_day_plugged_in": {"soc": 0.72, "location": "koramangala", "ambient_temp_c": 38, "plugged_in": True},
    "cold_morning": {"soc": 0.60, "ambient_temp_c": 8, "hvac_mode": "heat", "driving_style": 0.75},
    "full_battery": {"soc": 0.95, "ambient_temp_c": 26, "hvac_mode": "fan"},
    # Mysuru is just reachable direct; heat + AC mid-drive pushes it below reserve
    "road_trip": {"soc": 0.82, "ambient_temp_c": 26, "hvac_mode": "fan"},
}


def _apply(upd: dict):
    ctx = get_ctx()
    st = ctx.state
    if "location" in upd and upd["location"] not in ctx.net.nodes:
        raise HTTPException(400, f"unknown node {upd['location']}")
    if "hvac_mode" in upd and upd["hvac_mode"] not in ("off", "fan", "ac", "heat"):
        raise HTTPException(400, "hvac_mode must be off|fan|ac|heat")
    for k, v in upd.items():
        setattr(st, k, v)
    if upd.get("plugged_in") is False:
        st.precooling = False


async def _after_change():
    await hub.check_nudges()
    await hub.push_state()
    return get_ctx().snapshot()


@router.post("/update")
async def update(u: Update):
    _apply(u.model_dump(exclude_none=True))
    return await _after_change()


@router.post("/drive")
async def drive(d: Drive):
    events = simulation.drive(get_ctx(), d.km)
    snap = await _after_change()
    return {"events": events, "state": snap}


@router.post("/scenario/{name}")
async def scenario(name: str):
    if name not in SCENARIOS:
        raise HTTPException(404, f"scenarios: {list(SCENARIOS)}")
    ctx = get_ctx()
    ctx.reset()
    _apply(SCENARIOS[name])
    return await _after_change()


@router.post("/reset")
async def reset():
    get_ctx().reset()
    return await _after_change()
