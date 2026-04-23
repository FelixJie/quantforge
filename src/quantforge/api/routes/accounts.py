"""Account management API — multi-account tracking with fund operations and activity logs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/accounts", tags=["accounts"])

# ── Persistence ────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"
_ACCOUNTS_FILE = _DATA_DIR / "accounts.json"

ACCOUNT_COLORS = [
    "#3b82f6", "#8b5cf6", "#10b981", "#f59e0b",
    "#ef4444", "#06b6d4", "#ec4899", "#84cc16",
]


def _load() -> dict:
    if _ACCOUNTS_FILE.exists():
        try:
            return json.loads(_ACCOUNTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"accounts": [], "fund_records": [], "activity_logs": []}


def _save(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _ACCOUNTS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(data: dict, account_id: str, action: str, detail: str) -> None:
    data["activity_logs"].append({
        "id": str(uuid.uuid4()),
        "account_id": account_id,
        "action": action,
        "detail": detail,
        "timestamp": _now(),
    })


# ── Schemas ────────────────────────────────────────────────────────────────────
class CreateAccountReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)
    type: Literal["paper", "live"] = "paper"
    initial_capital: float = Field(1_000_000.0, ge=0)
    description: str = ""
    color: str = ""


class UpdateAccountReq(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None


class FundOpReq(BaseModel):
    op: Literal["deposit", "withdraw"]
    amount: float = Field(..., gt=0)
    note: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────
def _find(data: dict, account_id: str) -> dict:
    for acc in data["accounts"]:
        if acc["id"] == account_id:
            return acc
    raise HTTPException(404, f"Account {account_id} not found")


def _enrich(acc: dict, data: dict) -> dict:
    """Attach computed fields before returning."""
    pnl = acc["cash"] - acc["initial_capital"]
    pnl_pct = (pnl / acc["initial_capital"] * 100) if acc["initial_capital"] else 0.0
    logs_count = sum(1 for lg in data["activity_logs"] if lg["account_id"] == acc["id"])
    return {
        **acc,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 4),
        "activity_count": logs_count,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.get("")
def list_accounts():
    data = _load()
    accounts = [_enrich(a, data) for a in data["accounts"]]
    total_assets = sum(a["cash"] for a in data["accounts"])
    total_pnl = sum(a["cash"] - a["initial_capital"] for a in data["accounts"])
    return {
        "accounts": accounts,
        "summary": {
            "count": len(accounts),
            "total_assets": round(total_assets, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(
                total_pnl / total_assets * 100 if total_assets else 0, 4
            ),
        },
    }


@router.post("", status_code=201)
def create_account(req: CreateAccountReq):
    data = _load()
    existing_colors = {a["color"] for a in data["accounts"]}
    color = req.color
    if not color:
        for c in ACCOUNT_COLORS:
            if c not in existing_colors:
                color = c
                break
        if not color:
            color = ACCOUNT_COLORS[len(data["accounts"]) % len(ACCOUNT_COLORS)]

    acc = {
        "id": str(uuid.uuid4()),
        "name": req.name,
        "type": req.type,
        "color": color,
        "initial_capital": req.initial_capital,
        "cash": req.initial_capital,
        "description": req.description,
        "is_default": len(data["accounts"]) == 0,
        "created_at": _now(),
    }
    data["accounts"].append(acc)
    _log(data, acc["id"], "created", f"账户「{acc['name']}」创建，初始资金 ¥{req.initial_capital:,.2f}")
    _save(data)
    return _enrich(acc, data)


@router.get("/{account_id}")
def get_account(account_id: str):
    data = _load()
    acc = _find(data, account_id)
    fund_records = [r for r in data["fund_records"] if r["account_id"] == account_id]
    activity_logs = [lg for lg in data["activity_logs"] if lg["account_id"] == account_id]
    return {
        **_enrich(acc, data),
        "fund_records": sorted(fund_records, key=lambda r: r["timestamp"], reverse=True),
        "activity_logs": sorted(activity_logs, key=lambda lg: lg["timestamp"], reverse=True),
    }


@router.put("/{account_id}")
def update_account(account_id: str, req: UpdateAccountReq):
    data = _load()
    acc = _find(data, account_id)
    if req.name is not None:
        acc["name"] = req.name
    if req.description is not None:
        acc["description"] = req.description
    if req.color is not None:
        acc["color"] = req.color
    _log(data, account_id, "updated", "账户信息已更新")
    _save(data)
    return _enrich(acc, data)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: str):
    data = _load()
    _find(data, account_id)  # ensure exists
    data["accounts"] = [a for a in data["accounts"] if a["id"] != account_id]
    data["fund_records"] = [r for r in data["fund_records"] if r["account_id"] != account_id]
    data["activity_logs"] = [lg for lg in data["activity_logs"] if lg["account_id"] != account_id]
    _save(data)


@router.post("/{account_id}/fund")
def fund_operation(account_id: str, req: FundOpReq):
    data = _load()
    acc = _find(data, account_id)
    if req.op == "withdraw" and req.amount > acc["cash"]:
        raise HTTPException(400, f"余额不足：当前 ¥{acc['cash']:,.2f}，提取 ¥{req.amount:,.2f}")

    if req.op == "deposit":
        acc["cash"] += req.amount
        acc["initial_capital"] += req.amount  # adjust baseline so P&L reflects trading only
        action_label = "入金"
    else:
        acc["cash"] -= req.amount
        acc["initial_capital"] -= req.amount
        action_label = "出金"

    record = {
        "id": str(uuid.uuid4()),
        "account_id": account_id,
        "op": req.op,
        "amount": req.amount,
        "note": req.note,
        "balance_after": round(acc["cash"], 2),
        "timestamp": _now(),
    }
    data["fund_records"].append(record)
    _log(
        data, account_id, req.op,
        f"{action_label} ¥{req.amount:,.2f}，余额 ¥{acc['cash']:,.2f}"
        + (f"（{req.note}）" if req.note else ""),
    )
    _save(data)
    return {"account": _enrich(acc, data), "record": record}


@router.get("/{account_id}/logs")
def get_logs(account_id: str):
    data = _load()
    _find(data, account_id)
    logs = [lg for lg in data["activity_logs"] if lg["account_id"] == account_id]
    return sorted(logs, key=lambda lg: lg["timestamp"], reverse=True)
