from fastapi import APIRouter

from app.context import get_ctx

router = APIRouter(prefix="/api/companion", tags=["companion"])


@router.get("")
def companion():
    return get_ctx().companion()


@router.get("/coaching")
def coaching():
    return get_ctx().companion()["coaching"]
