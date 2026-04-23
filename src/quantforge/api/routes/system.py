"""System health and info endpoints."""

from datetime import datetime

from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/info")
async def info():
    from quantforge import __version__
    return {
        "name": "QuantForge",
        "version": __version__,
        "description": "Modern quantitative trading system",
    }
