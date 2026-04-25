"""Strategy discovery and info endpoints."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/strategy", tags=["strategy"])

_BUILTIN_STRATEGIES: dict[str, dict] = {
    "dual_ma": {
        "id": "S001",
        "path": "strategies.examples.dual_ma_strategy.DualMAStrategy",
        "display_name": "双均线策略",
        "category": "trend_following",
        "tags": ["趋势跟随", "均线", "经典", "入门"],
        "logic": "快均线上穿慢均线买入（金叉），下穿卖出（死叉）",
        "suitable": "单边上涨趋势行情",
        "risk": "低",
        "params_desc": {"fast_period": "快均线周期（默认10日）", "slow_period": "慢均线周期（默认30日）"},
    },
    "rsi_mean_revert": {
        "id": "S002",
        "path": "strategies.examples.rsi_mean_revert.RSIMeanRevertStrategy",
        "display_name": "RSI均值回归",
        "category": "mean_reversion",
        "tags": ["均值回归", "RSI", "振荡", "止损"],
        "logic": "RSI < 30 超跌买入，RSI > 70 超涨卖出，内置5%止损",
        "suitable": "震荡横盘行情",
        "risk": "中低",
        "params_desc": {"rsi_period": "RSI计算周期（默认14）", "oversold": "超卖阈值（默认30）", "overbought": "超买阈值（默认70）"},
    },
    "bollinger_breakout": {
        "id": "S003",
        "path": "strategies.examples.bollinger_breakout.BollingerBreakoutStrategy",
        "display_name": "布林带突破",
        "category": "trend_following",
        "tags": ["趋势跟随", "布林带", "突破", "止损"],
        "logic": "价格突破布林带上轨买入，回落中轨卖出，内置7%止损",
        "suitable": "强趋势行情，板块轮动期",
        "risk": "中",
        "params_desc": {"period": "布林带周期（默认20）", "std_dev": "标准差倍数（默认2）"},
    },
    "macd": {
        "id": "S004",
        "path": "strategies.examples.macd_strategy.MACDStrategy",
        "display_name": "MACD趋势跟随",
        "category": "trend_following",
        "tags": ["趋势跟随", "MACD", "动量", "经典"],
        "logic": "MACD线上穿信号线做多，下穿平仓，默认参数(12,26,9)",
        "suitable": "中期趋势行情，避免高频震荡",
        "risk": "中",
        "params_desc": {"fast": "快线周期（默认12）", "slow": "慢线周期（默认26）", "signal": "信号线周期（默认9）"},
    },
    "turtle_breakout": {
        "id": "S005",
        "path": "strategies.examples.turtle_breakout.TurtleBreakoutStrategy",
        "display_name": "海龟突破系统",
        "category": "trend_following",
        "tags": ["海龟", "突破", "趋势跟随", "ATR", "止损", "经典"],
        "logic": "N日最高价突破买入，M日最低价破位止损，ATR动态调整仓位",
        "suitable": "强趋势行情，品种流动性好",
        "risk": "中",
        "params_desc": {"entry_period": "突破周期N（默认20日）", "exit_period": "退出周期M（默认10日）", "atr_multiplier": "ATR止损倍数（默认2.0）"},
    },
    "keltner_channel": {
        "id": "S006",
        "path": "strategies.examples.keltner_channel.KeltnerChannelStrategy",
        "display_name": "肯特纳通道策略",
        "category": "mean_reversion",
        "tags": ["肯特纳", "通道", "ATR", "EMA", "均值回归"],
        "logic": "价格触及EMA±ATR×倍数下轨买入，回归EMA中轨时卖出，支持长期趋势过滤",
        "suitable": "震荡偏多行情，避免熊市使用",
        "risk": "中低",
        "params_desc": {"ema_period": "EMA周期（默认20）", "atr_period": "ATR周期（默认14）", "multiplier": "通道宽度倍数（默认2.0）", "trend_filter": "启用200日趋势过滤"},
    },
    "volume_price_breakout": {
        "id": "S007",
        "path": "strategies.examples.volume_price_breakout.VolumePriceBreakoutStrategy",
        "display_name": "量价共振突破",
        "category": "trend_following",
        "tags": ["量价", "突破", "共振", "放量", "趋势跟随"],
        "logic": "价格突破N日高点且成交量超过均量vol_mult倍，双重确认才入场",
        "suitable": "放量突破的主升浪，筛选真实启动信号",
        "risk": "中",
        "params_desc": {"lookback": "回溯周期（默认20）", "vol_multiplier": "放量倍数（默认1.5×）", "stop_loss": "硬止损比例（默认7%）"},
    },
    "chandelier_exit": {
        "id": "S008",
        "path": "strategies.examples.chandelier_exit.ChandelierExitStrategy",
        "display_name": "吊灯止损趋势跟踪",
        "category": "trend_following",
        "tags": ["吊灯止损", "追踪止损", "ATR", "EMA", "让利润奔跑"],
        "logic": "EMA确认趋势后入场，止损线 = 最高价 - N×ATR，随行情上移只升不降",
        "suitable": "中长期趋势行情，持有期长",
        "risk": "中",
        "params_desc": {"ema_period": "入场EMA周期（默认21）", "atr_period": "ATR周期（默认22）", "multiplier": "止损ATR倍数（默认3.0）"},
    },
    "grid_trading": {
        "id": "S009",
        "path": "strategies.examples.grid_trading.GridTradingStrategy",
        "display_name": "网格交易策略",
        "category": "mean_reversion",
        "tags": ["网格", "震荡", "均值回归", "自动", "套利"],
        "logic": "以中心价为基准划分等间距网格，触及下格买入，上格卖出，持续积累差价",
        "suitable": "横盘震荡、波动率稳定的个股，不适合单边趋势",
        "risk": "低（需防趋势性下跌出网格）",
        "params_desc": {"grid_spacing": "网格间距（默认2%）", "grid_levels": "网格层数（默认上下各5层）", "lot_size": "每格交易手数（默认100股）"},
    },
    "adaptive_momentum": {
        "id": "S010",
        "path": "strategies.examples.adaptive_momentum.AdaptiveMomentumStrategy",
        "display_name": "自适应动量策略",
        "category": "adaptive",
        "tags": ["自适应", "状态切换", "AI", "多信号"],
        "logic": "实时检测波动率判断趋势/震荡状态，低波动用均线趋势，高波动切换RSI回归",
        "suitable": "全天候，自动适应不同行情",
        "risk": "中",
        "params_desc": {"vol_threshold": "波动率切换阈值（默认30%年化）", "vol_window": "波动率计算窗口（默认20）"},
    },
    "ensemble_voting": {
        "id": "S011",
        "path": "strategies.examples.ensemble_voting.EnsembleVotingStrategy",
        "display_name": "集成投票策略",
        "category": "ml",
        "tags": ["集成学习", "多信号", "AI", "投票", "降噪"],
        "logic": "均线+MACD+RSI三信号投票，≥2个看涨才开仓，减少假信号",
        "suitable": "震荡与趋势均适用，信号更稳定",
        "risk": "中",
        "params_desc": {"min_votes": "最少赞成票数（默认2/3）"},
    },
    "ml_alpha": {
        "id": "S012",
        "path": "strategies.examples.ml_alpha_strategy.MLAlphaStrategy",
        "display_name": "ML Alpha策略",
        "category": "ml",
        "tags": ["机器学习", "LightGBM", "因子", "Alpha"],
        "logic": "LightGBM模型基于10个技术特征预测涨跌方向，高分做多低分平仓",
        "suitable": "数据充足的主流个股，自动学习历史规律",
        "risk": "中高",
        "params_desc": {"train_window": "训练窗口（默认120）", "threshold": "预测阈值（默认0.55）"},
    },
    "factor_based": {
        "id": "S013",
        "path": "quantforge.strategy.template.factor_based.FactorBasedStrategy",
        "display_name": "因子驱动模板",
        "category": "ml",
        "tags": ["因子驱动", "ML模板", "可扩展"],
        "logic": "通用ML因子策略框架，自定义因子和模型，信号百分位过滤",
        "suitable": "研究开发，作为自定义因子策略的基础框架",
        "risk": "中高",
        "params_desc": {},
    },
}

_CATEGORY_META = {
    "trend_following": {"label": "趋势跟随", "color": "#3b82f6", "icon": "trending-up"},
    "mean_reversion":  {"label": "均值回归", "color": "#22c55e", "icon": "repeat"},
    "adaptive":        {"label": "自适应",   "color": "#a855f7", "icon": "cpu"},
    "ml":              {"label": "机器学习", "color": "#f59e0b", "icon": "brain"},
    "arbitrage":       {"label": "套利",     "color": "#ef4444", "icon": "zap"},
}


def _load_cls(path: str):
    project_root = Path(".")
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    parts = path.rsplit(".", 1)
    module = importlib.import_module(parts[0])
    return getattr(module, parts[1])


@router.get("/")
async def list_strategies():
    from quantforge.strategy.yaml_registry import registry

    result = []

    # 1. Built-in code strategies
    for name, meta in _BUILTIN_STRATEGIES.items():
        path = meta["path"]
        try:
            cls = _load_cls(path)
            cat = meta.get("category", "")
            # Check if any YAML strategy links to this class
            yaml_links = [
                m["name"] for m in registry.list_metadata()
                if m.get("execution_class") == name
            ]
            result.append({
                "id":             meta.get("id", ""),
                "name":           name,
                "source":         "builtin",
                "display_name":   meta.get("display_name", cls.__name__),
                "class_name":     cls.__name__,
                "module_path":    path,
                "description":    getattr(cls, "description", ""),
                "parameters":     getattr(cls, "parameters", []),
                "params_desc":    meta.get("params_desc", {}),
                "category":       cat,
                "category_label": _CATEGORY_META.get(cat, {}).get("label", cat),
                "category_color": _CATEGORY_META.get(cat, {}).get("color", "#718096"),
                "category_icon":  _CATEGORY_META.get(cat, {}).get("icon", "chart"),
                "tags":           meta.get("tags", []),
                "logic":          meta.get("logic", ""),
                "suitable":       meta.get("suitable", ""),
                "risk":           meta.get("risk", ""),
                # Capability flags
                "has_backtest":   True,
                "has_screener":   False,
                "has_yaml_signal": False,
                "yaml_links":     yaml_links,  # YAML strategies that use this class
            })
        except Exception as e:
            result.append({
                "name": name, "module_path": path, "error": str(e),
                "category": "error", "display_name": meta.get("display_name", name),
                "source": "builtin",
            })

    # 2. YAML strategies — unified view showing all 3 capabilities
    for m in registry.list_metadata():
        result.append({
            "id":             f"YAML_{m['name'].upper()[:6]}",
            "name":           f"yaml_{m['name']}",
            "source":         "yaml",
            "display_name":   m["display_name"],
            "class_name":     "",
            "module_path":    m.get("execution_path", ""),
            "description":    m["description"],
            "parameters":     list(m.get("execution_params", {}).keys()),
            "params_desc":    {k: str(v) for k, v in m.get("execution_params", {}).items()},
            "category":       m.get("category", ""),
            "category_label": "YAML自定义",
            "category_color": m.get("category_color", "#6366f1"),
            "category_icon":  m.get("icon", "file-text"),
            "tags":           ["YAML", "自然语言", "统一策略"],
            "logic":          m["description"][:120],
            "suitable":       m.get("suitable", ""),
            "risk":           m.get("risk", ""),
            # Capability flags — key info for UI
            "has_screener":    m["has_screener"],
            "has_yaml_signal": True,
            "has_backtest":    m["has_execution"],
            "execution_class": m.get("execution_class", ""),
            "execution_display": m.get("execution_display", ""),
            "execution_params":  m.get("execution_params", {}),
            "yaml_name":       m["name"],
        })

    return result


@router.get("/{name}")
async def get_strategy(name: str):
    meta = _BUILTIN_STRATEGIES.get(name)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    try:
        cls = _load_cls(meta["path"])
        cat = meta.get("category", "")
        return {
            "id": meta.get("id", ""),
            "name": name,
            "display_name": meta.get("display_name", cls.__name__),
            "class_name": cls.__name__,
            "module_path": meta["path"],
            "description": getattr(cls, "description", ""),
            "author": getattr(cls, "author", ""),
            "parameters": getattr(cls, "parameters", []),
            "params_desc": meta.get("params_desc", {}),
            "category": cat,
            "category_label": _CATEGORY_META.get(cat, {}).get("label", cat),
            "category_color": _CATEGORY_META.get(cat, {}).get("color", "#718096"),
            "tags": meta.get("tags", []),
            "logic": meta.get("logic", ""),
            "suitable": meta.get("suitable", ""),
            "risk": meta.get("risk", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
