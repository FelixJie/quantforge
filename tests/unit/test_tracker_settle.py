"""结算引擎 settle() 的单元测试（价位/固定窗口分支，纯计算，不联网/不读库）。

只覆盖非动能（pick_strategy != "momentum"）分支：逐根先判止损、再判止盈，
未触发按固定窗口末收盘结算。动能分支依赖 compute_momentum 的完整计算链，
此处不展开，由 test_momentum.py 单独验证其纯函数。
"""

import pytest

from quantforge.prediction.tracker import settle


def _bar(date, o, h, l, c, v=1000):
    return {"date": date, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _levels_pred(target, stop, date="20240101"):
    # pick_strategy 非 momentum，走 _settle_levels_core（止盈/止损/固定窗口）
    return {"date": date, "pick_strategy": "pring", "target_price": target, "stop_price": stop}


def test_hit_target_first():
    # 验证：先冲到止盈价 → outcome=hit_target，收益按 (target-entry)/entry 锁定
    pred = _levels_pred(target=11.0, stop=9.0)
    bars = [
        _bar("20240101", 10.0, 10.2, 9.9, 10.1),   # 入场（open=10）
        _bar("20240102", 10.1, 11.5, 10.0, 11.2),  # 当日最高 11.5 ≥ 11.0 触发止盈
        _bar("20240103", 11.2, 12.0, 11.0, 11.8),
    ]
    r = settle(pred, bars, window=20)
    assert r is not None
    assert r["entry_price"] == 10.0
    assert r["outcome"] == "hit_target"
    assert r["settled"] is True
    # 锁定收益 = (11.0 - 10.0) / 10.0 * 100 = 10.0%
    assert r["final_return"] == pytest.approx(10.0)
    assert r["actual_close"] == pytest.approx(11.0)
    assert r["trigger_date"] == "20240102"
    assert r["hold_days"] == 2  # 入场日 + 触发日


def test_hit_stop_first():
    # 验证：先跌破止损价 → outcome=hit_stop，收益为负且按止损价锁定
    pred = _levels_pred(target=12.0, stop=9.0)
    bars = [
        _bar("20240101", 10.0, 10.2, 9.9, 10.1),
        _bar("20240102", 9.8, 9.9, 8.5, 9.0),   # 当日最低 8.5 ≤ 9.0 触发止损
        _bar("20240103", 9.0, 9.5, 8.0, 9.2),
    ]
    r = settle(pred, bars, window=20)
    assert r["outcome"] == "hit_stop"
    assert r["settled"] is True
    # 锁定收益 = (9.0 - 10.0) / 10.0 * 100 = -10.0%
    assert r["final_return"] == pytest.approx(-10.0)
    assert r["actual_close"] == pytest.approx(9.0)
    assert r["trigger_date"] == "20240102"


def test_stop_checked_before_target_same_bar():
    # 验证：同一根 K 线既触止损又触止盈时，引擎先判止损（保守口径）
    pred = _levels_pred(target=11.0, stop=9.0)
    bars = [
        _bar("20240101", 10.0, 10.2, 9.9, 10.1),
        _bar("20240102", 10.0, 11.5, 8.5, 10.0),  # high≥target 且 low≤stop，应判止损
        _bar("20240103", 10.0, 10.5, 9.8, 10.2),
    ]
    r = settle(pred, bars, window=20)
    assert r["outcome"] == "hit_stop"
    assert r["final_return"] == pytest.approx(-10.0)


def test_window_expiry_no_trigger_positive():
    # 验证：整个固定窗口都没触发止盈/止损 → 按窗口末收盘结算，收益为正
    pred = _levels_pred(target=20.0, stop=1.0)  # 极宽，不会触发
    bars = [
        _bar("20240101", 10.0, 10.2, 9.9, 10.1),  # 入场 open=10
        _bar("20240102", 10.1, 10.4, 10.0, 10.3),
        _bar("20240103", 10.3, 10.8, 10.2, 10.6),  # 窗口末收盘 10.6
    ]
    r = settle(pred, bars, window=3)
    assert r["settled"] is True
    assert r["outcome"] == "positive"
    assert r["trigger_date"] is None
    # (10.6 - 10.0) / 10.0 * 100 = 6.0%
    assert r["final_return"] == pytest.approx(6.0)
    assert r["hold_days"] == 3


def test_window_expiry_no_trigger_negative():
    # 验证：窗口内无触发且窗口末收盘低于入场 → outcome=negative
    pred = _levels_pred(target=20.0, stop=1.0)
    bars = [
        _bar("20240101", 10.0, 10.1, 9.9, 10.0),
        _bar("20240102", 10.0, 10.0, 9.6, 9.7),
        _bar("20240103", 9.7, 9.8, 9.3, 9.4),  # 末收盘 9.4
    ]
    r = settle(pred, bars, window=3)
    assert r["outcome"] == "negative"
    # (9.4 - 10.0) / 10.0 * 100 = -6.0%
    assert r["final_return"] == pytest.approx(-6.0)


def test_not_settled_when_window_incomplete():
    # 验证：未触发且 K 线根数不足一个完整窗口 → settled=False, outcome=open
    pred = _levels_pred(target=20.0, stop=1.0)
    bars = [
        _bar("20240101", 10.0, 10.2, 9.9, 10.1),
        _bar("20240102", 10.1, 10.4, 10.0, 10.3),
    ]
    r = settle(pred, bars, window=20)  # 只有 2 根 < window
    assert r["settled"] is False
    assert r["outcome"] == "open"


def test_returns_none_before_entry_date():
    # 验证：所有 K 线都早于推荐日（市场尚未在推荐日之后开盘）→ 返回 None
    pred = _levels_pred(target=11.0, stop=9.0, date="20240601")
    bars = [
        _bar("20240101", 10.0, 10.2, 9.9, 10.1),
        _bar("20240102", 10.1, 10.4, 10.0, 10.3),
    ]
    assert settle(pred, bars, window=20) is None


def test_entry_uses_first_bar_on_or_after_pred_date():
    # 验证：入场取「≥推荐日」的首根 K 线 open，早于推荐日的 K 线被忽略
    pred = _levels_pred(target=20.0, stop=1.0, date="20240103")
    bars = [
        _bar("20240101", 5.0, 5.1, 4.9, 5.0),    # 早于推荐日，忽略
        _bar("20240102", 6.0, 6.1, 5.9, 6.0),    # 早于推荐日，忽略
        _bar("20240103", 10.0, 10.2, 9.9, 10.1),  # 入场，open=10
        _bar("20240104", 10.1, 10.3, 10.0, 10.2),
        _bar("20240105", 10.2, 10.5, 10.1, 10.4),
    ]
    r = settle(pred, bars, window=3)
    assert r["entry_date"] == "20240103"
    assert r["entry_price"] == 10.0


def test_horizon_and_window_metrics():
    # 验证：反事实窗口指标（window_return / mfe / mae / horizon_returns）按纯买入持有计算
    pred = _levels_pred(target=100.0, stop=1.0)  # 不触发，纯持有
    bars = [
        _bar("20240101", 10.0, 11.0, 9.5, 10.5),  # 入场 open=10, 当日 high=11 low=9.5
        _bar("20240102", 10.5, 12.0, 9.0, 11.0),  # 区间最高 12，最低 9.0
        _bar("20240103", 11.0, 11.5, 10.5, 11.2),
    ]
    r = settle(pred, bars, window=3)
    # mfe = (12.0 - 10.0)/10*100 = 20.0；mae = (9.0 - 10.0)/10*100 = -10.0
    assert r["mfe_pct"] == pytest.approx(20.0)
    assert r["mae_pct"] == pytest.approx(-10.0)
    # window_return = 窗口末收盘 11.2 相对 10 = 12.0%
    assert r["window_return"] == pytest.approx(12.0)
    # horizon h=1 → 入场当日 open→close = (10.5-10)/10*100 = 5.0%
    assert r["horizon_returns"]["1"] == pytest.approx(5.0)
    # h=3 → 第3根收盘 11.2 = 12.0%
    assert r["horizon_returns"]["3"] == pytest.approx(12.0)
    # h=30 越界 → None
    assert r["horizon_returns"]["30"] is None
