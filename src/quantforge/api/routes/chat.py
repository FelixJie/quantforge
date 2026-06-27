"""纯 AI 聊股对话 —— 多轮、流式(SSE)，自动注入「数据库」分析上下文。

前端发送完整对话历史；当用户消息里出现 6 位股票代码 / 完整股名 / 板块名时，
直接从本地 SQLite(data/cache.db)拉取多维数据拼进 system prompt，让 AI 基于
真实数据分析、避免幻觉。**全部读库、零网络依赖**(库由后台刷新器持续灌新)：

  - 实时行情：现价/涨跌/PE/PB/换手/区间        (stock_quote)
  - 技术面：MA5/MA20、近 N 日涨跌、年内高低位置、多空排列  (stock_kline 现算)
  - 机构一致预期：目标价(均值/高/低)、评级分布、EPS/PE 预测  (stock_reports)
  - 板块行情：涨跌/领涨/成交额 + 板块内领涨领跌成分股        (sector_*)
  - 个性化：登录用户问「我的自选」时带其自选股行情概览        (watchlist)

Endpoints:
  POST /api/chat/stream  → SSE 流式回复 (data: {"delta": "..."} / {"done": true})
"""

from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from quantforge.api.routes.auth import get_optional_user

router = APIRouter(prefix="/chat", tags=["chat"])

# 单条消息里抓 6 位 A 股代码（前后非数字，避免误抓长数字串里的片段）
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

_SYSTEM_PROMPT = """你是一位资深的 A 股投资助手，擅长技术面、基本面、机构预期与市场情绪综合分析。

下方可能附带「实时行情 / 技术面 / 最近日K原始数据 / 资金面(主力净流入) /
真实财务报表 / 机构一致预期 / 板块行情 / 机构行业研报观点与正文 / 用户自选 /
实时资讯(联网)」等数据块。注意区分：「真实财务报表」是已披露的历史财报，「机构
一致预期」是机构对未来的预测；除标「联网」的实时资讯外其余多取自本地或现拉数据。
请**优先基于这些数据**作答，把它们
串成有逻辑的判断(例如：现价对比机构目标价 → 估值高低；MA 排列 + 近期涨跌 → 趋势强弱；
板块联动 → 情绪；行业研报观点 → 提炼机构共识与分歧)，不要只复述数字或照抄研报原文。涉及价格、估值、目标价、EPS 等具体数字时只能引用数据块里的值，
**严禁编造**。数据块未提供的维度，直接说明「暂无数据」，不要硬编。

这是**多轮对话**，请结合上文连贯作答：用户用「它/这只/该股/前面那只」等指代时，默认指
上文最近讨论的标的；用户说「对比/相比」时，把上文标的与本轮提到的放在一起比较。

回答专业、简洁、口语化。**先给结论(一句话判断)，再列支撑依据**，多用要点、避免长篇
铺陈与重复。你不能保证收益，给操作建议时务必提示风险、给出止损/仓位思路，并提醒这只是
基于数据的分析、非投资建议。"""


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    use_quotes: bool = True   # 是否自动带实时行情/技术面/研报等本地库上下文
    use_web: bool = False     # 是否联网补充实时资讯（个股新闻/公告，实时抓取）
    deep: bool = False        # 深度分析模式：更强的多步推理 + 更大输出预算
    session_id: str = ""      # 前端会话 id（用于对话存档）
    title: str = ""           # 会话标题（冗余存档，列表展示用）


# 深度分析模式追加到 system 末尾：要求多步拆解、结构化、并量化结论。
_DEEP_SUFFIX = """

【深度分析模式】本轮请做更系统的分析，按以下结构展开（用 Markdown 小标题）：
1) **核心结论**：一句话给出方向(看多/看空/观望)与置信度；
2) **基本面**：财报成长性/盈利质量/估值(现价 vs 机构目标价与历史)；
3) **技术面与资金面**：趋势/位置 + 主力资金态度；
4) **催化与风险**：研报/资讯里的利好利空，列分歧点；
5) **操作策略**：仓位、买点区间、止损位（给具体数字，标明依据），并提示这是基于数据的分析、非投资建议。
逐条用数据块里的真实数字支撑，缺失维度直说「暂无数据」。"""


# 股名映射构建一次约需遍历 ~5000 只，且一次对话请求里多路 builder 都要用，
# 故做进程级 TTL 缓存(股名几乎不变，10 分钟足够)，避免每路重复全量构建。
_NAMES_CACHE: dict[str, str] | None = None
_NAMES_CACHE_TS = 0.0
_NAMES_TTL = 600.0


def _all_names() -> dict[str, str]:
    """{code: name} 映射。优先用内存缓存(生产由 meta 预热器填充)，空则直接读盘
    (忽略 TTL —— 股名几乎不变，无需为识别触发网络刷新)。

    对存储方向做鲁棒处理：历史缓存文件曾把 名/码 写反(key=名、name字段=码)。
    这里按「哪个字段是 6 位数字」判定代码，两种方向都能正确解析。

    结果按进程级 TTL 缓存——同一对话请求里 6 路 builder 都调它，避免重复构建。
    """
    global _NAMES_CACHE, _NAMES_CACHE_TS
    now = time.monotonic()
    if _NAMES_CACHE is not None and (now - _NAMES_CACHE_TS) < _NAMES_TTL:
        return _NAMES_CACHE

    raw: dict = {}
    try:
        from quantforge.data.storage import stock_meta_cache
        raw = dict(stock_meta_cache._store)
        if not raw:
            f = stock_meta_cache._CACHE_FILE
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8")).get("stocks", {})
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chat: name map load failed: {e}")
        # 缓存空结果短时间，避免反复读盘失败；TTL 到期后再试
        _NAMES_CACHE = {}
        _NAMES_CACHE_TS = now
        return {}

    out: dict[str, str] = {}
    for k, v in raw.items():
        nm = (v or {}).get("name", "") if isinstance(v, dict) else ""
        if k.isdigit() and len(k) == 6:
            code, name = k, nm
        elif nm.isdigit() and len(nm) == 6:
            code, name = nm, k
        else:
            continue
        if name and not name.isdigit():
            out[code] = name
    _NAMES_CACHE = out
    _NAMES_CACHE_TS = now
    return out


def _resolve_name_codes(text: str) -> list[str]:
    """从文本里识别完整股名(如「宁德时代」「贵州茅台」)→ 代码，保序去重。

    只匹配作为子串完整出现的股名，且名称≥3字，避免短名误命中普通词。
    命中多个时长名优先（更具体）。
    """
    if not text:
        return []
    names = _all_names()
    if not names:
        return []

    hits: list[tuple[int, str]] = []   # (name_len, code)
    for code, name in names.items():
        if name and len(name) >= 3 and name in text:
            hits.append((len(name), code))
    hits.sort(reverse=True)   # 长名优先
    out: list[str] = []
    for _, code in hits:
        if code not in out:
            out.append(code)
    return out


