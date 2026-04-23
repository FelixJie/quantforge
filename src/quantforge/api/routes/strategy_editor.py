"""Strategy editor endpoints — save, load, and generate custom strategies."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/editor", tags=["editor"])

_CUSTOM_DIR = Path("strategies/custom")
_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)


# ── Templates ─────────────────────────────────────────────────────────────────

_TEMPLATES = {
    "dual_ma": """\
\"\"\"双均线策略模板 — 金叉买入，死叉卖出。\"\"\"
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext
from quantforge.core.datatypes import BarData


class MyDualMAStrategy(Strategy):
    name = "my_dual_ma"
    description = "自定义双均线策略"

    def __init__(self, fast_period: int = 10, slow_period: int = 30,
                 symbol: str = "000001", exchange: str = "SZSE", **kwargs):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.symbol = symbol
        self.exchange = exchange

    async def on_init(self, ctx: StrategyContext) -> None:
        ctx.log(f"初始化: fast={self.fast_period}, slow={self.slow_period}")

    async def on_bar(self, bar: BarData) -> None:
        ctx = self._ctx
        df = ctx.get_bars_df(bar.symbol)
        if len(df) < self.slow_period:
            return

        close = df["close"]
        fast_ma = close.rolling(self.fast_period).mean().iloc[-1]
        slow_ma = close.rolling(self.slow_period).mean().iloc[-1]
        prev_fast = close.rolling(self.fast_period).mean().iloc[-2]
        prev_slow = close.rolling(self.slow_period).mean().iloc[-2]

        pos = ctx.get_position(bar.symbol)
        account = ctx.get_account()

        # 金叉买入
        if prev_fast <= prev_slow and fast_ma > slow_ma and not pos:
            volume = int(account.available * 0.9 / bar.close / 100) * 100
            if volume > 0:
                await ctx.buy(bar.symbol, volume, bar.close,
                              exchange=__import__('quantforge.core.constants',
                              fromlist=['Exchange']).Exchange(self.exchange))

        # 死叉卖出
        elif prev_fast >= prev_slow and fast_ma < slow_ma and pos and pos.volume > 0:
            await ctx.sell(bar.symbol, pos.volume, bar.close,
                           exchange=__import__('quantforge.core.constants',
                           fromlist=['Exchange']).Exchange(self.exchange))
""",

    "mean_reversion": """\
\"\"\"均值回归策略模板 — 价格偏离均线时买卖。\"\"\"
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext
from quantforge.core.datatypes import BarData
from quantforge.core.constants import Exchange


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"
    description = "均值回归策略"

    def __init__(self, period: int = 20, std_threshold: float = 2.0,
                 symbol: str = "000001", exchange: str = "SZSE", **kwargs):
        self.period = period
        self.std_threshold = std_threshold
        self.symbol = symbol
        self.exchange = exchange

    async def on_init(self, ctx: StrategyContext) -> None:
        ctx.log(f"均值回归初始化: period={self.period}, threshold={self.std_threshold}σ")

    async def on_bar(self, bar: BarData) -> None:
        ctx = self._ctx
        df = ctx.get_bars_df(bar.symbol)
        if len(df) < self.period + 1:
            return

        close = df["close"]
        ma = close.rolling(self.period).mean().iloc[-1]
        std = close.rolling(self.period).std().iloc[-1]
        if std == 0:
            return

        zscore = (bar.close - ma) / std
        pos = ctx.get_position(bar.symbol)
        account = ctx.get_account()
        exc = Exchange(self.exchange)

        if zscore < -self.std_threshold and (not pos or pos.volume == 0):
            volume = int(account.available * 0.9 / bar.close / 100) * 100
            if volume > 0:
                await ctx.buy(bar.symbol, volume, bar.close, exchange=exc)

        elif zscore > self.std_threshold and pos and pos.volume > 0:
            await ctx.sell(bar.symbol, pos.volume, bar.close, exchange=exc)
""",

    "empty": """\
\"\"\"自定义策略 — 修改此模板实现你的策略逻辑。\"\"\"
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext
from quantforge.core.datatypes import BarData
from quantforge.core.constants import Exchange


class CustomStrategy(Strategy):
    name = "custom"
    description = "自定义策略"

    def __init__(self, symbol: str = "000001", exchange: str = "SZSE", **kwargs):
        self.symbol = symbol
        self.exchange = exchange

    async def on_init(self, ctx: StrategyContext) -> None:
        ctx.log("策略初始化")

    async def on_bar(self, bar: BarData) -> None:
        ctx = self._ctx
        # 在这里实现你的策略逻辑
        # ctx.get_bars_df(bar.symbol)  — 获取历史K线
        # ctx.get_position(bar.symbol) — 获取持仓
        # ctx.get_account()            — 获取账户
        # await ctx.buy(...)           — 买入
        # await ctx.sell(...)          — 卖出
        pass

    async def on_stop(self) -> None:
        self._ctx.log("策略结束")
