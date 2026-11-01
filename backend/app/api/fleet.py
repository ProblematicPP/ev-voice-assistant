"""Fleet-management endpoints (battery-aware allocation, demand, rebalancing, longevity)."""
from fastapi import APIRouter, HTTPException

from app.context import get_ctx

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


@router.get("/overview")
def overview():
    return get_ctx().fleet().overview()


@router.get("/allocation")
def allocation():
    """Today's bookings assigned two ways: health-aware vs first-available."""
    f = get_ctx().fleet()
    return {"bookings": f.bookings.fillna("").to_dict("records"), **f.allocation_today()}


@router.get("/rental/{booking_id}/plan")
def rental_plan(booking_id: str):
    f = get_ctx().fleet()
    if booking_id not in set(f.bookings.booking_id):
        raise HTTPException(404, f"unknown booking {booking_id}")
    return f.plan_rental(booking_id)


@router.get("/demand")
def demand(hours: int = 24):
    return get_ctx().fleet().heatmap(max(1, min(hours, 48)))


@router.get("/rebalance")
def rebalance(horizon_h: int = 3):
    return get_ctx().fleet().rebalance(max(1, min(horizon_h, 12)))


@router.get("/longevity")
def longevity():
    """One simulated year of allocations under each policy (cached; takes a few seconds the first time)."""
    return get_ctx().fleet_longevity()
