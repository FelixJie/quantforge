# -*- coding: utf-8 -*-
"""调研纪要推荐机构胜率计算（脚本 + API 共用核心）。

从 blog_posts（知识星球调研纪要）解析【机构】标签与被推荐个股，用本地
stock_kline 算发帖后 N 个交易日的收益，给出：
  - 绝对胜率（收益 > 0 占比）
  - 相对胜率（跑赢沪深300同期占比）+ 平均超额
按机构聚合排名。纯离线读 data/cache.db，不联网。

设计要点：
  * 标签清洗（``normalize_institution``）：要求带券商前缀才算「机构」，
    剔除纯主题词（如「光模块/AI服务器」「储能」）；归并分析师姓名/英文简称
    （tf→天风、zx/ZX→中信、建投→中信建投…），把「中泰医药谢木青、刘照芊」
    这类压成「中泰医药」。
  * 相对基准 = 沪深300（kline code ``SH000300``），按发帖日同期对齐计算。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

try:
    from quantforge.data.storage.db_cache import _DB_PATH as DB_PATH  # type: ignore
except Exception:  # pragma: no cover - 脚本独立运行兜底
    DB_PATH = Path("data/cache.db")

NAMES_FILE = Path("data/cache/stock_names.json")
GROUP_ID = "28855458518111"          # 调研纪要星球
BENCH_CODE = "SH000300"              # 沪深300
HORIZONS = [1, 3, 5, 30]            # 昨日/3日/5日/30日（交易日）

# 行业关键词：用于在券商后定位「行业」段，归一标签
INDUSTRY_KW = [
    "通信", "计算机", "电新", "电子", "金属", "有色", "钢铁", "煤炭", "石化", "化工",
    "建材", "建筑", "机械", "军工", "汽车", "家电", "食饮", "食品", "饮料", "纺服",
    "轻工", "商社", "消费", "零售", "医药", "生物", "银行", "非银", "地产", "环保",
    "公用", "交运", "传媒", "互联网", "农业", "策略", "新材料", "黄金", "新能源",
    "半导体", "电力", "船舶", "海工", "光伏", "储能", "金工", "宏观", "中小盘", "船舶",
]
# 券商简称（标签须以其一开头才算机构）；长名在前，匹配优先
BROKERS = sorted([
    "中信建投", "国泰海通", "申万宏源", "广发", "东吴", "天风", "申万", "中泰",
    "信达", "国金", "中信", "海通", "华泰", "招商", "国泰", "东北", "民生", "兴业",
    "光大", "方正", "西部", "国信", "安信", "浙商", "华西", "开源", "财通", "长江",
    "中金", "平安", "银河", "东兴", "华创", "太平洋", "国元", "中银", "德邦", "山西",
    "华安", "国海", "国盛", "西南", "东方", "粤开", "红塔", "华福", "甬兴", "长城",
    "国联民生", "兴证", "建投",
], key=len, reverse=True)
# 英文/别名前缀 → 券商
ALIASES = {
    "tf": "天风", "zx": "中信", "建投": "中信建投", "兴证": "兴业",
    "国君": "国泰海通", "申万宏源": "申万",
}
# 归一展示时把这些券商别名映射到规范名
BROKER_CANON = {"申万宏源": "申万", "建投": "中信建投", "兴证": "兴业", "国君": "国泰海通"}

CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
BRACKET_RE = re.compile(r"【([^】]{1,24})】")
_SEP_RE = re.compile(r"[|·/、&\-—:：　 _]")


def load_names() -> tuple[dict, dict]:
    """返回 ({code:name}, {name:code})，仅收 name 长度≥3 的进 name2code。"""
    raw = json.loads(NAMES_FILE.read_text(encoding="utf-8")).get("stocks", {})
    code2name, name2code = {}, {}
    for k, v in raw.items():
        nm = (v or {}).get("name", "") if isinstance(v, dict) else ""
        if k.isdigit() and len(k) == 6:
            code, name = k, nm
        elif nm.isdigit() and len(nm) == 6:
            code, name = nm, k
        else:
            continue
        if name and not name.isdigit():
            code2name[code] = name
            if len(name) >= 3:
                name2code[name] = code
    return code2name, name2code


def normalize_institution(tag: str) -> str | None:
    """把原始【标签】归一为「券商+行业」机构名；非机构(纯主题/无券商)返回 None。"""
    if not tag:
        return None
    tag = tag.strip()
    if not tag or CODE_RE.search(tag):  # 带 6 位代码的多为个股标签
        return None
    # 英文/别名前缀展开
    low = tag.lower()
    for k, v in ALIASES.items():
        if low.startswith(k.lower()):
            tag = v + tag[len(k):]
            break
    # 必须以券商开头
    broker = next((b for b in BROKERS if tag.startswith(b)), None)
    if not broker:
        return None
    rest = tag[len(broker):]
    broker = BROKER_CANON.get(broker, broker)
    # 行业段：取 rest 里首个行业关键词；没有则取分隔符前的片段
    ind = next((kw for kw in INDUSTRY_KW if kw in rest), None)
    if ind:
        return broker + ind
    head = _SEP_RE.split(rest, 1)[0].replace("团队", "").strip()
    head = re.sub(r"\d+", "", head)
    return (broker + head) if head else broker


def extract_stocks(title: str, content: str, name2code: dict, raw_tag: str | None) -> list[str]:
    """识别被推荐个股代码（6 位代码 + 完整股名，长名优先），保序去重。"""
    text = (title or "") + "\n" + (content or "")
    if raw_tag:
        text = text.replace("【" + raw_tag + "】", " ")
    codes: list[str] = []
    for m in CODE_RE.findall(text):
        if m not in codes:
            codes.append(m)
    hits = sorted(((len(nm), c) for nm, c in name2code.items() if nm in text), reverse=True)
    for _, c in hits:
        if c not in codes:
            codes.append(c)
    return codes


def _load_series(conn: sqlite3.Connection, codes: set[str]) -> dict[str, list[tuple[str, float]]]:
    """{code: [(date, close)...]} 升序。一次性批量取，避免逐只查询。"""
    series: dict[str, list[tuple[str, float]]] = defaultdict(list)
    if not codes:
        return series
    codes = {c for c in codes}
    qmarks = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT code, date, close FROM stock_kline "
        f"WHERE period='day' AND close IS NOT NULL AND code IN ({qmarks}) "
        f"ORDER BY code, date",
        tuple(codes),
    ).fetchall()
    for code, date, close in rows:
        series[code].append((date[:10], close))
    return series


def _bench_by_date(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute(
        "SELECT date, close FROM stock_kline WHERE period='day' AND code=? AND close IS NOT NULL",
        (BENCH_CODE,),
    ).fetchall()
    return {d[:10]: c for d, c in rows}


def compute(lookback_days: int = 120, min_samples: int = 3,
            group_id: str = GROUP_ID) -> dict:
    """主入口。返回 meta + institutions(含各 horizon 统计) + rankings。"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        code2name, name2code = load_names()
        bench = _bench_by_date(conn)
        kline_latest = conn.execute(
            "SELECT MAX(date) FROM stock_kline WHERE period='day'"
        ).fetchone()[0]

        cutoff = ""
        if lookback_days and lookback_days > 0:
            import datetime as _dt
            cutoff = (_dt.date.today() - _dt.timedelta(days=lookback_days)).isoformat()

        posts = conn.execute(
            "SELECT title, content_text, created_at FROM blog_posts "
            "WHERE group_id=? AND substr(created_at,1,10) >= ? ORDER BY created_at",
            (group_id, cutoff),
        ).fetchall()

        # 先把所有需要的 code 收齐，批量取 kline
        parsed = []   # (inst, post_date, [codes])
        all_codes: set[str] = set()
        n_posts = n_inst = n_stock = 0
        for title, content, created in posts:
            n_posts += 1
            raw_tag = None
            for t in BRACKET_RE.findall((title or "") + "\n" + (content or "")[:120]):
                if normalize_institution(t):
                    raw_tag = t
                    break
            inst = normalize_institution(raw_tag) if raw_tag else None
            if not inst:
                continue
            n_inst += 1
            codes = extract_stocks(title, content, name2code, raw_tag)
            if not codes:
                continue
            n_stock += 1
            parsed.append((inst, (created or "")[:10], codes))
            all_codes.update(c.zfill(6) for c in codes)
            all_codes.update(codes)

        series = _load_series(conn, all_codes)

        # 机构 → horizon → {"abs":[bool], "rel":[bool], "ret":[f], "exc":[f]}
        agg: dict = defaultdict(lambda: {n: {"abs": [], "rel": [], "ret": [], "exc": []}
                                         for n in HORIZONS})
        for inst, post_date, codes in parsed:
            for code in codes:
                bars = series.get(code.zfill(6)) or series.get(code)
                if not bars:
                    continue
                t0 = next((i for i, (d, _) in enumerate(bars) if d >= post_date), None)
                if t0 is None or not bars[t0][1]:
                    continue
                d0, base = bars[t0][0], bars[t0][1]
                b0 = bench.get(d0)
                for n in HORIZONS:
                    j = t0 + n
                    if j >= len(bars) or not bars[j][1]:
                        continue
                    ret = bars[j][1] / base - 1.0
                    bucket = agg[inst][n]
                    bucket["abs"].append(ret > 0)
                    bucket["ret"].append(ret)
                    dN = bars[j][0]
                    bN = bench.get(dN)
                    if b0 and bN:
                        exc = ret - (bN / b0 - 1.0)
                        bucket["rel"].append(exc > 0)
                        bucket["exc"].append(exc)

        def _stat(b: dict) -> dict | None:
            n = len(b["abs"])
            if not n:
                return None
            r = b["rel"]
            return {
                "n": n,
                "win_abs": round(sum(b["abs"]) / n, 4),
                "avg_ret": round(sum(b["ret"]) / n, 4),
                "n_rel": len(r),
                "win_rel": round(sum(r) / len(r), 4) if r else None,
                "avg_exc": round(sum(b["exc"]) / len(b["exc"]), 4) if b["exc"] else None,
            }

        institutions = []
        for inst, hz in agg.items():
            row = {"name": inst, "horizons": {}}
            for n in HORIZONS:
                s = _stat(hz[n])
                if s:
                    row["horizons"][str(n)] = s
            if row["horizons"]:
                institutions.append(row)

        # 排名：每 horizon 按相对胜率(主)→绝对胜率→样本 降序，样本≥min_samples
        rankings: dict = {}
        for n in HORIZONS:
            key = str(n)
            cand = [r for r in institutions
                    if key in r["horizons"] and r["horizons"][key]["n"] >= min_samples]
            cand.sort(key=lambda r: (
                r["horizons"][key]["win_rel"] if r["horizons"][key]["win_rel"] is not None else -1,
                r["horizons"][key]["win_abs"],
                r["horizons"][key]["n"],
            ), reverse=True)
            rankings[key] = [r["name"] for r in cand]

        # institutions 默认按总样本量降序，便于表格展示
        institutions.sort(
            key=lambda r: sum(h["n"] for h in r["horizons"].values()), reverse=True)

        data_start = posts[0][2][:10] if posts else None
        data_end = posts[-1][2][:10] if posts else None
        note = None
        if kline_latest and data_end:
            # 粗判 30 日窗口是否够（约 6 周交易日）
            note = "30日窗口需发帖后约30个交易日数据，近期帖子样本可能不足"

        return {
            "meta": {
                "group_id": group_id,
                "posts_total": n_posts,
                "posts_with_inst": n_inst,
                "posts_with_stock": n_stock,
                "inst_count": len(institutions),
                "post_start": data_start,
                "post_end": data_end,
                "kline_latest": kline_latest,
                "horizons": HORIZONS,
                "min_samples": min_samples,
                "lookback_days": lookback_days,
                "benchmark": "沪深300",
                "note": note,
            },
            "institutions": institutions,
            "rankings": rankings,
        }
    finally:
        conn.close()