# 高频俗称/简称 → 代码：启发式补不全的热门票手工兜底（库里不存在则启发式/全名兜底）。
_NICKNAMES = {
    "茅台": "600519", "五粮液": "000858", "宁王": "300750", "宁德": "300750",
    "比亚迪": "002594", "中免": "601888", "药明": "603259", "海天": "603288",
    "万华": "600309", "牧原": "002714", "隆基": "601012", "通威": "600438",
    "迈瑞": "300760", "立讯": "002475", "歌尔": "002241", "韦尔": "603501",
    "兆易": "603986", "北方华创": "002371", "中芯": "688981", "海光": "688041",
    "寒武纪": "688256", "金龙鱼": "300999", "片仔癀": "600436", "恒瑞": "600276",
    "爱尔": "300015", "东方财富": "300059", "东财": "300059", "中信证券": "600030",
}
# 明显是通用词、不该当简称的头/尾词（避免启发式把「股份/科技」「今天国际→今天」等
# 通用词当股名）。含两类：① 行业后缀类  ② 时间/行情高频词（防「今天大盘」误命中个股）
_ALIAS_STOP = {
    # ① 行业后缀/通用构词
    "股份", "科技", "集团", "控股", "实业", "发展", "电子", "电气", "能源",
    "传媒", "环保", "生物", "医药", "银行", "证券", "保险", "地产", "国际",
    "投资", "网络", "信息", "通信", "材料", "机械", "化学", "化工", "光电",
    # ② 时间/行情/操作高频词（这些当头/尾词会把「今天大盘/未来走势」误判成个股）
    "今天", "明天", "昨天", "后天", "现在", "未来", "最近", "目前", "当前",
    "大盘", "后市", "行情", "市场", "整体", "可能", "趋势", "机会", "题材",
    "概念", "龙头", "主力", "资金", "情绪", "风格", "板块", "布局", "操作",
    "策略", "仓位", "风险", "收益", "反弹", "回调", "走势", "持有",
}

_ALIAS_CACHE: dict[str, str] | None = None
_ALIAS_CACHE_TS = 0.0


def _alias_index() -> dict[str, str]:
    """{简称: 代码}。手工俗称 + 启发式(去前2字地域/限定前缀得尾词)，仅保留唯一解。

    与全名映射同款进程级 TTL 缓存。启发式只在尾词长度 2~3、且全市场唯一映射到
    一只股、且不是通用词时才收录——多义/通用词一律丢弃，避免认错股。
    """
    global _ALIAS_CACHE, _ALIAS_CACHE_TS
    now = time.monotonic()
    if _ALIAS_CACHE is not None and (now - _ALIAS_CACHE_TS) < _NAMES_TTL:
        return _ALIAS_CACHE

    names = _all_names()
    cand: dict[str, set[str]] = {}   # 简称 → 命中的代码集合（用于唯一性判定）
    for code, name in names.items():
        if not name or len(name) < 4:
            continue
        # ① 尾词(剥地域/限定前缀)：贵州茅台→茅台、宁德时代→时代
        tail = name[2:]
        if 2 <= len(tail) <= 3 and tail not in _ALIAS_STOP:
            cand.setdefault(tail, set()).add(code)
        # ② 头词(前两字)：国瓷材料→国瓷、立讯精密→立讯、迈瑞医疗→迈瑞。很多 A 股俗称
        #    取的是名字头部而非尾部，仅靠尾词会漏。多义/地域头词(如「上海」「东方」)会因
        #    映射到多只股被下面的唯一性判定剔除，故安全。
        head = name[:2]
        if head not in _ALIAS_STOP:
            cand.setdefault(head, set()).add(code)
    idx = {a: next(iter(cs)) for a, cs in cand.items() if len(cs) == 1}
    # 手工俗称优先级最高（仅当代码确实在库里时覆盖）
    for a, c in _NICKNAMES.items():
        if c in names:
            idx[a] = c
    _ALIAS_CACHE = idx
    _ALIAS_CACHE_TS = now
    return idx


def _resolve_alias_codes(text: str) -> list[str]:
    """从文本里识别简称(如「茅台」「宁王」)→ 代码，长简称优先，保序去重。"""
    if not text:
        return []
    idx = _alias_index()
    if not idx:
        return []
    hits: list[tuple[int, str]] = []
    for alias, code in idx.items():
        if alias in text:
            hits.append((len(alias), code))
    hits.sort(reverse=True)   # 长简称优先（更具体）
    out: list[str] = []
    for _, code in hits:
        if code not in out:
            out.append(code)
    return out


def _extract_codes(text: str) -> list[str]:
    """抓 6 位代码 + 识别完整股名 + 简称，合并去重，最多 5 只。"""
    seen: list[str] = []
    for m in _CODE_RE.findall(text or ""):
        if m not in seen:
            seen.append(m)
    for code in _resolve_name_codes(text or ""):
        if code not in seen:
            seen.append(code)
    for code in _resolve_alias_codes(text or ""):
        if code not in seen:
            seen.append(code)
    return seen[:5]


# 多轮指代继承：判断本轮是否在「延续上文标的」。只认两类强信号——① 指代/承接词
# （它/这只/该股/前面、对比/竞品/同行…）② 很短的追问（如「领涨的呢」「估值贵吗」）。
# 维度词（资金/估值…）单独出现在长句里不算（如「今天大盘你怎么看」不该拖着上一只票）。
_ANAPHORA_RE = re.compile(
    r"它|他|她|这|那|该|此|两者?|前面|上面|上述|前述|"
    r"继续|接着|然后|再说|还有|另外|"
    r"对比|相比|比一比|比较|竞品|同行|对手|龙头"
)
_FOLLOWUP_MAX_LEN = 15   # 不含实体且不超过这个长度的问题，视为对上文的短追问


def _has_entity(text: str) -> bool:
    """文本里是否带『可识别个股』（6 位代码 / 完整股名 / 简称）。

    只认个股，**不**把主题词算进来：主题词正则 `[一-龥]{2,6}` 几乎能从任何中文句
    切出词（连「那它的资金面」都算），若用它判断「本轮是否自带话题」，会让指代继承
    永远不触发。个股识别足够严格，是判断「换没换标的」的可靠依据。
    """
    return bool(_extract_codes(text))


