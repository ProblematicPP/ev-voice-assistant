from fastapi import APIRouter

from app.context import get_ctx

router = APIRouter(prefix="/api/battery", tags=["battery-core"])


@router.get("/soh")
def soh():
    return get_ctx().battery.soh()


@router.get("/range")
def range_(highway_share: float | None = None):
    ctx = get_ctx()
    return ctx.battery.range(ctx.state, highway_share)


@router.get("/explain")
def explain():
    ctx = get_ctx()
    return ctx.battery.explain_range(ctx.state)