""",
}


# ── Request models ────────────────────────────────────────────────────────────

class SaveStrategyRequest(BaseModel):
    filename: str    # e.g. "my_strategy"
    code: str


class GenerateRequest(BaseModel):
    description: str
    template: str = "empty"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates():
    return [{"id": k, "preview": v[:120] + "..."} for k, v in _TEMPLATES.items()]


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    code = _TEMPLATES.get(template_id)
    if not code:
        raise HTTPException(status_code=404, detail=f"Template {template_id!r} not found")
    return {"template_id": template_id, "code": code}


@router.get("/strategies")
async def list_custom_strategies():
    """List all saved custom strategies."""
    result = []
    for f in sorted(_CUSTOM_DIR.glob("*.py")):
        code = f.read_text(encoding="utf-8")
        result.append({
            "filename": f.stem,
            "module_path": f"strategies.custom.{f.stem}",
            "code_preview": code[:200],
            "size": len(code),
        })
    return result


@router.get("/strategies/{filename}")
async def get_strategy(filename: str):
    """Load a saved custom strategy."""
    path = _CUSTOM_DIR / f"{filename}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Strategy {filename!r} not found")
    return {"filename": filename, "code": path.read_text(encoding="utf-8")}


@router.post("/strategies")
async def save_strategy(req: SaveStrategyRequest):
    """Save a custom strategy to disk and validate it can be imported."""
    # Sanitize filename
    filename = req.filename.strip().replace(" ", "_")
    if not filename.isidentifier():
        raise HTTPException(status_code=400, detail="Invalid filename (must be a valid Python identifier)")

    path = _CUSTOM_DIR / f"{filename}.py"

    # Validate syntax
    try:
        compile(req.code, f"<{filename}>", "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Syntax error: {e}")

    path.write_text(req.code, encoding="utf-8")

    # Attempt import to get class name
    module_path = f"strategies.custom.{filename}"
    class_name = _detect_class_name(req.code)

    return {
        "filename": filename,
        "module_path": f"{module_path}.{class_name}" if class_name else module_path,
        "class_name": class_name,
        "saved": True,
    }


@router.delete("/strategies/{filename}")
async def delete_strategy(filename: str):
    path = _CUSTOM_DIR / f"{filename}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy not found")
    path.unlink()
    return {"deleted": filename}


@router.post("/generate")
async def generate_strategy(req: GenerateRequest):
    """Generate strategy code from natural language description via unified AI client."""
    from quantforge.api.ai_client import chat

    base_code = _TEMPLATES.get(req.template, _TEMPLATES["empty"])

    system = """你是一名专业量化交易工程师，专为 QuantForge 系统编写 Python 策略代码。
只输出纯 Python 代码，不要 markdown 代码块标记，不要任何解释文字。"""

    user_msg = f"""根据以下策略描述，生成一个完整可运行的 QuantForge 策略类：

"{req.description}"

要求：
- 继承 quantforge.strategy.base.Strategy
- 实现 on_init(ctx), on_bar(bar)，可选 on_stop()
- 用 ctx.get_bars_df(symbol) 获取历史 K 线（DataFrame，含 open/high/low/close/volume）
- 用 ctx.get_position(symbol) 和 ctx.get_account() 查询状态
- 用 await ctx.buy(symbol, volume, price, exchange=Exchange.SZSE) 买入
- 用 await ctx.sell(symbol, volume, price, exchange=Exchange.SZSE) 卖出
- __init__ 包含 symbol 和 exchange 参数
- 用 pandas 计算指标
- 代码简洁正确"""

    try:
        code = await chat(system, user_msg, max_tokens=2048, caller="strategy_editor")
        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return {"code": code, "source": "ai"}
    except Exception:
        pass

    # Fallback: insert description as comment into base template
    commented = f'# 策略说明: {req.description}\n# 请根据上述描述在下方实现策略逻辑\n\n{base_code}'
    return {"code": commented, "source": "template"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_class_name(code: str) -> str | None:
    """Extract the first Strategy subclass name from source code."""
    import ast
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = getattr(base, "id", "") or getattr(base, "attr", "")
                    if "Strategy" in name or "strategy" in name.lower():
                        return node.name
        # If no Strategy base found, return first class
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                return node.name
    except SyntaxError:
        pass
    return None