def _resolve_context_text(messages: list[dict], last_user: str) -> str:
    """返回用于「实体识别」的文本：本轮消息，必要时并入上文锚点（多轮指代继承）。

    规则：本轮已带实体 → 直接用本轮（话题以最新为准，不被旧标的污染）；本轮没实体
    但是「短追问」或「含指代/承接词」→ 回溯最近一条带实体的历史用户消息并进来，让
    行情/技术/资金/研报/板块等数据块仍挂在上文讨论的标的上。其余（明确换了新话题的
    长问句）不继承，避免「今天大盘怎么看」还硬拖着上一只票。
    """
    if _has_entity(last_user):
        return last_user
    is_followup = len(last_user) <= _FOLLOWUP_MAX_LEN or bool(_ANAPHORA_RE.search(last_user))
    if not is_followup:
        return last_user
    for m in reversed(messages[:-1]):
        if m.get("role") == "user" and _has_entity(m.get("content", "")):
            return f"{last_user} {m['content']}".strip()
    return last_user


async def _build_quote_context(codes: list[str]) -> str:
    """对识别出的代码拉实时行情，拼成一段上下文文本。"""
    if not codes:
        return ""

    try:
        from quantforge.data.feed import datasource
        q = await asyncio.to_thread(datasource.quotes, [c.zfill(6) for c in codes])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chat: quote context fetch failed: {e}")
        return ""

    if not q:
        return ""

    lines = ["\n\n[实时行情参考 — 请基于以下真实价位分析，不要编造数字]"]
    for code in codes:
        v = (q or {}).get(code.zfill(6))
        if not v:
            continue
        name = v.get("name") or ""
        parts = [f"{code} {name}".strip()]
        if v.get("price") is not None:
            parts.append(f"现价{v.get('price')}")
        if v.get("change_pct") is not None:
            try:
                parts.append(f"涨跌{float(v['change_pct']):+.2f}%")
            except (TypeError, ValueError):
                pass
        if v.get("pe_ttm"):
            parts.append(f"PE(TTM)={v.get('pe_ttm')}")
        if v.get("pb"):
            parts.append(f"PB={v.get('pb')}")
        if v.get("turnover_pct") is not None:
            parts.append(f"换手{v.get('turnover_pct')}%")
        if v.get("high") is not None and v.get("low") is not None:
            parts.append(f"今日{v.get('low')}~{v.get('high')}")
        lines.append("  - " + " | ".join(str(p) for p in parts))

    return "\n".join(lines) if len(lines) > 1 else ""


# ---------------------------------------------------------------------------
# 技术面（从 stock_kline 现算 MA / 趋势 / 位置）
# ---------------------------------------------------------------------------

def _tech_brief_from_bars(bars: list[dict]) -> str | None:
    """对一段日线 bars 现算技术面速写。bar 不足 20 根时返回 None。"""
    if not bars or len(bars) < 20:
        return None

    closes = [b["close"] for b in bars if b.get("close") is not None]
    if len(closes) < 20:
        return None
    last = closes[-1]

    def _ma(n: int) -> float | None:
        return round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None

    ma5, ma10, ma20, ma60 = _ma(5), _ma(10), _ma(20), _ma(60)

    parts: list[str] = []
    # 均线排列（多头/空头/纠缠）
    ordered = [m for m in (ma5, ma10, ma20, ma60) if m is not None]
    if ma5 and ma20:
        if ma5 > ma20 and (ma60 is None or ma20 > ma60):
            parts.append("均线多头排列")
        elif ma5 < ma20 and (ma60 is None or ma20 < ma60):
            parts.append("均线空头排列")
        else:
            parts.append("均线纠缠")
    ma_txt = "/".join(
        f"{lbl}{val}" for lbl, val in
        (("MA5", ma5), ("MA20", ma20), ("MA60", ma60)) if val is not None
    )
    if ma_txt:
        parts.append(ma_txt)
    # 现价相对 MA20
    if ma20:
        parts.append(f"现价{'上' if last >= ma20 else '下'}破MA20({(last/ma20-1)*100:+.1f}%)")

    # 近 N 日累计涨跌
    for n, lbl in ((5, "近5日"), (20, "近20日")):
        if len(closes) > n:
            chg = (last / closes[-n - 1] - 1) * 100
            parts.append(f"{lbl}{chg:+.1f}%")

    # 年内（最多 250 日）高低位置
    win = closes[-250:]
    hi, lo = max(win), min(win)
    if hi > lo:
        pos = (last - lo) / (hi - lo) * 100
        parts.append(f"处于{len(win)}日区间{pos:.0f}%位置(高{hi}/低{lo})")

    return " | ".join(parts) if parts else None


def _kline_tail_lines(bars: list[dict], n: int = 10) -> list[str]:
    """取最近 n 根日线的开/高/低/收原始数据，格式化成缩进行（供模型看具体盘面）。"""
    out: list[str] = []
    for b in bars[-n:]:
        d = b.get("date") or b.get("datetime") or ""
        o, h, l, c = b.get("open"), b.get("high"), b.get("low"), b.get("close")
        if c is None:
            continue
        seg = f"{d} 开{o} 高{h} 低{l} 收{c}"
        cp = b.get("change_pct")
        if cp is not None:
            try:
                seg += f" 涨跌{float(cp):+.1f}%"
            except (TypeError, ValueError):
                pass
        out.append("    " + seg)
    return out


async def _kline_for(code: str, count: int = 250) -> list[dict]:
    """取某只股票日线：本地库优先，库里没有/不足则联网增量补齐并落库（兜底现拉）。

    复用 market._kline_cached（iFinD 优先、回退腾讯，上游失败仍返回本地已有），
    这样聊到「冷门股 / 还没被预热进库」的票时也能拿到 K 线，而不是静默跳过。
    """
    c = code.zfill(6)
    try:
        from quantforge.api.routes import market
        bars, _ = await market._kline_cached(c, "day", count)
        return bars or []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chat: kline fetch failed ({c}): {e}")
        try:
            from quantforge.data.storage import db_cache
            return db_cache.kline_load(c, "day", limit=count)
        except Exception:
            return []


async def _build_tech_context(codes: list[str]) -> str:
    """对识别出的代码取日线(库里没有就现拉)，拼技术面速写 + 最近 10 日原始 K 线。"""
    if not codes:
        return ""

    names = _all_names()
    results = await asyncio.gather(*[_kline_for(c) for c in codes])

    tech_lines = ["\n\n[技术面参考 — 基于日线现算的均线/趋势/位置，请据此判断强弱]"]
    raw_lines: list[str] = []
    for code, bars in zip(codes, results):
        c = code.zfill(6)
        name = names.get(c, "")
        brief = _tech_brief_from_bars(bars)
        if brief:
            tech_lines.append(f"  - {c} {name}：{brief}".rstrip())
        tail = _kline_tail_lines(bars, 10)
        if tail:
            raw_lines.append(f"  - {c} {name} 最近{len(tail)}日日K(开/高/低/收)：".rstrip())
            raw_lines.extend(tail)

    out: list[str] = []
    if len(tech_lines) > 1:
        out.append("\n".join(tech_lines))
    if raw_lines:
        out.append("\n\n[最近日K原始数据 — 逐日开高低收，可据此点评近期具体盘面]\n"
                   + "\n".join(raw_lines))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 机构一致预期（从 stock_reports 聚合：目标价 / 评级 / 盈利预测）
