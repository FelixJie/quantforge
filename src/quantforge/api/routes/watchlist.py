"""User watchlist API — per-user stock watchlist with metadata.

Endpoints:
  GET    /api/watchlist/           → current user's watchlist
  POST   /api/watchlist/           → add stock to watchlist
  DELETE /api/watchlist/{code}     → remove stock from watchlist
  GET    /api/watchlist/overview   → enriched watchlist (realtime quotes + charts)
  PUT    /api/watchlist/{code}/notes → update notes for a stock

Data persistence:
  Each user has an independent watchlist stored under `data/watchlists/{user_id}.json`.
  Watchlist items carry: {code, name, added_at, notes, tags[]}.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from quantforge.api.routes.auth import get_current_user

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

_DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"
_WATCHLIST_DIR = _DATA_DIR / "watchlists"
_WATCHLIST_DIR.mkdir(parents=True, exist_ok=True)


# ── Schemas ────────────────────────────────────────────────────────────────

class WatchlistItem(BaseModel):
    code: str
    name: str
    added_at: str
    notes: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)


class WatchlistAddRequest(BaseModel):
    code: str
    name: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[List[str]] = None


class WatchlistUpdateNotes(BaseModel):
    notes: str


class WatchlistOverviewItem(WatchlistItem):
    price: Optional[float] = None
    change_pct: Optional[float] = None
    change: Optional[float] = None
    volume: Optional[float] = None
    turnover: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    pre_close: Optional[float] = None


# ── File helpers ────────────────────────────────────────────────────────────

def _path_for(user_id: str) -> Path:
    return _WATCHLIST_DIR / f"{user_id}.json"


def _load(user_id: str) -> dict:
    p = _path_for(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"items": [], "updated_at": None}


def _save(user_id: str, data: dict) -> None:
    data["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    _path_for(user_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _enrich_with_quotes(items: List[dict]) -> List[dict]:
    """Best-effort: attach latest market quote to each item.

    Uses the same efinance endpoint as the `market` router so we don't introduce
    a heavy dependency here.  If fetching fails, the items are returned without
    quote data (the UI handles missing fields gracefully).
    """
    import asyncio

    codes = [it["code"] for it in items]
    if not codes:
        return [dict(it) for it in items]

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            quote_map = loop.run_until_complete(_fetch_quotes(codes))
        finally:
            loop.close()
    except Exception:
        quote_map = {}

    result = []
    for it in items:
        row = dict(it)
        q = quote_map.get(it["code"]) or {}
        row.update(q)
        result.append(row)
    return result


async def _fetch_quotes(codes: List[str]) -> dict:
    """Fetch latest quotes from efinance for a list of codes.  Returns {code: quote_dict}."""
    try:
        import efinance as ef

        def _sync():
            try:
                df = ef.stock.get_latest_quote(codes)
                if df is None or df.empty:
                    return {}
            except Exception:
                return {}
            out = {}
            for _, row in df.iterrows():
                try:
                    code = str(row.iloc[0]).strip()
                    price = float(row.iloc[3]) if len(row) > 3 else None
                    change_pct = float(row.iloc[2]) if len(row) > 2 else None
                    change = float(row.iloc[13]) if len(row) > 13 else None
                    volume = float(row.iloc[6]) if len(row) > 6 else None
                    turnover = float(row.iloc[7]) if len(row) > 7 else None
                    high = float(row.iloc[4]) if len(row) > 4 else None
                    low = float(row.iloc[5]) if len(row) > 5 else None
                    pre_close = float(row.iloc[13]) if len(row) > 13 else None
                    out[code] = {
                        "price": price,
                        "change_pct": change_pct,
                        "change": change,
                        "volume": volume,
                        "turnover": turnover,
                        "high": high,
                        "low": low,
                        "pre_close": pre_close,
                    }
                except (ValueError, TypeError, IndexError):
                    continue
            return out

        return await asyncio.to_thread(_sync)
    except Exception:
        return {}


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[WatchlistItem])
async def get_watchlist(current_user: dict = Depends(get_current_user)):
    """Return the current user's watchlist (basic info — no quotes)."""
    data = _load(current_user["id"])
    return data.get("items", [])


@router.get("/overview")
async def get_watchlist_overview(current_user: dict = Depends(get_current_user)):
    """Return the watchlist enriched with latest market quotes."""
    data = _load(current_user["id"])
    items = data.get("items", [])
    enriched = _enrich_with_quotes(items)
    return {"items": enriched, "count": len(enriched), "updated_at": data.get("updated_at")}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    req: WatchlistAddRequest,
    current_user: dict = Depends(get_current_user),
):
    """Add a stock to the user's watchlist.  Duplicate codes are ignored (idempotent)."""
    code = req.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="股票代码不能为空")

    data = _load(current_user["id"])
    items = data.get("items", [])

    # Check existence
    for it in items:
        if it["code"] == code:
            return {"status": "exists", "item": it}

    # Try to auto-resolve the name from market metadata cache if caller didn't supply one
    name = req.name or ""
    if not name:
        try:
            from quantforge.data.storage.stock_meta_cache import _store
            if code in _store:
                name = _store[code].get("name", "")
        except Exception:
            pass

    new_item = {
        "code": code,
        "name": name or code,
        "added_at": datetime.utcnow().isoformat(timespec="seconds"),
        "notes": req.notes or "",
        "tags": req.tags or [],
    }
    items.append(new_item)
    data["items"] = items
    _save(current_user["id"], data)
    return {"status": "added", "item": new_item, "count": len(items)}


@router.delete("/{code}")
async def remove_from_watchlist(
    code: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a stock from the user's watchlist by code."""
    code = code.strip().upper()
    data = _load(current_user["id"])
    items = data.get("items", [])
    new_items = [it for it in items if it["code"] != code]
    if len(new_items) == len(items):
        raise HTTPException(status_code=404, detail="自选股中未找到该股票")
    data["items"] = new_items
    _save(current_user["id"], data)
    return {"status": "removed", "code": code, "count": len(new_items)}


@router.put("/{code}/notes")
async def update_notes(
    code: str,
    req: WatchlistUpdateNotes,
    current_user: dict = Depends(get_current_user),
):
    """Update the user's personal notes for a specific stock."""
    code = code.strip().upper()
    data = _load(current_user["id"])
    items = data.get("items", [])
    for it in items:
        if it["code"] == code:
            it["notes"] = req.notes or ""
            _save(current_user["id"], data)
            return {"status": "updated", "item": it}
    raise HTTPException(status_code=404, detail="自选股中未找到该股票")


@router.delete("/")
async def clear_watchlist(current_user: dict = Depends(get_current_user)):
    """Remove all stocks from the user's watchlist."""
    _save(current_user["id"], {"items": []})
    return {"status": "cleared"}
