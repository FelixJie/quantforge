"""User watchlist API — per-account stock watchlist with metadata.

Endpoints:
  GET    /api/watchlist/           → current user's watchlist
  POST   /api/watchlist/           → add stock to watchlist
  DELETE /api/watchlist/{code}     → remove stock from watchlist
  GET    /api/watchlist/overview   → enriched watchlist (realtime quotes)
  PUT    /api/watchlist/{code}/notes → update notes for a stock
  DELETE /api/watchlist/           → clear watchlist

Storage:
  Per-account rows in the ``watchlist`` table of ``data/cache.db`` (SQLite),
  keyed by (user_id, code).  Quotes are sourced from Tencent (qt.gtimg.cn),
  which works behind proxies that hijack EastMoney.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field

from quantforge.api.routes.auth import get_current_user
from quantforge.data.storage import db_cache

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# ── Schemas ────────────────────────────────────────────────────────────────

class WatchlistItem(BaseModel):
    code: str
    name: str
    added_at: Optional[str] = None
    notes: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)


class WatchlistAddRequest(BaseModel):
    code: str
    name: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[List[str]] = None


class WatchlistUpdateNotes(BaseModel):
    notes: str


class VerificationCreate(BaseModel):
    periodDays: int = 0
    startDate: str = ""
    endDate: str = ""
    totalReturn: float = 0
    results: List[dict] = Field(default_factory=list)


def _verif_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "periodDays": r["period_days"],
        "startDate": r["start_date"],
        "endDate": r["end_date"],
        "totalReturn": r["total_return"],
        "results": r["results"],
        "createdAt": r["created_at"],
    }


# ── Quote enrichment (Tencent — works behind proxy) ──────────────────────────

def _quote_fields(q: dict) -> dict:
    """Map a Tencent quote dict to the overview's quote fields."""
    amt_wan = q.get("amount_wan")
    return {
        "price":      q.get("price"),
        "change_pct": q.get("change_pct"),
        "change":     q.get("change_amt"),
        "high":       q.get("high"),
        "low":        q.get("low"),
        "pre_close":  q.get("last_close"),
        "turnover":   amt_wan * 10000 if amt_wan else None,
        "pe":         q.get("pe_ttm"),
        "pb":         q.get("pb"),
        "turnover_rate": q.get("turnover_pct"),
    }


async def _fetch_quotes(codes: List[str]) -> dict:
    if not codes:
        return {}
    try:
        from quantforge.data.feed.mootdx_feed import _tencent_quote
        raw = await asyncio.to_thread(_tencent_quote, codes)
    except Exception as e:
        logger.debug(f"watchlist quote fetch failed: {e}")
        return {}
    return {code: _quote_fields(q) for code, q in raw.items()}


# ── One-time migration from legacy data/watchlists/{user}.json ───────────────

_LEGACY_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "watchlists"


def _migrate_legacy(user_id: str) -> None:
    """Best-effort import of a user's old JSON watchlist into the DB (once)."""
    f = _LEGACY_DIR / f"{user_id}.json"
    if not f.exists():
        return
    if db_cache.get_watchlist(user_id):
        return  # already has DB rows — don't clobber
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return
    migrated = 0
    for it in data.get("items", []):
        code = (it.get("code") or "").strip().upper()
        if not code:
            continue
        if db_cache.watchlist_add(
            user_id, code, it.get("name", ""), it.get("notes", ""), it.get("tags") or []
        ):
            migrated += 1
    if migrated:
        logger.info(f"watchlist: migrated {migrated} legacy items for user {user_id}")
        try:
            f.rename(f.with_suffix(".json.migrated"))
        except Exception:
            pass


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[WatchlistItem])
async def get_watchlist(current_user: dict = Depends(get_current_user)):
    """Return the current user's watchlist (basic info — no quotes)."""
    uid = current_user["id"]
    _migrate_legacy(uid)
    return db_cache.get_watchlist(uid)


@router.get("/overview")
async def get_watchlist_overview(current_user: dict = Depends(get_current_user)):
    """Return the watchlist enriched with latest market quotes (Tencent)."""
    uid = current_user["id"]
    _migrate_legacy(uid)
    items = db_cache.get_watchlist(uid)
    quote_map = await _fetch_quotes([it["code"] for it in items])
    enriched = [{**it, **(quote_map.get(it["code"]) or {})} for it in items]
    return {"items": enriched, "count": len(enriched), "updated_at": datetime.utcnow().isoformat(timespec="seconds")}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    req: WatchlistAddRequest,
    current_user: dict = Depends(get_current_user),
):
    """Add a stock to the user's watchlist (idempotent on code)."""
    code = req.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="股票代码不能为空")

    uid = current_user["id"]
    existing = db_cache.watchlist_get_item(uid, code)
    if existing is not None:
        return {"status": "exists", "item": existing}

    # Resolve name from stock_meta if not supplied
    name = req.name or ""
    if not name:
        try:
            meta = db_cache.get_stock(code)
            if meta:
                name = meta.get("name", "")
        except Exception:
            pass

    item = db_cache.watchlist_add(uid, code, name, req.notes or "", req.tags or [])
    if item is None:
        # Race: inserted between check and add
        return {"status": "exists", "item": db_cache.watchlist_get_item(uid, code)}
    count = len(db_cache.get_watchlist(uid))
    return {"status": "added", "item": item, "count": count}


@router.delete("/{code}")
async def remove_from_watchlist(
    code: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a stock from the user's watchlist by code."""
    code = code.strip().upper()
    if not db_cache.watchlist_remove(current_user["id"], code):
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    count = len(db_cache.get_watchlist(current_user["id"]))
    return {"status": "removed", "code": code, "count": count}


@router.put("/{code}/notes")
async def update_notes(
    code: str,
    req: WatchlistUpdateNotes,
    current_user: dict = Depends(get_current_user),
):
    """Update the user's personal notes for a specific stock."""
    code = code.strip().upper()
    item = db_cache.watchlist_update_notes(current_user["id"], code, req.notes or "")
    if item is None:
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    return {"status": "updated", "item": item}


@router.delete("/")
async def clear_watchlist(current_user: dict = Depends(get_current_user)):
    """Remove all stocks from the user's watchlist."""
    n = db_cache.watchlist_clear(current_user["id"])
    return {"status": "cleared", "count": n}


# ── Verification records (per-account) ───────────────────────────────────────

@router.get("/verifications")
async def list_verifications(current_user: dict = Depends(get_current_user)):
    """List the current user's saved watchlist-verification snapshots."""
    rows = db_cache.get_watch_verifications(current_user["id"])
    return [_verif_out(r) for r in rows]


@router.post("/verifications", status_code=status.HTTP_201_CREATED)
async def create_verification(
    req: VerificationCreate,
    current_user: dict = Depends(get_current_user),
):
    """Persist a verification snapshot (computed client-side) for this account."""
    saved = db_cache.add_watch_verification(
        current_user["id"], req.periodDays, req.startDate, req.endDate,
        req.totalReturn, req.results,
    )
    if saved is None:
        raise HTTPException(status_code=500, detail="保存验证记录失败")
    return _verif_out(saved)


@router.delete("/verifications/{vid}")
async def delete_verification(
    vid: int,
    current_user: dict = Depends(get_current_user),
):
    """Delete one verification snapshot by id."""
    if not db_cache.delete_watch_verification(current_user["id"], vid):
        raise HTTPException(status_code=404, detail="未找到该验证记录")
    return {"status": "removed", "id": vid}