# ---------------------------------------------------------------------------

async def _build_reports_context(codes: list[str]) -> str:
    """对识别出的代码读研报库，拼成机构一致预期上下文。"""
    if not codes:
        return ""

    from quantforge.data.storage import db_cache

    names = _all_names()
    try:
        summaries = await asyncio.to_thread(
            lambda: [(c, names.get(c.zfill(6), ""), db_cache.reports_summary(c.zfill(6)))
                     for c in codes]
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chat: reports context failed: {e}")
        return ""

    lines = ["\n\n[机构一致预期 — 近一年研报聚合，请对比现价判断估值高低与上行空间]"]
    for code, name, s in summaries:
        if not s or not s.get("count"):
            continue
        parts = [f"{code} {name}".strip(), f"研报{s['count']}篇"]
        if s.get("latest_date"):
            parts.append(f"最新{s['latest_date']}")
        ratings = s.get("ratings") or {}
        if ratings:
            rt = "、".join(f"{k}{v}" for k, v in
                           sorted(ratings.items(), key=lambda kv: -kv[1])[:3])
            parts.append(f"评级[{rt}]")
        tgt = s.get("target")
        if tgt:
            parts.append(f"目标价均{tgt['avg']}(高{tgt['high']}/低{tgt['low']},{tgt['count']}家)")
        eps_pe = []
        if s.get("eps_this") is not None:
            eps_pe.append(f"今年EPS{s['eps_this']}/PE{s.get('pe_this')}")
        if s.get("eps_next") is not None:
            eps_pe.append(f"明年EPS{s['eps_next']}/PE{s.get('pe_next')}")
        if eps_pe:
            parts.append("预测" + "、".join(eps_pe))
        lines.append("  - " + " | ".join(str(p) for p in parts))

    return "\n".join(lines) if len(lines) > 1 else ""


def _board_match_keys(name: str) -> set[str]:
    """板块名的匹配关键词集合：原名 + 剥掉常见后缀的核心词(≥2字)。"""
    keys = {name}
    for suf in ("概念", "行业", "板块", "指数", "产业"):
        if name.endswith(suf) and len(name) > len(suf):
            keys.add(name[: -len(suf)])
    return {k for k in keys if len(k) >= 2}


async def _build_sector_context(last_user: str) -> str:
    """匹配最近用户消息里提到的板块名(行业/概念)，拼成板块行情上下文。"""
    if not last_user:
        return ""

    try:
        from quantforge.api.routes import sector
        industry = await sector._sina_boards_cached()
        # 概念**只用同花顺指数**(概念页/预热器落库的 sector_boards)，不回退新浪
        concept = sector.cached_concept_boards()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chat: sector context fetch failed: {e}")
        return ""

    matched: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for kind, boards in (("行业", industry), ("概念", concept)):
        for b in boards or []:
            name = (b.get("name") or "").strip()
            if not name or name in seen:
                continue
            # 用「板块名」及其剥掉 概念/行业 等后缀的核心词去匹配，
            # 这样用户说「白酒」也能命中「白酒概念」、「电力」命中「电力行业」。
            if any(k in last_user for k in _board_match_keys(name)):
                seen.add(name)
                matched.append((kind, b))
    matched = matched[:4]
    if not matched:
        return ""

    lines = ["\n\n[板块行情参考 — 请基于以下真实数据分析板块，不要编造]"]
    for kind, b in matched:
        parts = [f"{b.get('name')}({kind}板块)"]
        if b.get("change_pct") is not None:
            try:
                parts.append(f"板块涨跌{float(b['change_pct']):+.2f}%")
            except (TypeError, ValueError):
                pass
        if b.get("leader"):
            parts.append(f"领涨股{b.get('leader')}")
        if b.get("amount"):
            try:
                parts.append(f"成交额{float(b['amount']) / 1e8:.1f}亿")
            except (TypeError, ValueError):
                pass
        if b.get("count"):
            parts.append(f"成分股{b.get('count')}只")
        lines.append("  - " + " | ".join(str(p) for p in parts))

        # 板块内领涨/领跌成分股（读库 sector_constituents，给 AI 看资金流向）
        kind_key = "industry" if kind == "行业" else "concept"
        try:
            from quantforge.data.storage import db_cache
            cons = await asyncio.to_thread(
                db_cache.get_sector_constituents, kind_key, b.get("name"))
        except Exception:
            cons = None
        if cons:
            ranked = [c for c in cons if c.get("change_pct") is not None]
            ranked.sort(key=lambda c: c["change_pct"], reverse=True)
            top = ranked[:3]
            bot = ranked[-3:][::-1] if len(ranked) > 3 else []
            def _fmt(c):
                return f"{c.get('name') or c.get('code')}{c['change_pct']:+.1f}%"
            if top:
                lines.append("    领涨：" + "、".join(_fmt(c) for c in top))
            if bot:
                lines.append("    领跌：" + "、".join(_fmt(c) for c in bot))

    return "\n".join(lines) if len(lines) > 1 else ""


# ---------------------------------------------------------------------------
# 个性化：用户提到「自选/持仓」时带其自选股行情概览
# ---------------------------------------------------------------------------

_WATCH_RE = re.compile(r"自选|持仓|我的(?:股|票|仓)|关注的")


async def _build_watchlist_context(last_user: str, user_id: str | None) -> str:
    """登录用户问及「自选/持仓」时，注入其自选股行情概览（读库 watchlist+stock_quote）。"""
    if not user_id:
        return ""
    if not last_user or not _WATCH_RE.search(last_user):
        return ""

    from quantforge.data.storage import db_cache

    try:
        items = await asyncio.to_thread(db_cache.get_watchlist, user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chat: watchlist context failed: {e}")
        return ""
    if not items:
        return "\n\n[用户自选 — 当前用户自选股为空]"

    codes = [it["code"] for it in items][:30]
    quotes = await asyncio.to_thread(db_cache.quote_get_many, codes)

    rows = []
    for it in items[:30]:
        q = quotes.get(it["code"]) or {}
        cp = q.get("change_pct")
        rows.append((cp if cp is not None else -999, it, q))
    rows.sort(key=lambda r: r[0], reverse=True)

    lines = [f"\n\n[用户自选 — 共{len(items)}只，以下为行情概览，可据此点评组合]"]
    for _, it, q in rows:
        nm = q.get("name") or it.get("name") or it["code"]
        parts = [f"{it['code']} {nm}"]
        if q.get("price") is not None:
            parts.append(f"现价{q['price']}")
        if q.get("change_pct") is not None:
            parts.append(f"{float(q['change_pct']):+.2f}%")
        if q.get("pe"):
            parts.append(f"PE{q['pe']}")
        if it.get("notes"):
            parts.append(f"备注「{it['notes'][:20]}」")
        lines.append("  - " + " | ".join(str(p) for p in parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 行业/主题研报（industry_reports 观点 + research_pdfs 正文摘录）
# ---------------------------------------------------------------------------
# 这两张库主要是「行业/产业链」级别(个股归属很少)，所以挂在板块名/主题词上，
# 而非个股代码。给 AI 看：① 机构对该行业的最新观点列表 ② 一篇研报正文摘录。

# 触发「研报观点」的行业/主题词：板块词太泛(如「行业」)无意义，这里取消息里出现的
# 中文连续词(2-6字)做候选，再交给库的 LIKE 检索去筛(命中即有料，否则空块跳过)。
_THEME_RE = re.compile(r"[一-龥]{2,6}")
# 明显非主题的停用词，避免拿「分析」「怎么」去检索研报
_THEME_STOP = {
    "怎么", "怎样", "如何", "现在", "最近", "板块", "行业", "概念", "分析", "看看",
    "帮我", "估值", "目标", "机构", "技术", "趋势", "未来", "今天", "明天", "走势",
    "建议", "风险", "买入", "卖出", "持有", "自选", "持仓", "对比", "还是", "哪个",
}


def _theme_terms(text: str) -> list[str]:
    """从用户消息提取候选主题词（2-6 字中文，去停用词、去纯数字、保序去重）。"""
    if not text:
        return []
    out: list[str] = []
    for w in _THEME_RE.findall(text):
        if w in _THEME_STOP or w in out:
            continue
        out.append(w)
    return out[:6]


async def _build_research_context(terms: list[str]) -> str:
    """匹配用户消息里的行业/主题词，注入机构研报观点 + 一篇正文摘录。

    读库 industry_reports(观点) + research_pdfs(正文)，零网络依赖。命中才注入。
    """
    if not terms:
        return ""

    from quantforge.data.storage import db_cache
    import datetime as _dt
    begin = (_dt.date.today() - _dt.timedelta(days=120)).isoformat()

    def _gather() -> tuple[list[dict], list[dict]]:
        # 行业研报观点：近 120 天，命中任一主题词（只展示前 6 条，多取一些做去重冗余）
        reps = db_cache.industry_reports_search(terms, begin_date=begin, limit=12)
        # 研报正文：逐词找第一个命中、有正文的库，最多取 2 篇
        pdfs: list[dict] = []
        seen_ic: set[str] = set()
        pdf_floor = (_dt.date.today() - _dt.timedelta(days=365)).isoformat()
        for t in terms:
            rows, _ = db_cache.research_pdf_query(
                q=t, has_text=True, start=pdf_floor,
                sort_by="date", order="desc", page_size=2)
            for r in rows:
                if r["info_code"] not in seen_ic:
                    seen_ic.add(r["info_code"])
                    pdfs.append(r)
            if len(pdfs) >= 2:
                break
        return reps, pdfs[:2]

    try:
        reps, pdfs = await asyncio.to_thread(_gather)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"chat: research context failed: {e}")
        return ""

    if not reps and not pdfs:
        return ""

    lines: list[str] = []
    if reps:
        # 按行业名聚合，列最近的几条观点
        lines.append("\n\n[机构行业研报观点 — 近期卖方对相关行业的研判，请提炼共识与分歧]")
        for r in reps[:6]:
            parts = [r.get("publish_date") or "", r.get("org") or "",
                     r.get("industry_name") or ""]
            title = (r.get("title") or "").strip()
            seg = " ".join(p for p in parts if p)
            lines.append(f"  - {seg}：{title[:46]}" if title else f"  - {seg}")

    if pdfs:
        lines.append("\n[研报正文摘录 — 以下为相关研报原文片段，可引用其核心逻辑]")
        for r in pdfs:
            txt = await asyncio.to_thread(db_cache.research_pdf_get_text, r["info_code"])
            if not txt:
                continue
            head = f"{r.get('publish_date') or ''} {r.get('org') or ''} {(r.get('title') or '')[:40]}".strip()
            excerpt = txt.strip().replace("\n", " ")[:600]
            lines.append(f"  《{head}》\n  {excerpt}…")

    return "\n".join(lines) if lines else ""


# ---------------------------------------------------------------------------
# 资金面（主力资金净流入，东财 120 日资金流现算）
# ---------------------------------------------------------------------------
# 逐只深挖、较重，故只对最先识别的前 2 只票拉取。融资融券/股东户数/龙虎榜在本
# 环境数据源不稳(返回空)，暂不接——主力净流入是竞品最看重的核心资金信号。

def _yi(v) -> str | None:
    """元 → 带符号亿元字符串（保留 2 位）。"""
    try:
        return f"{float(v) / 1e8:+.2f}亿"
    except (TypeError, ValueError):
        return None


def _main_inflow_brief(code: str) -> str | None:
    """东财 120 日资金流 → 主力净流入：今日 / 近5日 / 近20日累计 + 净流入天数。"""
    from quantforge.api.routes import capital_flow
    # push2his.eastmoney 偶发被代理劫持(空返回)，轻量重试 1 次提升命中率
    klines = capital_flow._eastmoney_push2his_funds_120(code.zfill(6))
    if not klines:
        klines = capital_flow._eastmoney_push2his_funds_120(code.zfill(6))
    main: list[float] = []
    for row in klines or []:
        parts = str(row).split(",")   # date,主力净流入,小单,中单,大单,超大单,...
        if len(parts) >= 2:
            try:
                main.append(float(parts[1]))
            except ValueError:
                pass
    if not main:
        return None
    segs: list[str] = []
    t = _yi(main[-1])
    if t:
        segs.append(f"今日{t}")
    d5 = _yi(sum(main[-5:]))
    if d5:
        segs.append(f"近5日{d5}")
    d20 = _yi(sum(main[-20:]))
    if d20:
        segs.append(f"近20日{d20}")
    n = min(len(main), 20)
    if n:
        pos = sum(1 for x in main[-n:] if x > 0)
        segs.append(f"近{n}日{pos}天净流入")
    return "主力净流入 " + "、".join(segs) if segs else None


async def _build_capital_context(codes: list[str]) -> str:
    """对最先识别的前 2 只票拉主力资金净流入，拼成资金面上下文。"""
    if not codes:
        return ""
    names = _all_names()
    targets = codes[:2]
    briefs = await asyncio.gather(
        *[asyncio.to_thread(_main_inflow_brief, c) for c in targets]
    )
    lines = ["\n\n[资金面参考 — 主力资金净流入(>0 主力净买、<0 主力净卖)，"
             "据此判断主力态度与资金持续性]"]
    hit = False
    for code, brief in zip(targets, briefs):
        if brief:
            hit = True
            c = code.zfill(6)
            lines.append(f"  - {c} {names.get(c, '')}：{brief}".rstrip())
    return "\n".join(lines) if hit else ""


# ---------------------------------------------------------------------------
# 真实财务报表（近 3 年年报：营收/净利及同比、毛利率、ROE、资产负债率）
# ---------------------------------------------------------------------------
# 区别于「机构一致预期」给的是未来 EPS 预测，这里是已披露的**真实历史财报**。

def _financials_brief(code: str) -> str | None:
    """近 3 年年报关键指标，按报告期降序格式化成多行。"""
    from quantforge.api.routes.stock_analysis import _fetch_financials
    rows = _fetch_financials(code.zfill(6), years=3)
    if not rows:
        return None

    def _yi2(v) -> str:
        try:
            return f"{float(v) / 1e8:.0f}亿"
        except (TypeError, ValueError):
            return "—"

    def _pct(v) -> str:
        try:
            return f"{float(v):+.1f}%"
        except (TypeError, ValueError):
            return "—"

    out: list[str] = []
    for r in rows:
        out.append(
            f"    {r.get('period')}: 营收{_yi2(r.get('revenue'))}"
            f"(同比{_pct(r.get('revenue_yoy'))})、"
            f"净利{_yi2(r.get('net_profit'))}(同比{_pct(r.get('net_profit_yoy'))})、"
            f"毛利率{_pct(r.get('gross_margin'))}、ROE{_pct(r.get('roe'))}、"
            f"负债率{_pct(r.get('debt_ratio'))}"
        )
    return "\n".join(out) if out else None


async def _build_financials_context(codes: list[str]) -> str:
    """对最先识别的前 2 只票拉近 3 年真实年报，拼成财务上下文。"""
    if not codes:
        return ""
    names = _all_names()
    targets = codes[:2]
    briefs = await asyncio.gather(
        *[asyncio.to_thread(_financials_brief, c) for c in targets]
    )
    lines = ["\n\n[真实财务报表 — 近3年年报关键指标，请据此看成长性/盈利质量/财务健康，"
             "区别于上面机构对未来的预测]"]
    hit = False
    for code, brief in zip(targets, briefs):
        if brief:
            hit = True
            c = code.zfill(6)
            lines.append(f"  - {c} {names.get(c, '')} 近3年年报：")
            lines.append(brief)
    return "\n".join(lines) if hit else ""


# ---------------------------------------------------------------------------
# 联网实时资讯（个股新闻/公告，实时抓取）—— 仅在用户勾选「查询外网」时触发
# ---------------------------------------------------------------------------
# 与上面「读本地库」的上下文不同，这一路会**实时联网**抓取个股最新新闻/公告，
# 补充库里没有的时效信息。复用 news._fetch_stock_news(akshare+同花顺+东财公告)。

async def _build_news_context(codes: list[str], use_web: bool) -> str:
    """勾选「查询外网」且识别到个股时，实时抓取其新闻/公告标题拼进上下文。"""
    if not use_web or not codes:
        return ""

    names = _all_names()

    async def _one(code: str) -> tuple[str, str, list[dict]]:
        c = code.zfill(6)
        try:
            from quantforge.api.routes import news as news_mod
            items = await asyncio.to_thread(news_mod._fetch_stock_news, c, 8)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"chat: news fetch failed ({c}): {e}")
            items = []
        return c, names.get(c, ""), items

    results = await asyncio.gather(*[_one(c) for c in codes])

    lines = ["\n\n[实时资讯(联网) — 刚抓取的个股新闻/公告标题，可据此补充最新动态，"
             "注意时效，与上面历史数据相互印证]"]
    hit = False
    for code, name, items in results:
        if not items:
            continue
        hit = True
        lines.append(f"  - {code} {name}：")
        for it in items[:6]:
            when = f"{it.get('date', '')} {it.get('time', '')}".strip()
            title = (it.get("title") or "").strip()
            src = it.get("source") or ""
            if title:
                lines.append(f"    · {when} {title}（{src}）".rstrip())
    return "\n".join(lines) if hit else ""


# ---------------------------------------------------------------------------
# 自然语言选股（问财式）：识别选股意图 → LLM 解析条件 → 跑全市场快照出名单
# ---------------------------------------------------------------------------
# 数据走 screener.universe 的本地实时快照(快、可靠)，支持 PE/PB/涨跌幅/换手/市值/股价；
# ROE 需逐只补充(慢)，故仅在粗筛后的小子集上 best-effort 补。营收/利润增长等财报维度
# 需逐只年报，本版不在选股里支持(会在结果里说明)。

_SCREEN_INTENT_RE = re.compile(
    r"选股|筛选|帮我(找|选|挑|筛)|符合.{0,8}条件|哪些股票|有什么股票|有哪些.{0,4}股|"
    r"找出.{0,10}股|筛.{0,4}出|市盈率.{0,8}(低于|小于|大于|高于|超过)|"
    r"市值.{0,8}(低于|小于|大于|高于|超过)|涨幅.{0,8}(超过|大于|低于)"
)

# 允许的选股字段 → universe 快照列名（market_cap 在快照里是「元」，条件按「亿」）
_SCREEN_FIELDS = {"pe", "pb", "change_pct", "turnover_rate", "market_cap", "price", "roe"}
_SNAPSHOT_FIELDS_OK = {"pe", "pb", "change_pct", "turnover_rate", "market_cap", "price"}

_SCREEN_PARSE_SYSTEM = (
    "你是 A 股选股条件解析器。把用户的自然语言选股需求解析成 JSON。"
    "只能使用这些字段：pe(市盈率)、pb(市净率)、change_pct(当日涨跌幅%)、"
    "turnover_rate(换手率%)、market_cap(总市值，单位亿元)、price(股价，元)、"
    "roe(净资产收益率%)。"
    '输出严格为 JSON：{"filters":[{"field":"pe","op":"<","value":20}],'
    '"sort":{"field":"change_pct","order":"desc"},"limit":15}。'
    "op 只能是 < <= > >= 之一；value 为数字。无法映射到上述字段的条件请忽略。"
    "只输出 JSON，不要任何多余文字。"
)


async def _parse_screen(text: str, account: str | None) -> dict:
    """用一次轻量 LLM 调用把 NL 选股需求解析为结构化条件；失败返回空。"""
    from quantforge.api.ai_client import chat as ai_chat
    try:
        raw = await ai_chat(_SCREEN_PARSE_SYSTEM, text[:300], max_tokens=240,
                            caller="chat_screen", account=account, timeout=25)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chat screen parse failed: {e}")
        return {}
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


def _apply_screen(df, filters: list[dict]) -> tuple[object, list[str], list[str]]:
    """在 universe DataFrame 上应用快照可支持的条件；返回 (子集, 已应用, 跳过)。"""
    import pandas as pd

    work = df
    applied: list[str] = []
    skipped: list[str] = []
    op_label = {"<": "<", "<=": "≤", ">": ">", ">=": "≥"}
    for f in filters:
        field = str(f.get("field", "")).strip()
        op = str(f.get("op", "")).strip()
        try:
            val = float(f.get("value"))
        except (TypeError, ValueError):
            continue
        if field not in _SNAPSHOT_FIELDS_OK or op not in op_label or field not in work.columns:
            skipped.append(f"{field}{op}{f.get('value')}")
            continue
        thr = val * 1e8 if field == "market_cap" else val   # 市值：亿 → 元
        s = pd.to_numeric(work[field], errors="coerce")
        mask = {"<": s < thr, "<=": s <= thr, ">": s > thr, ">=": s >= thr}[op]
        work = work[mask.fillna(False)]
        unit = "亿" if field == "market_cap" else ""
        applied.append(f"{field}{op_label[op]}{val:g}{unit}")
    return work, applied, skipped


async def _build_screen_context(last_user: str, account: str | None) -> str:
    """识别到选股意图时，解析条件并从全市场快照筛出名单，拼成上下文。"""
    if not last_user or not _SCREEN_INTENT_RE.search(last_user):
        return ""

    spec = await _parse_screen(last_user, account)
    filters = [f for f in (spec.get("filters") or []) if isinstance(f, dict)]
    if not filters:
        return ""

    from quantforge.screener import universe
    df = await universe.fetch_universe()
    if df is None or getattr(df, "empty", True):
        return ""

    sub, applied, skipped = _apply_screen(df, filters)

    # ROE 条件：在已粗筛的小子集(≤80)上 best-effort 补一次，再过滤
    wants_roe = [f for f in filters if f.get("field") == "roe"]
    if wants_roe and 0 < len(sub) <= 80:
        try:
            import pandas as pd
            sub = await universe.enrich_with_fundamentals(sub, sub["code"].tolist())
            if "roe" in sub.columns:
                op_label = {"<": "<", "<=": "≤", ">": ">", ">=": "≥"}
                for f in wants_roe:
                    op = str(f.get("op", "")).strip()
                    try:
                        v = float(f.get("value"))
                    except (TypeError, ValueError):
                        continue
                    if op not in op_label:
                        continue
                    s = pd.to_numeric(sub["roe"], errors="coerce")
                    mask = {"<": s < v, "<=": s <= v, ">": s > v, ">=": s >= v}[op]
                    sub = sub[mask.fillna(False)]
                    applied.append(f"roe{op_label[op]}{v:g}%")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"chat screen roe enrich failed: {e}")
            skipped.extend(f"roe{f.get('op')}{f.get('value')}" for f in wants_roe)
    elif wants_roe:
        skipped.extend(f"roe{f.get('op')}{f.get('value')}" for f in wants_roe)

    if not applied:
        return ""

    # 排序
    sort = spec.get("sort") or {}
    sort_field = sort.get("field") if isinstance(sort, dict) else None
    order = (sort.get("order") if isinstance(sort, dict) else "desc") or "desc"
    if sort_field in getattr(sub, "columns", []):
        try:
            sub = sub.sort_values(sort_field, ascending=(order == "asc"), na_position="last")
        except Exception:  # noqa: BLE001
            pass

    try:
        limit = int(spec.get("limit") or 15)
    except (TypeError, ValueError):
        limit = 15
    limit = max(1, min(limit, 30))

    total = len(sub)
    rows = sub.head(limit).to_dict("records")
    if total == 0:
        return (f"\n\n[选股结果 — 已应用条件: {'、'.join(applied)}；全市场快照内"
                f"**无股票同时满足**。请如实告知用户没有匹配标的，建议放宽条件。]")

    lines = [f"\n\n[选股结果 — 按用户条件从全市场实时快照({len(df)}只)筛出。"
             f"已应用: {'、'.join(applied)}；共命中 {total} 只，列前 {len(rows)}。"
             f"请据此点评名单、挑出更值得关注的并说明逻辑，提醒非投资建议]"]
    for r in rows:
        code = str(r.get("code", "")).zfill(6)
        parts = [f"{code} {r.get('name', '')}".strip()]
        if r.get("price") is not None:
            parts.append(f"现价{r.get('price')}")
        if r.get("change_pct") is not None:
            try:
                parts.append(f"涨跌{float(r['change_pct']):+.2f}%")
            except (TypeError, ValueError):
                pass
        if r.get("pe") is not None:
            parts.append(f"PE{r.get('pe')}")
        if r.get("pb") is not None:
            parts.append(f"PB{r.get('pb')}")
        if r.get("market_cap") is not None:
            try:
                parts.append(f"市值{float(r['market_cap']) / 1e8:.0f}亿")
            except (TypeError, ValueError):
                pass
        if r.get("turnover_rate") is not None:
            parts.append(f"换手{r.get('turnover_rate')}%")
        if r.get("roe") is not None:
            try:
                parts.append(f"ROE{float(r['roe']):.1f}%")
            except (TypeError, ValueError):
                pass
        lines.append("  - " + " | ".join(str(p) for p in parts))
    if skipped:
        lines.append(f"  （未支持的条件已跳过：{'、'.join(skipped)}——如涉及营收/利润增长等"
                     f"财报维度，本次选股暂不支持，可在结果里说明）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 追问建议：答完后用一次轻量 LLM 调用，产出 3 个用户最可能继续问的问题（chip）
# ---------------------------------------------------------------------------

_FOLLOWUP_SYSTEM = (
    "你是 A 股投资助手的「追问建议」生成器。根据用户问题与助手回答，生成 3 个用户"
    "最可能继续追问的简短问题（每个≤14字，具体、可操作、不重复已答内容，"
    "可涉及估值/资金/风险/对比/买卖点等）。只输出 JSON 数组，"
    '形如 ["问题1","问题2","问题3"]，不要任何多余文字。'
)


# 确定性兜底：当二次 LLM 生成追问失败/超载/回答过短返回空时，按本轮上下文给一组
# 合理的「下一个问题」，保证推荐模块始终在场，不因 chat_suggest 抖动而消失。
_FALLBACK_STOCK = [
    "现在估值贵不贵？", "主力资金在买还是卖？", "技术面处于什么位置？", "有哪些主要风险？",
]
_FALLBACK_SECTOR = [
    "板块里哪些龙头值得关注？", "这个方向的催化剂是什么？", "近期资金在流入吗？",
]
_FALLBACK_SCREEN = [
    "从名单里挑出最值得关注的 3 只", "再加一个 ROE>15% 的条件", "按主力资金强弱排个序",
]
_FALLBACK_DEFAULT = [
    "最近有什么热点题材？", "帮我看看今天大盘走势", "推荐几只低估值的股票",
]


def _fallback_followups(codes: list[str], sources: list[str]) -> list[str]:
    """无 LLM 追问时，按本轮命中的数据来源/标的，挑一组贴合语境的默认追问。"""
    if "选股结果" in sources:
        return list(_FALLBACK_SCREEN)
    if codes:
        return list(_FALLBACK_STOCK)
    if "板块行情" in sources or "行业研报" in sources:
        return list(_FALLBACK_SECTOR)
    return list(_FALLBACK_DEFAULT)


async def _gen_followups(last_user: str, answer: str, account: str | None) -> list[str]:
    """最佳努力地生成 3 个追问建议；任何失败都静默返回空（不影响主回答）。"""
    if not answer or len(answer) < 40:
        return []
    from quantforge.api.ai_client import chat as ai_chat
    user = f"用户问题：{last_user[:200]}\n\n助手回答：{answer[:1200]}"
    try:
        raw = await ai_chat(_FOLLOWUP_SYSTEM, user, max_tokens=150,
                            caller="chat_suggest", account=account, timeout=20)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"chat followups failed: {e}")
        return []
    m = re.search(r"\[.*\]", raw or "", re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return []
    out = [str(x).strip() for x in arr if str(x).strip()]
    return out[:3]


@router.post("/stream")
async def chat_stream_endpoint(
    req: ChatRequest,
    current_user: dict | None = Depends(get_optional_user),
):
    """流式对话。返回 text/event-stream，逐 token 推送。

    带有效登录态时把 token 用量记到该账号名下（后台模块据此统计）。
    """
    from quantforge.api.ai_client import chat_stream

    account = current_user["username"] if current_user else None
    user_id = current_user.get("id") if current_user else None

    messages = [{"role": m.role, "content": m.content} for m in req.messages if m.content.strip()]
    if not messages:
        async def _empty():
            yield 'data: {"done": true}\n\n'
        return StreamingResponse(_empty(), media_type="text/event-stream")

    # 本轮用户消息（最后一条 user）：上下文识别与流结束存档都用它，只算一次
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

    system = _SYSTEM_PROMPT
    codes: list[str] = []
    sources: list[str] = []     # 本轮实际用到的数据来源（供前端「溯源」标签）
    if req.use_quotes:
        # 多轮指代继承：本轮没带标的且像追问时，借用上文最近一条带标的的消息，使
        # 「它/这只/对比下竞品」等延续问题的行情/技术/资金/研报/板块数据块不落空。
        ctx_text = _resolve_context_text(messages, last_user)
        # 代码 / 主题词只识别一次，共享给各 builder（避免每路重复跑全量股名匹配）
        codes = _extract_codes(ctx_text)
        terms = _theme_terms(ctx_text)
        # 并发拉取各路上下文：行情/机构预期/板块/行业研报/自选读本地库；技术面在库里
        # 缺 K 线时会联网增量补齐；资金面/财务逐只联网拉(限前2只)；新闻仅在勾选外网时抓。
        # 板块用继承后的 ctx_text；自选/选股是「当轮意图」识别，仍只看本轮 last_user。
        ctxs = await asyncio.gather(
            _build_quote_context(codes),
            _build_tech_context(codes),
            _build_capital_context(codes),
            _build_financials_context(codes),
            _build_reports_context(codes),
            _build_sector_context(ctx_text),
            _build_research_context(terms),
            _build_watchlist_context(last_user, user_id),
            _build_news_context(codes, req.use_web),
            _build_screen_context(last_user, account),
        )
        # 与 ctxs 同序的来源标签：非空者计入「溯源」
        _labels = ["实时行情", "技术面/K线", "资金面", "财务报表", "机构预期",
                   "板块行情", "行业研报", "用户自选", "实时资讯(联网)", "选股结果"]
        for ctx, label in zip(ctxs, _labels):
            if ctx:
                system = system + ctx
                sources.append(label)

    # 深度分析模式：追加结构化推理要求 + 放大输出预算
    if req.deep:
        system = system + _DEEP_SUFFIX
    max_tokens = 4096 if req.deep else 2048

    # 前端用：识别到的个股(画迷你图) + 实际数据来源(溯源标签)
    meta = {"stocks": [c.zfill(6) for c in codes[:3]], "sources": sources}

    async def _gen():
        parts: list[str] = []
        try:
            # 先推一条 meta（个股代码 + 数据来源），让前端即时画图/显示来源
            yield f"data: {json.dumps({'meta': meta}, ensure_ascii=False)}\n\n"
            async for delta in chat_stream(messages, system=system, max_tokens=max_tokens,
                                           caller="chat", account=account):
                parts.append(delta)
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            # 主回答完成 → 追问建议（LLM 生成优先，失败/空则确定性兜底，保证模块常驻）
            answer = "".join(parts)
            sugg: list[str] = []
            try:
                sugg = await _gen_followups(last_user, answer, account)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"chat suggestions gen failed: {e}")
            if not sugg and answer.strip():
                sugg = _fallback_followups(codes, sources)
            if sugg:
                yield f"data: {json.dumps({'suggestions': sugg}, ensure_ascii=False)}\n\n"
            yield 'data: {"done": true}\n\n'
        except Exception as e:  # noqa: BLE001
            logger.warning(f"chat stream failed: {type(e).__name__}: {e}")
            yield f"data: {json.dumps({'error': str(e)[:200]}, ensure_ascii=False)}\n\n"
        finally:
            # 流结束后落库整轮对话（拼完整段再写一次，不逐 delta 写）。
            answer = "".join(parts)
            if req.session_id and (last_user.strip() or answer.strip()):
                try:
                    from quantforge.data.storage import db_cache
                    await asyncio.to_thread(
                        db_cache.chat_log_turn, user_id, account,
                        req.session_id, req.title, last_user, answer,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"chat archive failed: {e}")

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
