from fastapi import APIRouter

from app.context import get_ctx

router = APIRouter(prefix="/api/companion", tags=["companion"])


@router.get("")
def companion():
    return get_ctx().companion()


@router.get("/coaching")
def coaching():
    return get_ctx().companion()["coaching"]


@router.get("/eco")
def eco():
    return get_ctx().eco()


@router.get("/telemetry")
def telemetry():
    """Latest simulated CAN frames and harsh events (the OBD-II dongle is a stub)."""
    ctx = get_ctx()
    return {"source": ctx.telemetry.source, **(ctx.state.telemetry or {"frames": [], "events": [], "drive": None})}
