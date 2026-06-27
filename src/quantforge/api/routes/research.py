"""
研报 API (基于 a-stock-data 3.1)
- 东财 reportapi: 研报列表 + PDF下载
- 同花顺一致预期EPS
- 概念板块/产业链数据
- AI分析任务接口
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from loguru import logger
import pandas as pd

# 纯辅助逻辑已抽到 ..research_helpers（外部如 ai_picks/stock_analysis 仍 import
# routes.research.<helper>，这里 re-export 保持其导入路径不变）。
from ..research_helpers import (  # noqa: F401  (re-export 供内部 & 外部模块复用)
    UA, REPORT_API, DATACENTER_URL, _REPORT_LOOKBACK_DAYS,
    _eastmoney_datacenter, _eastmoney_reports, _rf,
    _norm_report_row, _norm_industry_report_row,
    _fetch_all_reports_pages,
    _store_reports, _store_stock_reports, _store_industry_reports, _store_reports_mixed,
    _ths_consensus_eps, _get_concept_stocks, _normalise_cons_stocks,
    _report_industries, _match_industry_codes,
    _eastmoney_reports_by_industry, _eastmoney_industry_reports, _smartbox,
    _stored_stock_report_to_raw, _stored_industry_report_to_raw,
    _strip_json, _repair_json_text, _loads_lenient, _chat_json,
    _bom_leaves, _bom_all_nodes, _slug, _s, _as_dict,
    _fact_block, _fact_line, _facts_digest, _fmt_eta, _estimate_eta,
    _T_PER_PDF, _T_PER_MAP_WAVE, _T_REDUCE_TAIL, _MAP_BATCH, _MAP_CONC, _DL_WORKERS,
    _MAP_MAX_TOKENS,
)

# MiniMax-M3 单次输出硬顶：请求 max_tokens 超过它直接 400（线上实测 122 次/日）。
# MAP 重试时 +2048 会把已经顶格的 _MAP_MAX_TOKENS(=524288) 顶出界，必须 clamp。
_MODEL_MAX_OUTPUT = int(os.getenv("QF_MODEL_MAX_OUTPUT") or 524288)

from .auth import get_admin_user  # 产业链分析触发收口到管理员

router = APIRouter(prefix="/research", tags=["research"])

PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

# AI分析任务缓存和状态
# 锚定到仓库根的绝对路径，**不随启动 CWD 漂移**：后端有时从项目根、有时从 web/ 启动，
# 若用相对路径，task 文件会散落到两个 data/cache/industry_tasks 目录，/saved-reports
# 只 glob 当前 CWD 那一份 → 历史「生成记录」时多时少地漏。绝对路径根治该分裂。
# research.py 位于 src/quantforge/api/routes/ → parents[4] 即仓库根。
_TASKS_DIR = Path(__file__).resolve().parents[4] / "data" / "cache" / "industry_tasks"

# 运行态进度跨 worker 共享：线上 uvicorn 跑 --workers 2，进度若只存进程内存字典，
# 分析任务跑在 worker A、前端轮询命中 worker B 就读不到 → 进度空白。故把运行态
# 落到 app_config（SQLite，所有 worker 共享）。下面的代理对象保持与普通 dict 完全
# 相同的接口（``[slug]=``、``.get``、``.items``、``.pop``、``in``），现有调用点零改动。
_TASK_CFG_PREFIX = "research:job:"
# 终态（done/error）记录保留时长：供前端最后几次轮询读到结果，过期自动清理。
_TASK_TERMINAL_TTL = 600  # 秒
# running 僵尸超时：进程崩溃/重启会把 running 记录留在 DB，新进程读到就永远
# already_running、任务无法重启。正常任务每步都会刷新 updated_at（最慢一步=慢模型
# 单次 300s 超时），故超过该阈值未更新即判定为僵尸 worker，清理放行。
_TASK_RUNNING_STALE_TTL = int(os.getenv("QF_RESEARCH_STALE_TTL") or 900)  # 秒
# 并行上限：同一时间最多几个产业链精读在跑。默认 **1=串行**：单任务要把上万篇研报
# 正文 load 进内存做 MAP，多个并行会叠加内存(线上已被 OOM 杀过 worker)、并一起砸单
# LLM 号触发 529 风暴。改为串行排队——一个跑完下一个自动顶上。可经 env 覆盖。
_RESEARCH_MAX_CONCURRENT = int(os.getenv("QF_RESEARCH_MAX_CONCURRENT") or 1)
# 等待队列上限：串行后请求改排队，最多挂这么多个，满了拒绝。0=不限(可无限排队)。
_RESEARCH_MAX_QUEUE = int(os.getenv("QF_RESEARCH_MAX_QUEUE") or 0)
# 单任务精读篇数硬上限：read_limit=0(全部)时也不超过它。上万篇会把单进程吃到 OOM、
# 且 ETA 长达数小时超过僵尸阈值。0=不限(不建议)。可经 QF_RESEARCH_MAX_REPORTS 覆盖。
_RESEARCH_MAX_REPORTS = int(os.getenv("QF_RESEARCH_MAX_REPORTS") or 5000)
# 返回内存的研报正文截断长度：MAP 逐篇只用前 2800 字，全文仍存 .txt/DB。给 200 字余量。
_MAP_TEXT_CHARS = int(os.getenv("QF_MAP_TEXT_CHARS") or 3000)

# ── 任务中断（协作式取消，跨 worker）────────────────────────────────────────────
# 后台分析跑在某个 worker 的事件循环里，取消请求可能命中另一个 worker，故不能直接
# 持 asyncio.Task 句柄 cancel。改用 app_config 里一个共享的「取消标志」：被取消的任务
# 在每个检查点(upd / MAP 每批开头)读这个标志，命中就抛 _AnalysisCancelled 干净退出。
_TASK_CANCEL_PREFIX = "research:cancel:"

# ── 失败记录（持久，跨 worker）─────────────────────────────────────────────────
# 任务失败时只在 _RUNNING_TASKS 写 error 终态——但那是 running 态表、600s 后自愈清掉，
# 且 saved_reports() 只 glob 文件，于是「生成记录」里失败的那次会静默消失、用户无从
# 得知为何没出报告。改用单独的持久前缀记录失败原因（不写主 task 文件，避免覆盖历史里
# 那份好报告，与「取消」的处理一致）；下次同 slug 跑成功后由 _clear_failure 清除。
_TASK_FAILED_PREFIX = "research:failed:"


def _record_failure(slug: str, keyword: str, error: str, stage: str = "") -> None:
    """持久化一条失败记录，供「生成记录」展示原因及失败阶段。"""
    from quantforge.data.storage import db_cache
    try:
        db_cache.app_config_set(
            f"{_TASK_FAILED_PREFIX}{slug}",
            json.dumps({"slug": slug, "keyword": keyword, "error": error,
                        "stage": stage, "failed_at": datetime.now().isoformat()},
                       ensure_ascii=False),
        )
    except Exception as exc:
        logger.debug(f"_record_failure {slug} failed: {exc}")


def _clear_failure(slug: str) -> None:
    from quantforge.data.storage import db_cache
    try:
        db_cache.app_config_delete(f"{_TASK_FAILED_PREFIX}{slug}")
    except Exception:
        pass


def _all_failures() -> dict[str, dict]:
    """slug -> 失败记录 dict。"""
    from quantforge.data.storage import db_cache
    out: dict[str, dict] = {}
    try:
        for k, raw in db_cache.app_config_prefix(_TASK_FAILED_PREFIX).items():
            slug = k[len(_TASK_FAILED_PREFIX):]
            try:
                out[slug] = json.loads(raw)
            except Exception:
                continue
    except Exception as exc:
        logger.debug(f"_all_failures read failed: {exc}")
    return out


class _AnalysisCancelled(BaseException):
    """用户主动中断产业链分析（区别于真正的失败）。

    刻意继承 BaseException（与 asyncio.CancelledError 同源）而非 Exception：
    `_run_keyword_analysis` 里散布着大量 `try/except Exception`（REDUCE 解析降级、
    各处行情回填兜底…），若是普通 Exception 会被它们吞掉、把中断变成「降级后照常
    保存」。继承 BaseException 才能穿过这些 except、直达外层的 `except _AnalysisCancelled`。
    """


def _request_cancel(slug: str) -> None:
    """置位取消标志（任一 worker 调用即可，跑任务的 worker 会在下个检查点读到）。"""
    from quantforge.data.storage import db_cache
    try:
        db_cache.app_config_set(f"{_TASK_CANCEL_PREFIX}{slug}", datetime.now().isoformat())
    except Exception as exc:
        logger.debug(f"_request_cancel {slug} failed: {exc}")


def _is_cancel_requested(slug: str) -> bool:
    from quantforge.data.storage import db_cache
    try:
        return bool(db_cache.app_config_get(f"{_TASK_CANCEL_PREFIX}{slug}"))
    except Exception:
        return False


def _clear_cancel(slug: str) -> None:
    from quantforge.data.storage import db_cache
    try:
        db_cache.app_config_delete(f"{_TASK_CANCEL_PREFIX}{slug}")
    except Exception:
        pass


async def _cancellable(slug: str, awaitable, poll: float = 2.0):
    """await 单个协程，但每 ``poll`` 秒探一次取消标志；命中即 cancel 它并抛
    _AnalysisCancelled。用于包住 seed/收集/下载/MAP 这些「单段长 await、中间无检查点」
    的步骤，让中断在任何阶段都能 ~poll 秒内生效，而非干等整段返回。

    注：被包的若是 asyncio.to_thread，cancel 只会让 await 端抛出，底层线程仍会自行
    跑完（无法强杀），但任务已就此退出，孤儿线程跑完即无害。
    """
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=poll)
            if task in done:
                return task.result()
            if _is_cancel_requested(slug):
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
                raise _AnalysisCancelled()
    except asyncio.CancelledError:
        task.cancel()
        raise


async def _cancellable_gather(slug: str, *coros, poll: float = 2.0, **kwargs):
    """像 asyncio.gather 一样并发若干协程，但每 ``poll`` 秒探一次取消标志。

    一旦命中取消：真正 cancel 在飞的 gather（cancellation 会传播进在途的 LLM/HTTP
    调用），随即抛 _AnalysisCancelled。用于 REDUCE 这类「单次 gather 数分钟、中间无
    其它检查点」的长 await 段，让中断在 ~poll 秒内生效，而不是干等整段跑完。
    """
    task = asyncio.ensure_future(asyncio.gather(*coros, **kwargs))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=poll)
            if task in done:
                return task.result()
            if _is_cancel_requested(slug):
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
                raise _AnalysisCancelled()
    except asyncio.CancelledError:
        task.cancel()
        raise


# REDUCE 并发闸门：合成阶段一次发 8 路重型 LLM 调用（A~H），若无上限地同时打单
# LLM 号（生产 MiniMax 单扛），会触发与 MAP 同款的 529 过载风暴——多路轮流 529、退避
# 重试自我放大，最终大面积失败 → result 收不到几路 → 落「AI 解析失败」降级空壳报告，
# 即用户看到的「断」。这里用一个**模块级共享** Semaphore 把 REDUCE 限到 _REDUCE_CONC
# 路一波（默认 3，与 QF_MAP_CONC 对齐）；跨并行任务也共享，最坏并发受控。
_REDUCE_CONC = int(os.getenv("QF_REDUCE_CONC") or 3)
_REDUCE_SEM: asyncio.Semaphore | None = None


def _reduce_sem() -> asyncio.Semaphore:
    """惰性创建 REDUCE 并发信号量（须在运行的事件循环内首次取用）。"""
    global _REDUCE_SEM
    if _REDUCE_SEM is None:
        _REDUCE_SEM = asyncio.Semaphore(_REDUCE_CONC)
    return _REDUCE_SEM


async def _reduce_bounded(coro, heartbeat=None):
    """用 REDUCE 信号量限流地 await 一个合成协程，避免八路一把砸单号。

    ``heartbeat`` 在抢到槽位、真正开跑前调用一次（刷新任务 updated_at）：八路分波后
    单次合成段墙钟会拉长，分波心跳可避免任务在 MAP→REDUCE 间被僵尸 TTL 误判清理。
    心跳里**不做**取消检查/抛异常（取消由外层 _cancellable_gather 每 2s 轮询负责），
    以免把一路合成的失败混进 return_exceptions 结果。
    """
    async with _reduce_sem():
        if heartbeat:
            try:
                heartbeat()
            except Exception:
                pass
        return await coro


def _research_provider() -> str | None:
    """产业链精读的主 provider（后台 research_provider 配置）。

    设为 "claude-code" 时，合成(REDUCE)走本地 Claude Code(Opus 4.8)；本机不可用
    （如服务器无 claude 二进制）时 chat() 自动跌回 HTTP 链。空=用全局链。
    """
    from quantforge.api.ai_client import get_research_provider
    return get_research_provider()


def _admission_check(slug: str) -> dict | None:
    """并行准入：本 slug 已在跑→already_running；并发已满→busy；否则放行(None)。

    返回非 None 时即为应直接回给前端的拒绝响应。跨 worker 一致（读 DB 共享态）。
    """
    running = _RUNNING_TASKS.get(slug)
    if running and running.get("status") == "running":
        ts = running.get("updated_at")
        try:
            stale = ts and (datetime.now() - datetime.fromisoformat(ts)).total_seconds() > _TASK_RUNNING_STALE_TTL
        except Exception:
            stale = False
        if stale:
            # 死 worker 残留：清掉僵尸记录并放行（否则该 slug 永远无法重启）。
            logger.warning(f"research job '{slug}' stale on admission, clearing zombie and re-admitting")
            _RUNNING_TASKS.pop(slug, None)
        else:
            return {"status": "already_running", "slug": slug,
                    "message": "该关键词分析正在进行中"}
    active = _RUNNING_TASKS.running_items()
    if len([1 for s, _ in active if s != slug]) >= _RESEARCH_MAX_CONCURRENT:
        kws = "、".join(t.get("keyword", "") for s, t in active if s != slug)
        return {"status": "busy", "slug": slug, "running_count": len(active),
                "max_concurrent": _RESEARCH_MAX_CONCURRENT,
                "message": f"已达并行上限（{_RESEARCH_MAX_CONCURRENT} 个）：{kws}，请等其中一个完成后再启动"}
    return None
# 只持久化轻量进度字段（完整 result/reports 很大、且完成后由 _load_task 从文件读，
# 不进 DB，避免 app_config 膨胀）。
_TASK_PERSIST_FIELDS = {
    "status", "slug", "keyword", "stage", "progress", "report_count", "pdf_count",
    "read_total", "read_done", "pdf_done", "pdf_total", "eta_seconds", "eta_text",
    "updated_at", "error",
    # 任务开始时间（前端据此跑「已用时」计时器）
    "started_at",
    # MAP 阶段细化：缓存命中篇数 / MAP 需处理总篇数 / MAP 已完成篇数
    "cached_count", "map_total", "map_done",
    # 调研纪要（blog 收集阶段）篇数
    "n_blog",
}


class _DbBackedTasks:
    """app_config 支持的运行态进度表，接口兼容 dict。

    写入时只挑 ``_TASK_PERSIST_FIELDS`` 落库（瘦身）；``running`` 状态才保留，
    ``done``/``error`` 终态写入后由调用方/清理逻辑负责删除（终态结果走文件缓存）。
    """

    @staticmethod
    def _key(slug: str) -> str:
        return f"{_TASK_CFG_PREFIX}{slug}"

    def __setitem__(self, slug: str, value: dict) -> None:
        from quantforge.data.storage import db_cache
        slim = {k: value.get(k) for k in _TASK_PERSIST_FIELDS if k in value}
        slim.setdefault("slug", slug)
        try:
            db_cache.app_config_set(self._key(slug), json.dumps(slim, ensure_ascii=False))
        except Exception as exc:
            logger.debug(f"_DbBackedTasks set {slug} failed: {exc}")

    def get(self, slug: str, default=None):
        from quantforge.data.storage import db_cache
        raw = db_cache.app_config_get(self._key(slug))
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    def __getitem__(self, slug: str):
        v = self.get(slug)
        if v is None:
            raise KeyError(slug)
        return v

    def __contains__(self, slug: str) -> bool:
        return self.get(slug) is not None

    def items(self):
        """遍历全部任务记录（含终态）。注意：判定「正在跑」请显式过滤
        ``status == 'running'``——终态记录会保留一小段时间供 status 轮询读取。"""
        from quantforge.data.storage import db_cache
        out = []
        for k, raw in db_cache.app_config_prefix(_TASK_CFG_PREFIX).items():
            slug = k[len(_TASK_CFG_PREFIX):]
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            # 自愈清理：终态（done/error/cancelled）留存超过 _TASK_TERMINAL_TTL 秒即删除，
            # 防止僵尸记录堆积、污染并行闸门计数。
            if rec.get("status") in ("done", "error", "cancelled"):
                ts = rec.get("updated_at")
                if ts and (datetime.now() - datetime.fromisoformat(ts)).total_seconds() > _TASK_TERMINAL_TTL:
                    db_cache.app_config_delete(k)
                    continue
            # running 僵尸自愈：进程崩溃/重启后 running 记录会残留，长时间不再刷新
            # updated_at。超过 _TASK_RUNNING_STALE_TTL 即视为死 worker，删除放行，
            # 否则该 slug 永远 already_running、无法重启。
            elif rec.get("status") == "running":
                ts = rec.get("updated_at")
                try:
                    stale = ts and (datetime.now() - datetime.fromisoformat(ts)).total_seconds() > _TASK_RUNNING_STALE_TTL
                except Exception:
                    stale = False
                if stale:
                    logger.warning(f"research job '{slug}' stale (no update > {_TASK_RUNNING_STALE_TTL}s), clearing zombie record")
                    db_cache.app_config_delete(k)
                    continue
            out.append((slug, rec))
        return out

    def running_items(self):
        """仅返回 status == 'running' 的任务。"""
        return [(s, t) for s, t in self.items() if t.get("status") == "running"]

    def pop(self, slug: str, default=None):
        from quantforge.data.storage import db_cache
        cur = self.get(slug, default)
        db_cache.app_config_delete(self._key(slug))
        return cur


_RUNNING_TASKS = _DbBackedTasks()  # slug -> 轻量进度 dict（DB 共享，跨 worker）


# ── 手动触发的「等待队列」 ────────────────────────────────────────────────────
# 需求：除每日定时任务外，管理员手动触发的分析若超出并发上限不再被直接拒绝，
# 而是排进队列；有空闲名额时由 research_queue_worker 自动「跑完一个接下一个」。
# 队列落 app_config（SQLite，跨 worker 共享），与运行态同源、可跨设备查看。
_QUEUE_CFG_KEY = "research:queue"


def _get_queue() -> list[dict]:
    """读取等待队列（顺序即排队次序）。"""
    from quantforge.data.storage import db_cache

    raw = db_cache.app_config_get(_QUEUE_CFG_KEY)
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _set_queue(items: list[dict]) -> None:
    from quantforge.data.storage import db_cache

    db_cache.app_config_set(_QUEUE_CFG_KEY, json.dumps(items, ensure_ascii=False))


def _enqueue(keyword: str, read_limit: int = 0,
             keywords: list[str] | None = None) -> dict:
    """把分析加入等待队列（已在队列里则不重复）。返回给前端的响应。

    keyword 为主题名称；keywords 为检索关键词清单（多关键词主题随队列项一并保存，
    出队开跑时按此检索）。
    """
    slug = _slug(keyword)
    q = _get_queue()
    slugs = [it.get("slug") for it in q]
    if slug in slugs:
        return {"status": "already_queued", "slug": slug, "keyword": keyword,
                "queue_pos": slugs.index(slug) + 1,
                "message": f"「{keyword}」已在排队中（第 {slugs.index(slug) + 1} 位）"}
    if _RESEARCH_MAX_QUEUE > 0 and len(q) >= _RESEARCH_MAX_QUEUE:
        return {"status": "queue_full", "slug": slug, "keyword": keyword,
                "queue_len": len(q), "max_queue": _RESEARCH_MAX_QUEUE,
                "message": f"排队已满（{_RESEARCH_MAX_QUEUE} 个），请等队列消化后再试"}
    item = {"slug": slug, "keyword": keyword, "read_limit": int(read_limit or 0),
            "enqueued_at": datetime.now().isoformat()}
    if keywords:
        item["keywords"] = keywords
    q.append(item)
    _set_queue(q)
    return {"status": "queued", "slug": slug, "keyword": keyword, "queue_pos": len(q),
            "message": f"已加入排队队列（第 {len(q)} 位），有空闲名额时自动开始"}


def _dequeue(slug: str) -> bool:
    """从等待队列移除某 slug；移除成功返回 True。"""
    q = _get_queue()
    nxt = [it for it in q if it.get("slug") != slug]
    if len(nxt) != len(q):
        _set_queue(nxt)
        return True
    return False


def _move_in_queue(slug: str, direction: str) -> dict:
    """调整队列中某项的优先级（排队次序）。

    direction：``up`` 上移一位 / ``down`` 下移一位 / ``top`` 置顶 / ``bottom`` 置底。
    队首即下一个开跑，故「置顶」=最高优先级。返回新位置（1 基）。
    """
    q = _get_queue()
    idx = next((i for i, it in enumerate(q) if it.get("slug") == slug), -1)
    if idx < 0:
        return {"status": "not_found", "slug": slug, "message": "队列中没有该任务"}
    item = q.pop(idx)
    if direction == "up":
        new_idx = max(0, idx - 1)
    elif direction == "down":
        new_idx = min(len(q), idx + 1)
    elif direction == "top":
        new_idx = 0
    elif direction == "bottom":
        new_idx = len(q)
    else:
        q.insert(idx, item)  # 还原
        return {"status": "bad_direction", "slug": slug, "message": "无效的移动方向"}
    q.insert(new_idx, item)
    _set_queue(q)
    return {"status": "moved", "slug": slug, "keyword": item.get("keyword", ""),
            "position": new_idx + 1, "queue_len": len(q)}


# ── 命名产业链分析（多关键词主题）注册表 ──────────────────────────────────────
# 一个分析可取一个名字 + 多个关键词，所有关键词都作为检索材料。主题定义落 app_config
# （跨 worker 共享），供重跑（重试/队列/定时）按 slug 还原关键词清单。
_TOPICS_CFG_KEY = "research:topics"


def _get_topics() -> dict:
    from quantforge.data.storage import db_cache

    raw = db_cache.app_config_get(_TOPICS_CFG_KEY)
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _get_topic(slug: str) -> dict | None:
    return _get_topics().get(slug)


def _save_topic(name: str, keywords: list[str], read_limit: int = 0) -> dict:
    """登记/更新一个命名主题；返回 {slug,name,keywords,read_limit}。名称缺省取首个关键词。"""
    from quantforge.data.storage import db_cache

    name = (name or "").strip()
    kws, seen = [], set()
    for k in (keywords or []):
        k = (k or "").strip()
        if k and k not in seen:
            seen.add(k); kws.append(k)
    if not name:
        name = kws[0] if kws else ""
    slug = _slug(name)
    topics = _get_topics()
    topics[slug] = {"slug": slug, "name": name, "keywords": kws,
                    "read_limit": int(read_limit or 0),
                    "updated_at": datetime.now().isoformat()}
    db_cache.app_config_set(_TOPICS_CFG_KEY, json.dumps(topics, ensure_ascii=False))
    return topics[slug]


def _delete_topic(slug: str) -> None:
    from quantforge.data.storage import db_cache

    topics = _get_topics()
    if slug in topics:
        topics.pop(slug, None)
        db_cache.app_config_set(_TOPICS_CFG_KEY, json.dumps(topics, ensure_ascii=False))


async def research_queue_worker() -> None:
    """后台循环：有空闲并发名额时，从等待队列取队首开跑（跑完接着补位）。

    与每日定时任务相互独立——定时任务按时刻表串行错开，本队列服务管理员临时手动触发。
    串行补位至并发上限 ``_RESEARCH_MAX_CONCURRENT``；任务结束让出名额后下一个自动顶上。
    依赖运行态/队列均落 DB（跨 worker 共享）；双 worker 同时补位时靠 ``_admission_check``
    与运行记录幂等兜底（最坏一次重复启动会被 already_running 挡掉）。
    """
    import asyncio

    logger.info("research.research_queue_worker: starting")
    while True:
        try:
            q = _get_queue()
            if q:
                while True:
                    q = _get_queue()
                    if not q:
                        break
                    active = _RUNNING_TASKS.running_items()
                    if len(active) >= _RESEARCH_MAX_CONCURRENT:
                        break  # 名额已满，等下轮
                    item = q[0]
                    slug = item.get("slug")
                    kw = item.get("keyword") or ""
                    rejected = _admission_check(slug)
                    if rejected and rejected.get("status") == "busy":
                        break  # 名额被别处占了，下轮再来
                    # already_running 或可放行：都从队列出队（已在跑的无需再排）
                    _dequeue(slug)
                    if rejected and rejected.get("status") == "already_running":
                        continue
                    _RUNNING_TASKS[slug] = {
                        "status": "running", "slug": slug, "keyword": kw,
                        "stage": "排队就绪·初始化", "progress": 2,
                        "started_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                    }
                    logger.info(f"research queue: starting '{kw}' (queue had {len(q)})")
                    asyncio.create_task(
                        _run_keyword_analysis(kw, int(item.get("read_limit") or 0),
                                              keywords=item.get("keywords")))
        except Exception as e:
            logger.warning(f"research queue worker error: {e}")
        await asyncio.sleep(5)

# 预定义的热门概念/产业链
_PRESET_TOPICS = {
    "humanoid_robot": {
        "name": "人形机器人",
        "concepts": ["机器人", "工业4.0", "减速器", "伺服系统"],
        "default_stocks": ["300024", "300008", "002008", "002176", "603666"],
        "tabs": ["overview", "cost", "reducer", "ballscrew", "motor", "sensor", "material", "risk", "valuation"]
    },
    "solid_state_battery": {
        "name": "固态电池",
        "concepts": ["固态电池", "锂电池", "储能"],
        "default_stocks": ["002812", "300750", "600030", "002460"],
        "tabs": ["overview", "cost", "material", "electrolyte", "cathode", "anode", "risk", "valuation"]
    },
    "ai_chip": {
        "name": "AI芯片",
        "concepts": ["AI芯片", "芯片设计", "算力", "GPU"],
        "default_stocks": ["600584", "002230", "300661", "002049"],
        "tabs": ["overview", "cost", "design", "manufacturing", "packaging", "material", "risk", "valuation"]
    },
    "auto_intelligence": {
        "name": "智能驾驶",
        "concepts": ["智能驾驶", "自动驾驶", "新能源车"],
        "default_stocks": ["002594", "300750", "601012", "002230"],
        "tabs": ["overview", "cost", "sensing", "decision", "actuation", "material", "risk", "valuation"]
    },
    "custom": {
        "name": "自定义主题",
        "concepts": [],
        "default_stocks": [],
        "tabs": ["overview", "cost", "risk", "valuation"]
    }
}

# 研报本地缓存新鲜度：研报更新慢，6 小时足够
_REPORTS_TTL = 6 * 3600


async def fetch_and_store_reports(code: str, max_pages: int = 10, page_size: int = 100) -> list[dict]:
    """拉取并入库研报；返回入库后的本地记录（统一字段）。"""
    from quantforge.data.storage import db_cache
    raw = await asyncio.to_thread(_eastmoney_reports, code, max_pages, page_size)
    if raw:
        await asyncio.to_thread(_store_reports, code, raw)
    return db_cache.reports_get(code, limit=page_size)


@router.get("/reports/{code}")
async def get_reports(code: str, max_pages: int = 10, page_size: int = 100,
                      refresh: bool = False):
    """获取股票研报列表（本地缓存优先，6h 新鲜度；自动入库 stock_reports）。"""
    from quantforge.data.storage import db_cache
    code = code.strip()
    # sqlite 读放线程池，避免阻塞事件循环
    age = await asyncio.to_thread(db_cache.reports_latest_fetch_age, code)
    fresh = age is not None and age <= _REPORTS_TTL
    if fresh and not refresh:
        reports = await asyncio.to_thread(db_cache.reports_get, code, page_size)
        return {"code": code, "count": len(reports), "reports": reports, "cached": True}
    try:
        reports = await fetch_and_store_reports(code, max_pages, page_size)
        return {"code": code, "count": len(reports), "reports": reports, "cached": False}
    except Exception as e:
        logger.warning(f"get_reports {code} fetch failed: {e}")
        reports = await asyncio.to_thread(db_cache.reports_get, code, page_size)  # stale fallback
        return {"code": code, "count": len(reports), "reports": reports, "cached": True}


@router.get("/summary/{code}")
async def get_report_summary(code: str):
    """研报汇总：篇数/最新日期/评级分布/最新一致预期 EPS·PE（落库后展示）。"""
    from quantforge.data.storage import db_cache
    code = code.strip()
    if await asyncio.to_thread(db_cache.reports_latest_fetch_age, code) is None:
        # 库内尚无 → 拉一次入库（首屏触发预热）
        try:
            await fetch_and_store_reports(code, max_pages=5, page_size=100)
        except Exception as e:
            logger.debug(f"summary prefetch {code} failed: {e}")
    summary = await asyncio.to_thread(db_cache.reports_summary, code)
    return {"code": code, **summary}


# ── 机构荐股·投资逻辑/风险 AI 提炼（个股详情页）────────────────────────────────
# 基于该股已落库研报，让 LLM 提炼 3 条投资逻辑 + 3 条风险。结果按个股落盘缓存，
# 研报更新慢，给 24h 新鲜度，避免每次进详情页都打 LLM。
_THESIS_DIR = Path("data/cache/stock_thesis")
_THESIS_TTL = 24 * 3600

_THESIS_PROMPT = """你是资深券商分析师。下面给出某只 A 股的【机构荐股汇总数据】（评级分布、机构一致目标价与区间、相对现价的上涨空间、一致预期 EPS/PE）和【近一年机构研报清单】。
请**综合这两部分信息**，提炼出 **3 条投资逻辑（看多依据）** 和 **3 条风险提示**。要求：
- 每条一句话，具体、可据上述数据/研报佐证，不空泛、不杜撰数据中没有的数字；
- 投资逻辑要结合机构评级与目标价上涨空间（如多数机构买入/一致目标价较现价有 X% 空间）、业绩与估值（EPS/PE）、行业景气/份额卡位/催化剂；
- 风险聚焦：需求/竞争/政策/成本，以及估值层面（如现价已接近或超过一致目标价、PE 偏高=上涨空间有限/估值透支）。
仅返回**严格合法**的 JSON，不要多余文字、不要 markdown：
{"bull": ["逻辑1", "逻辑2", "逻辑3"], "bear": ["风险1", "风险2", "风险3"]}"""


def _thesis_path(code: str) -> Path:
    return _THESIS_DIR / f"{code}.json"


def _load_thesis_cache(code: str) -> dict | None:
    p = _thesis_path(code)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        ts = d.get("updated_at")
        if ts:
            age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
            if age <= _THESIS_TTL:
                return d
    except Exception:
        pass
    return None


def _save_thesis_cache(code: str, data: dict) -> None:
    try:
        _THESIS_DIR.mkdir(parents=True, exist_ok=True)
        _thesis_path(code).write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.debug(f"thesis cache save {code} failed: {e}")


@router.get("/thesis/{code}")
async def get_stock_thesis(code: str, refresh: bool = False):
    """机构荐股·投资逻辑(3)/风险(3)：基于落库研报 AI 提炼，24h 缓存。"""
    from quantforge.data.storage import db_cache
    code = code.strip()

    if not refresh:
        cached = await asyncio.to_thread(_load_thesis_cache, code)
        if cached:
            return {"code": code, "bull": cached.get("bull", []),
                    "bear": cached.get("bear", []), "cached": True}

    # 库内无研报则先拉一次（与 summary 同步策略一致）
    if await asyncio.to_thread(db_cache.reports_latest_fetch_age, code) is None:
        try:
            await fetch_and_store_reports(code, max_pages=5, page_size=100)
        except Exception as e:
            logger.debug(f"thesis prefetch {code} failed: {e}")

    reps = await asyncio.to_thread(db_cache.reports_get, code, 40)
    if not reps:
        return {"code": code, "bull": [], "bear": [], "cached": False}

    # ① 机构荐股结构化汇总（评级分布 / 一致目标价区间 / 一致预期 EPS·PE）
    summary = await asyncio.to_thread(db_cache.reports_summary, code)
    # ② 现价（用于算上涨空间，让 AI 判断估值是否透支）
    price = None
    try:
        from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
        q = await asyncio.to_thread(_tencent_quote, [_normalize_code(code)])
        price = (next(iter(q.values()), {}) or {}).get("price")
    except Exception as e:
        logger.debug(f"thesis {code} quote failed: {e}")

    parts: list[str] = ["【机构荐股汇总数据】"]
    if summary.get("ratings"):
        parts.append("评级分布：" + "、".join(f"{k} {v}家" for k, v in summary["ratings"].items()))
    tgt = summary.get("target")
    if tgt:
        upside = (f"，较现价 {price} 的上涨空间约 {round((tgt['avg'] - price) / price * 100, 1)}%"
                  if price else "")
        parts.append(f"机构一致目标价：{tgt['avg']}（区间 {tgt['low']}~{tgt['high']}，{tgt['count']} 家近半年）{upside}")
    elif price:
        parts.append(f"当前价：{price}（机构暂无有效目标价）")
    eps_pe = []
    if summary.get("eps_this") is not None:
        eps_pe.append(f"今年 EPS {summary['eps_this']}/PE {summary.get('pe_this')}")
    if summary.get("eps_next") is not None:
        eps_pe.append(f"明年 EPS {summary['eps_next']}/PE {summary.get('pe_next')}")
    if summary.get("eps_next2") is not None:
        eps_pe.append(f"后年 EPS {summary['eps_next2']}/PE {summary.get('pe_next2')}")
    if eps_pe:
        parts.append("一致预期：" + "；".join(eps_pe))

    parts.append("\n【近一年机构研报清单】")
    for r in reps[:40]:
        tp = r.get("target_price")
        parts.append(
            f"[{r.get('publish_date','')}] {r.get('org','')} | "
            f"{r.get('rating','')}{f' 目标价{tp}' if tp else ''} | {r.get('title','')}"
        )
    user = "\n".join(parts)

    try:
        data = await _chat_json(_THESIS_PROMPT, user, 1024, "stock_thesis", retries=1)
        bull = [str(x).strip() for x in (data.get("bull") or []) if str(x).strip()][:3]
        bear = [str(x).strip() for x in (data.get("bear") or []) if str(x).strip()][:3]
    except Exception as e:
        logger.warning(f"thesis {code} AI failed: {e}")
        return {"code": code, "bull": [], "bear": [], "cached": False, "error": "ai_failed"}

    result = {"bull": bull, "bear": bear, "updated_at": datetime.now().isoformat()}
    await asyncio.to_thread(_save_thesis_cache, code, result)
    return {"code": code, "bull": bull, "bear": bear, "cached": False}


async def prewarm_watchlist_reports() -> int:
    """提前把所有自选股的研报拉到本地库（每日级别即可）。"""
    from quantforge.data.storage import db_cache
    codes = await asyncio.to_thread(db_cache.watchlist_all_codes)
    if not codes:
        return 0
    sem = asyncio.Semaphore(4)

    async def _one(c: str):
        async with sem:
            age = db_cache.reports_latest_fetch_age(c)
            if age is not None and age <= _REPORTS_TTL:
                return
            try:
                await fetch_and_store_reports(c, max_pages=5, page_size=100)
            except Exception:
                pass

    await asyncio.gather(*[_one(c) for c in codes])
    return len(codes)


async def watchlist_report_warmer() -> None:
    """后台循环：周期性预热自选股研报（每 6 小时）。"""
    logger.info("research.watchlist_report_warmer: starting watchlist report prewarmer")
    while True:
        try:
            n = await prewarm_watchlist_reports()
            if n:
                logger.info(f"watchlist report warmer: prewarmed {n} codes")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"watchlist report warmer error: {e}")
        await asyncio.sleep(_REPORTS_TTL)


# ── 全市场研报全量/增量同步（近一年）──────────────────────────────────────────
# 东财 reportapi 可不按个股、直接全市场翻页（code 空 / industryCode=*）。近一年
# 个股研报约 1.5 万篇 / 行业研报约 1.8 万篇，分别 ~150 / ~180 页，单页 ~0.6s，
# 配合限速整轮几分钟可拉完。每日只需从库内最新日期回拉几天做增量。

async def sync_all_reports(lookback_days: int = _REPORT_LOOKBACK_DAYS,
                           incremental_days: int = 7,
                           full: bool = False) -> dict:
    """全市场研报入库（个股 qType=0 + 行业 qType=1）。

    - full=True 或库为空：拉近 ``lookback_days`` 天（首灌/全量）。
    - 否则增量：从库内最新日期回拉 ``incremental_days`` 天（覆盖滞后发布的研报）。
    入库走 upsert，重复天数不会产生重复行。
    """
    from quantforge.data.storage import db_cache

    have_stock = await asyncio.to_thread(db_cache.reports_total_count)
    have_ind = await asyncio.to_thread(db_cache.industry_reports_total_count)
    is_full = full or (have_stock == 0 and have_ind == 0)

    if is_full:
        begin = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    else:
        latest = await asyncio.to_thread(db_cache.reports_global_latest_date)
        ind_latest = await asyncio.to_thread(db_cache.industry_reports_latest_date)
        anchor = min([d for d in (latest, ind_latest) if d] or [None]) \
            or (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        try:
            begin = (datetime.strptime(anchor, "%Y-%m-%d")
                     - timedelta(days=incremental_days)).strftime("%Y-%m-%d")
        except ValueError:
            begin = (datetime.now() - timedelta(days=incremental_days)).strftime("%Y-%m-%d")

    logger.info(f"sync_all_reports: {'FULL' if is_full else 'incremental'} from {begin}")
    raw_stock, raw_ind = await asyncio.gather(
        asyncio.to_thread(_fetch_all_reports_pages, "0", begin),
        asyncio.to_thread(_fetch_all_reports_pages, "1", begin),
    )
    n_stock = await asyncio.to_thread(_store_stock_reports, raw_stock)
    n_ind = await asyncio.to_thread(_store_industry_reports, raw_ind)
    result = {"mode": "full" if is_full else "incremental", "begin": begin,
              "fetched_stock": len(raw_stock), "fetched_industry": len(raw_ind),
              "stored_stock": n_stock, "stored_industry": n_ind}
    logger.info(f"sync_all_reports done: {result}")
    return result


def _seconds_until_next_run(hour: int = 18, minute: int = 30) -> float:
    """距下一个 ``hour:minute``（默认 18:30，收盘后）的秒数。"""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def report_sync_scheduler() -> None:
    """后台调度：开机若库空则补全量首灌，之后**每小时**增量同步新研报。

    「研报」板块要求每小时刷新，故由每日 18:30 改为每小时一轮增量（间隔可经
    QF_REPORT_SYNC_INTERVAL_HOURS 调整，默认 1 小时）。增量只从库内最新日期回拉
    几天、走 to_thread 不阻塞事件循环，重复天数 upsert 不产生重复行。

    默认关闭，需 QF_ENABLE_REPORT_SYNC=1 开启（东财 reportapi 在本环境间歇被劫持，
    由运维确认网络可达后再开）。
    """
    logger.info("research.report_sync_scheduler: started (hourly incremental)")
    interval = max(0.25, float(os.getenv("QF_REPORT_SYNC_INTERVAL_HOURS") or 1)) * 3600
    # 开机首灌：库空时拉近一年全量，避免分析读库时无数据
    try:
        from quantforge.data.storage import db_cache
        if await asyncio.to_thread(db_cache.reports_total_count) == 0:
            await sync_all_reports(full=True)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"report_sync_scheduler initial full sync error: {e}")

    while True:
        try:
            await asyncio.sleep(interval)
            await sync_all_reports()  # 增量
            # 顺手清理过期的 MAP facts 缓存（研报一年滚动，facts 同步过期）
            try:
                from quantforge.data.storage import db_cache
                await asyncio.to_thread(db_cache.report_facts_purge, 400)
            except Exception as e:
                logger.debug(f"report_facts_purge skipped: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"report_sync_scheduler incremental sync error: {e}")
            await asyncio.sleep(600)  # 出错后 10min 再试，避免空转


@router.post("/sync-reports")
async def trigger_report_sync(background_tasks: BackgroundTasks, full: bool = False):
    """手动触发全市场研报入库（后台执行）。full=true 强制近一年全量。"""
    background_tasks.add_task(sync_all_reports, _REPORT_LOOKBACK_DAYS, 7, full)
    return {"status": "started", "mode": "full" if full else "incremental"}


@router.get("/sync-status")
async def report_sync_status():
    """研报库状态：个股/行业篇数 + 最新日期。"""
    from quantforge.data.storage import db_cache
    return {
        "stock_count": await asyncio.to_thread(db_cache.reports_total_count),
        "stock_latest": await asyncio.to_thread(db_cache.reports_global_latest_date),
        "industry_count": await asyncio.to_thread(db_cache.industry_reports_total_count),
        "industry_latest": await asyncio.to_thread(db_cache.industry_reports_latest_date),
    }


@router.get("/map-cache-stats")
async def map_cache_stats():
    """研报 MAP 抽取缓存的模型分布：共多少篇研报已被抽取、各由哪个模型读的。

    供管理后台可视化复用情况（命中即免重跑省 token）。
    """
    from quantforge.data.storage import db_cache
    return await asyncio.to_thread(db_cache.report_facts_stats)


@router.get("/all-reports")
async def list_all_reports(kind: str = "stock", page: int = 1, page_size: int = 30,
                           search: str | None = None, days: int | None = None,
                           rating: str | None = None):
    """全市场研报通览（供「研报」板块）：分页读库，kind=stock|industry。

    个股研报随 PDF 下载地址一并返回；行业研报无个股归属。库由 report_sync_scheduler
    每小时增量入库（开机若空补近一年全量）。
    """
    from quantforge.data.storage import db_cache
    if kind == "industry":
        res = await asyncio.to_thread(db_cache.industry_reports_list, page, page_size, search, days)
    else:
        kind = "stock"
        res = await asyncio.to_thread(db_cache.reports_list, page, page_size, search, days, rating)
        for r in res.get("items", []):
            ic = r.get("info_code")
            if ic:
                r["pdf_url"] = PDF_TPL.format(info_code=ic)
    return {"kind": kind, **res}


@router.get("/pdf/{info_code}")
async def get_pdf_url(info_code: str):
    """获取研报PDF下载地址"""
    return {"info_code": info_code, "pdf_url": PDF_TPL.format(info_code=info_code)}

# ── 同花顺一致预期EPS ──
@router.get("/consensus/{code}")
async def get_consensus(code: str):
    """获取机构一致预期EPS"""
    def fetch():
        return _ths_consensus_eps(code)
    data = await asyncio.to_thread(fetch)
    return {"code": code, "consensus": data}

# ── 个股估值 ──
@router.get("/valuation/{code}")
async def get_valuation(code: str):
    """个股估值综合报告 — PE/PB/PEG/PE消化"""
    from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
    code_norm = _normalize_code(code)
    
    q = await asyncio.to_thread(_tencent_quote, [code_norm])
    quote = q.get(code_norm, {})
    
    reports = await asyncio.to_thread(_eastmoney_reports, code_norm, 2)
    
    eps_next = None
    eps_this = None
    for r in reports[:10]:
        if r.get("predictNextYearEps"):
            eps_next = float(r.get("predictNextYearEps"))
        if r.get("predictThisYearEps"):
            eps_this = float(r.get("predictThisYearEps"))
        if eps_next and eps_this:
            break
    
    price = quote.get("price", 0)
    pe_ttm = quote.get("pe_ttm", 0)
    
    peg = None
    pe_digest = None
    if eps_next and eps_this and eps_this > 0:
        growth = (eps_next - eps_this) / eps_this * 100
        if growth > 0:
            peg = pe_ttm / growth if growth != 0 else None
            pe_digest = f"{round(peg, 1)}年" if peg else None
    
    return {
        "code": code,
        "name": quote.get("name", ""),
        "price": price,
        "pe_ttm": pe_ttm,
        "pe_static": quote.get("pe_static", 0),
        "pb": quote.get("pb", 0),
        "mcap_yi": quote.get("mcap_yi", 0),
        "float_mcap_yi": quote.get("float_mcap_yi", 0),
        "limit_up": quote.get("limit_up", 0),
        "limit_down": quote.get("limit_down", 0),
        "consensus_eps_this": eps_this,
        "consensus_eps_next": eps_next,
        "peg": peg,
        "pe_digest_years": pe_digest,
    }

# ── 概念板块相关 API ──
@router.get("/topics")
def get_preset_topics():
    """获取预定义的主题/产业链列表"""
    return {
        "topics": [
            {"id": k, "name": v["name"], "concepts": v["concepts"]}
            for k, v in _PRESET_TOPICS.items()
        ]
    }

@router.get("/topic/{topic_id}")
def get_topic_detail(topic_id: str):
    """获取特定主题的详细信息"""
    topic = _PRESET_TOPICS.get(topic_id) or _PRESET_TOPICS.get("custom")
    return {
        "id": topic_id,
        "name": topic["name"],
        "concepts": topic["concepts"],
        "default_stocks": topic["default_stocks"],
        "tabs": topic.get("tabs", ["overview", "cost", "risk", "valuation"])
    }

@router.get("/concept/{concept_name}")
async def get_concept_stocks(concept_name: str):
    """获取概念板块的成分股列表"""
    def fetch():
        return _get_concept_stocks(concept_name)
    stocks = await asyncio.to_thread(fetch)
    return {"concept": concept_name, "count": len(stocks), "stocks": stocks}


# ── AI智能选股功能 ───────────────────────────────────────────────────────────
async def _ai_suggest_stocks(topic: str, sector: str = None, limit: int = 20) -> list[dict]:
    """使用AI分析推荐产业链相关股票
    
    Args:
        topic: 主题/产业链名称
        sector: 行业板块名称（可选）
        limit: 返回数量限制
    """
    try:
        # 1. 先从板块获取成分股
        sector_stocks = []
        if sector:
            try:
                import akshare as ak
                df = await asyncio.to_thread(ak.stock_board_industry_cons_em, sector)
                for _, row in df.iterrows():
                    try:
                        sector_stocks.append({
                            "code": str(row.iloc[1]),
                            "name": str(row.iloc[2]),
                            "price": float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                            "change_pct": float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                            "pe": float(row.iloc[14]) if len(row) > 14 and pd.notna(row.iloc[14]) else None,
                            "turnover_rate": float(row.iloc[13]) if len(row) > 13 and pd.notna(row.iloc[13]) else None,
                        })
                    except:
                        continue
                logger.info(f"Got {len(sector_stocks)} stocks from sector {sector}")
            except Exception as e:
                logger.warning(f"Failed to get sector stocks: {e}")
        
        # 2. 获取概念相关股票
        concept_stocks = await asyncio.to_thread(_get_concept_stocks, topic)
        
        # 3. 合并去重
        all_stocks_map = {}
        for s in concept_stocks:
            all_stocks_map[s["code"]] = s
        for s in sector_stocks:
            if s["code"] not in all_stocks_map:
                all_stocks_map[s["code"]] = s
        
        all_stocks = list(all_stocks_map.values())[:100]  # 最多100个用于AI分析
        
        if not all_stocks:
            return []
        
        # 4. 使用AI分析推荐最佳股票
        from quantforge.api.ai_client import chat
        
        stock_list_text = "\n".join([
            f"{s['code']} {s['name']} 现价:{s.get('price', 'N/A')} PE:{s.get('pe', 'N/A')} 换手:{s.get('turnover_rate', 'N/A')}%"
            for s in all_stocks[:50]
        ])
        
        prompt = f"""你是一位专业的股票分析师。请从以下{topic}产业链相关的股票中，筛选出最值得研究的股票。

股票列表：
{stock_list_text}

请分析并推荐不超过{limit}只最值得关注的股票，考虑因素：
1. 行业地位和市场份额
2. 估值合理性（PE、换手率）
3. 近期价格走势
4. 主营业务相关性

请以JSON格式返回：
{{
  "recommended": [
    {{"code": "股票代码", "name": "股票名称", "reason": "推荐理由", "priority": 1-5}},
    ...
  ],
  "summary": "整体分析总结（100字以内）"
}}

只返回JSON，不要其他文字。"""
        
        try:
            result_text = await chat(
                system="你是一位专业的股票分析师，擅长产业链研究和投资分析。",
                user=prompt,
                max_tokens=4096,
                caller="stock_suggestion"
            )
            
            # 解析JSON结果
            text = result_text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            if text.endswith("```"):
                text = text[:text.rfind("```")].strip()
            
            result = json.loads(text)
            recommended_codes = [s["code"] for s in result.get("recommended", [])]
            
            # 返回推荐的股票详细信息
            recommended_stocks = []
            for code in recommended_codes[:limit]:
                stock_info = all_stocks_map.get(code)
                if stock_info:
                    recommended_stocks.append(stock_info)
            
            return {
                "topic": topic,
                "sector": sector,
                "recommended": recommended_stocks,
                "all_count": len(all_stocks),
                "summary": result.get("summary", ""),
            }
        except Exception as e:
            logger.warning(f"AI analysis failed: {e}")
            # 如果AI失败，返回按换手率排序的股票
            sorted_stocks = sorted(
                [s for s in all_stocks if s.get("turnover_rate")],
                key=lambda x: x.get("turnover_rate", 0),
                reverse=True
            )[:limit]
            return {
                "topic": topic,
                "sector": sector,
                "recommended": sorted_stocks,
                "all_count": len(all_stocks),
                "summary": "按换手率排序推荐",
            }
            
    except Exception as e:
        logger.error(f"AI suggest stocks failed: {e}")
        return {"error": str(e), "recommended": [], "all_count": 0}


@router.get("/ai-suggest-stocks")
async def suggest_stocks(topic: str, sector: str = None, limit: int = 20):
    """AI智能推荐产业链相关股票
    
    Args:
        topic: 主题/产业链名称（如"人形机器人"、"固态电池"等）
        sector: 行业板块名称（可选，如"自动化设备"）
        limit: 返回数量限制（默认20）
    """
    result = await _ai_suggest_stocks(topic, sector, limit)
    return result


@router.get("/sectors")
async def get_all_sectors():
    """获取所有行业板块列表（用于选择）"""
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_name_em)
        sectors = []
        for _, row in df.iterrows():
            try:
                sectors.append({
                    "name": str(row.iloc[1]),
                    "code": str(row.iloc[2]),
                    "change_pct": float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                    "up_count": int(row.iloc[8]) if pd.notna(row.iloc[8]) else 0,
                    "down_count": int(row.iloc[9]) if pd.notna(row.iloc[9]) else 0,
                })
            except:
                continue
        # 按涨跌幅排序
        sectors.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        return {"sectors": sectors, "count": len(sectors)}
    except Exception as e:
        logger.error(f"Get sectors failed: {e}")
        return {"sectors": [], "count": 0, "error": str(e)}


@router.get("/sector-stocks/{sector_name}")
async def get_sector_stocks(sector_name: str):
    """获取指定行业板块的成分股
    
    Args:
        sector_name: 板块名称（如"自动化设备"）
    """
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_cons_em, sector_name)
        stocks = _normalise_cons_stocks(df)
        return {"sector": sector_name, "stocks": stocks, "count": len(stocks)}
    except Exception as e:
        logger.error(f"Get sector stocks failed: {e}")
        return {"sector": sector_name, "stocks": [], "count": 0, "error": str(e)}


@router.get("/stocks/quotes")
async def get_stock_quotes(codes: str):
    """批量获取股票实时报价"""
    from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
    code_list = [_normalize_code(c.strip()) for c in codes.split(",") if c.strip()]
    quotes = await asyncio.to_thread(_tencent_quote, code_list)
    return {"count": len(quotes), "quotes": quotes}

# ── AI分析任务系统 ──
def _task_path(topic: str) -> Path:
    return _TASKS_DIR / f"{topic}.json"

def _load_task(topic: str) -> dict | None:
    path = _task_path(topic)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None

def _save_task(topic: str, data: dict):
    try:
        _TASKS_DIR.mkdir(parents=True, exist_ok=True)
        _task_path(topic).write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"Task save failed for {topic}: {e}")


# ── 逐篇研报事实缓存（增量精读用）：{infoCode: fact} ──
def _facts_path(slug: str) -> Path:
    return _TASKS_DIR / f"{slug}_facts.json"


def _load_facts(slug: str) -> dict:
    p = _facts_path(slug)
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {}


def _save_facts(slug: str, facts: dict):
    try:
        _TASKS_DIR.mkdir(parents=True, exist_ok=True)
        _facts_path(slug).write_text(
            json.dumps(facts, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"Facts save failed for {slug}: {e}")

_INDUSTRY_ANALYSIS_PROMPT = """你是一位专业的产业链研究分析师，负责撰写深度行业研报。
请针对给定的产业链/概念主题进行深度分析。

分析要求：
1. 分析产业链上下游构成，识别关键环节
2. 分析当前行业发展阶段和未来趋势
3. 识别核心受益标的及投资逻辑
4. 提示投资风险和注意事项
5. 估算BOM成本构成

输入数据包括：
- 主题/概念名称
- 核心标的列表及其基本资料
- 相关机构研报摘要

请返回 JSON 格式分析报告，不要其他文字：
{
  "overview": "产业链整体分析（300字）",
  "market_size": "当前市场规模和增长预估",
  "key_players": ["核心标的1", "核心标的2"],
  "key_segments": [
    {
      "name": "环节名称",
      "importance": "高|中|低",
      "leader": "龙头公司",
      "description": "环节说明"
    }
  ],
  "bom": [
    {"name": "部件名称1", "percent": 35, "color": "#6366f1"},
    {"name": "部件名称2", "percent": 25, "color": "#3b82f6"},
    {"name": "部件名称3", "percent": 20, "color": "#06d6c8"},
    {"name": "部件名称4", "percent": 12, "color": "#f59e0b"},
    {"name": "其他", "percent": 8, "color": "#22d97a"}
  ],
  "risks": ["风险1", "风险2"],
  "summary": "投资建议（200字）"
}
"""

async def _run_industry_analysis(topic_id: str, custom_stocks: str = ""):
    """在后台执行产业链分析"""
    topic = _PRESET_TOPICS.get(topic_id) or _PRESET_TOPICS["custom"]
    
    # 1. 先通过主题名称搜索相关概念股票
    search_query = topic["name"]
    logger.info(f"Searching concept stocks for: {search_query}")
    
    concept_stocks = await asyncio.to_thread(_get_concept_stocks, search_query)
    logger.info(f"Found {len(concept_stocks)} concept stocks for {search_query}")
    
    # 2. 使用用户自定义股票，或者搜索到的股票，或者默认股票
    stock_codes = [s.strip() for s in custom_stocks.split(",") if s.strip()]
    if not stock_codes:
        if concept_stocks:
            stock_codes = [s["code"] for s in concept_stocks]  # 使用搜索到的股票
            logger.info(f"Using {len(stock_codes)} searched concept stocks")
        else:
            stock_codes = topic.get("default_stocks", [])
            logger.info(f"Using {len(stock_codes)} default stocks")
    
    # 3. 收集行情数据
    from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
    quotes = {}
    if stock_codes:
        codes_normalized = [_normalize_code(c) for c in stock_codes]
        quotes = await asyncio.to_thread(_tencent_quote, codes_normalized)
        logger.info(f"Got quotes for {len(quotes)} stocks")
    
    # 4. 收集研报（获取所有搜索到的股票的研报）
    reports_agg = []
    for code in stock_codes:
        try:
            reps = await asyncio.to_thread(_eastmoney_reports, code, max_pages=5, page_size=100)
            if reps:
                reports_agg.extend(reps)
                logger.info(f"Got {len(reps)} reports for {code}")
        except Exception as e:
            logger.warning(f"Failed to get reports for {code}: {e}")
    
    logger.info(f"Total reports collected: {len(reports_agg)}")
    
    # 构建提示词
    from quantforge.api.ai_client import chat
    user_parts = [
        f"分析主题：{topic['name']}",
        "核心标的（含行情数据）："
    ]
    for code, q in quotes.items():
        user_parts.append(f"{code} {q.get('name','')} 价格{q.get('price',0)} PE={q.get('pe_ttm',0)} PB={q.get('pb',0)}")
    
    user_parts.append("相关研报：")
    for r in reports_agg[:20]:
        user_parts.append(f"[{r.get('orgSName','')}] {r.get('title','')}")
    
    try:
        ai_text = await chat(
            system=_INDUSTRY_ANALYSIS_PROMPT,
            user="\n".join(user_parts),
            max_tokens=8192,
            caller="industry_research",
            provider=_research_provider(),
        )
        # 解析JSON
        text = ai_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        if text.endswith("```"):
            text = text[:text.rfind("```")].strip()
        
        result = json.loads(text)
    except Exception as e:
        result = {
            "error": str(e),
            "overview": f"{topic['name']}是当前市场热点板块",
            "key_players": stock_codes,
            "key_segments": [{"name": "全产业链", "importance": "高"}],
            "risks": ["市场波动风险"],
            "summary": "建议关注龙头公司"
        }
    
    # 保存结果
    task_result = {
        "topic": topic_id,
        "topic_name": topic["name"],
        "status": "done",
        "result": result,
        "quotes": quotes,
        "reports": reports_agg,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    _save_task(topic_id, task_result)
    _RUNNING_TASKS[topic_id] = task_result
    logger.info(f"Industry analysis complete for {topic_id}")

@router.post("/analyze")
async def start_analysis(topic_id: str, background_tasks: BackgroundTasks, custom_stocks: str = "", refresh: bool = True):
    """启动产业链AI分析"""
    if topic_id in _RUNNING_TASKS and _RUNNING_TASKS[topic_id].get("status") == "running":
        return {"status": "already_running", "message": "该主题分析正在进行中"}
    
    # 不再使用缓存，每次都重新生成
    task_record = {
        "status": "running",
        "topic": topic_id,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    _RUNNING_TASKS[topic_id] = task_record
    background_tasks.add_task(_run_industry_analysis, topic_id, custom_stocks)
    return {"status": "started", "message": "AI分析已在后台启动，约1分钟后刷新查看结果"}

@router.get("/analysis/{topic_id}")
async def get_analysis_result(topic_id: str):
    """获取分析结果"""
    running = _RUNNING_TASKS.get(topic_id)
    if running and running.get("status") == "running":
        return {"status": "running", "message": "分析正在进行中"}
    
    cached = _load_task(topic_id)
    if cached:
        return {"status": "done", "data": cached}
    
    return {"status": "not_found", "message": "未找到该主题分析，请先启动分析"}

@router.get("/analysis-status/{topic_id}")
async def get_analysis_status(topic_id: str):
    """获取分析状态"""
    running = _RUNNING_TASKS.get(topic_id)
    if running:
        return {
            "status": running.get("status"),
            "topic": topic_id,
            "updated_at": running.get("updated_at")
        }
    cached = _load_task(topic_id)
    if cached:
        return {
            "status": cached.get("status"),
            "topic": topic_id,
            "updated_at": cached.get("updated_at")
        }
    return {"status": "not_found"}


# ── 关键词驱动的产业链研报精读分析 ───────────────────────────────────────────────
_COLORS = ["#6366f1", "#3b82f6", "#06d6c8", "#f59e0b", "#22d97a", "#f04060", "#a855f7", "#14b8a6"]

# MAP：逐篇研报抽取结构化事实（分批并发，覆盖全部研报）
_MAP_PROMPT = """你是产业链研究分析师。下面是若干篇机构研报的正文摘录。请**逐篇**提取与产业链拆解相关的关键事实，严格依据原文。
仅返回 JSON 数组（每篇一个对象，按给定 idx），不要任何多余文字、不要 markdown：
[{
  "idx": 1,
  "segments": [{"name": "环节/部件名", "percent": 占比数字或null, "note": "成本/价值量/市占率等依据"}],
  "bottleneck": "本篇提到的卡脖子/技术壁垒环节（无则空字符串）",
  "irreplaceable": "本篇提到的不可替代/壁垒最高的环节或公司（无则空）",
  "fastest_catchup": "本篇提到的国产追赶最快的环节或公司（无则空）",
  "value_shift": "本篇提到的价值量在环节间迁移/集中的描述，如技术演进使某环节价值占比上升/下降（无则空）",
  "overseas_catalyst": "本篇提到的海外龙头(英伟达/台积电/海外大厂)资本开支/技术路线/订单等一级催化，及其对应的国内卡位供应商（无则空）",
  "leaders": ["龙头公司"],
  "leader_gap": "国产与海外龙头差距的描述（无则空）",
  "targets": [{"name": "公司", "target_price": 数字或null, "rating": "评级"}],
  "milestones": [{"date": "时间/年份", "event": "产业里程碑事件"}],
  "substitution": [{"module": "环节", "tech": "替代技术", "risk": "替代风险/概率描述"}],
  "equipment": [{"name": "生产/制造设备名(如 叠层机/流延机/烧结炉/光刻机/PVD镀膜机)", "process": "用于的生产工序/环节", "makers": "主要设备厂商(海外原名/国内简称，含市占率若有)", "localization": "国产化率/卡脖子/精度壁垒等描述（无则空）"}],
  "key_points": "本篇最关键的1-2句结论"
}]
注意：equipment 仅在研报确有提及生产/制造设备(产线设备/专用装备/关键工艺设备)时填写，逐条对应工序与设备厂商；研报未涉及设备则给空数组。"""

# MAP Prompt 口径版本号：_MAP_PROMPT 的字段/口径一旦变更就 bump（如 v2），
# 全局 facts 缓存按 prompt_version 比对，旧版自动失效不被复用。
_MAP_PROMPT_VERSION = "v2"  # v2: 新增 equipment(生产设备/厂商/国产化)字段，强制重抽


def _map_text_hash(text: str) -> str:
    """对实际喂给 LLM 的正文摘录算 sha1。

    截断与 MAP 内部一致（t[:2800]）：正文不变则 hash 不变 → 可命中缓存；
    PDF 重抓导致正文变动则 hash 变化 → 自动失效旧缓存重抽。
    """
    return hashlib.sha1((text or "")[:2800].encode("utf-8")).hexdigest()

# REDUCE 拆成两个较小的调用，避免单个 JSON 过大被截断/出错
# REDUCE-A：结构拆解（产业全景 + 3 层 BOM + 核心环节）
_REDUCE_A_PROMPT = """你是顶尖产业链研究分析师。下面是对【全部机构研报】逐篇抽取的事实汇总与核心标的行情。
请综合所有事实，输出产业链的【结构拆解】部分。**严格基于事实**。

重点：BOM 成本/价值拆解要**尽量细，逐层向下拆到不能再拆的最后一层**（环节 → 子环节 → 部件 → 子部件 → 关键工艺/材料/芯片，能到第 5 层就拆到第 5 层）。
你自行判断每条分支能拆几层：有成本占比依据的分支务必拆到最细颗粒度；确实无法再细分的分支可少于 4 层，但不要偷懒停在大类。
每个节点 percent 表示在其**父节点**中的占比，同一父级下 children 的 percent 合计≈100；顶层 bom 的 percent 合计≈100。

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、键值间用逗号分隔：
{
  "overview": "产业全景（约300字）",
  "market_size": "市场规模与增速（含数字）",
  "key_players": ["代码 名称", "..."],
  "bom": [{"name": "环节", "percent": 35, "color": "#6366f1", "children": [{"name": "子环节", "percent": 60, "children": [{"name": "部件", "percent": 50, "children": [{"name": "子部件/工艺/材料", "percent": 40}]}]}]}],
  "key_segments": [{"name": "环节", "importance": "高|中|低", "leader": "龙头", "localization_rate": "国产化率(如45%)", "substitution_risk": "低|中|高", "bottleneck_score": 0到100的整数, "description": "说明"}],
  "bottleneck_ranking": [{"name": "环节名", "score": 0到100的整数, "value_share": "该环节在整链中的价值量占比(如约30%,无依据则空)", "reason": "评分依据：国产化率/集中度/技术壁垒/不可替代性一句话", "leader": "该环节龙头(含代码,优先A股)"}],
  "cost_down_paths": [{"lever": "降本抓手(如:硅光集成/CPO/自动化耦合/良率提升/国产替代)", "mechanism": "降本机理与作用环节", "magnitude": "预计降幅(如 单位成本年降15-20%)", "horizon": "兑现节奏(如 2025-2027)", "beneficiary": "受益环节/公司"}],
  "product_targets": [{"product": "整机/产品型号(如 800G光模块/400G ZR)", "current_price": "当前均价(含单位,如 $1200/只)", "price_trend": "价格趋势(如 年降10-15%)", "target_price": "目标/展望价位", "note": "依据说明"}]
}
顶层 bom 的 color 按此顺序选取：#6366f1 #3b82f6 #06d6c8 #f59e0b #22d97a #f04060 #a855f7 #14b8a6
其中 cost_down_paths（降本路径）给 3-6 条，product_targets（整机/产品目标价，注意是**产品**而非个股）给 2-5 个主力产品。
**bottleneck_score（瓶颈/卡脖子评分，0-100）**评判标准：国产化率越低、行业集中度越高(被少数海外厂垄断)、技术壁垒越高、越不可替代 → 分越高(越卡脖子)；终端整机/泛受益、国产化充分、可替代性强的环节分越低。每个 key_segments 必填该分。
**bottleneck_ranking** 把全链环节按 score 从高到低排序给 4-8 条，突出最卡脖子的上游核心环节（这是分析的重点抓手）。
**严格基于研报事实，无数据的字段留空字符串，不要杜撰具体数字。**
"""

# REDUCE-A 失败时的降级：只聚焦 BOM 成本/价值拆解，JSON 更精简以降低截断概率
_BOM_ONLY_PROMPT = """你是顶尖产业链研究分析师。下面是对【全部机构研报】逐篇抽取的事实汇总与核心标的行情。
请**只**输出该产业链的【BOM 成本/价值拆解】，逐层向下拆到不能再拆的最后一层（环节 → 子环节 → 部件 → 子部件 → 关键工艺/材料/芯片，能到第 5 层就拆到第 5 层）。**严格基于事实**。
每个节点 percent 表示在其**父节点**中的占比，同一父级下 children 的 percent 合计≈100；顶层 bom 的 percent 合计≈100。
你自行判断每条分支能拆几层，有依据的分支务必拆到最细颗粒度；确实无法再细分的分支可少于 4 层。

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、键值间用逗号分隔：
{
  "bom": [{"name": "环节", "percent": 35, "color": "#6366f1", "children": [{"name": "子环节", "percent": 60, "children": [{"name": "部件", "percent": 50, "children": [{"name": "子部件/工艺/材料", "percent": 40}]}]}]}]
}
顶层 bom 的 color 按此顺序选取：#6366f1 #3b82f6 #06d6c8 #f59e0b #22d97a #f04060 #a855f7 #14b8a6
"""

# REDUCE-B：洞察与估值
_REDUCE_B_PROMPT = """你是顶尖产业链研究分析师。下面是对【全部机构研报】逐篇抽取的事实汇总与核心标的行情。
请综合所有事实，输出产业链的【洞察与估值】部分。**严格基于事实**。

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、键值间用逗号分隔：
{
  "milestones": [{"date": "2024", "event": "里程碑事件"}],
  "bottleneck": "最大卡脖子环节及原因",
  "irreplaceable": "不可替代性最强的环节/公司及理由",
  "fastest_catchup": "国产追赶最快的环节/公司及进展",
  "value_migration": {"trend": "随技术/工艺演进，产业链价值量正从哪个环节迁移/集中到哪个环节（约80字，如 价值从模组组装迁向上游光芯片/硅光集成）", "from": "价值流出的环节", "to": "价值流入(未来瓶颈)的环节", "beneficiary": "价值迁入侧的受益环节/公司(含代码)"},
  "leader": "整体龙头股（含代码）",
  "leader_gap": "国产厂商与海外龙头的差距",
  "target_price": "整体目标价/估值中枢观点（约150字，含重点标的目标价）",
  "target_prices": [{"name": "公司", "current": 现价数字, "target": 目标价数字, "upside": "空间(如+25%)"}],
  "substitution_risk": [{"module": "模块", "probability": "低(<20%)", "tech": "替代技术", "window": "5-10年", "impact": "投资影响"}],
  "valuation": "估值全景与重点标的 PE/PB 评价",
  "risks": ["风险1", "风险2"],
  "summary": "投资建议（约200字）"
}
"""

# REDUCE-C：可执行的明日操作决策（辅助“第二天买哪些股票”）
_REDUCE_C_PROMPT = """你是审慎的A股投资决策顾问。下面是对某产业链【全部机构研报】逐篇抽取的事实，以及核心标的【实时行情】。
请基于研报逻辑 + 当前估值，给出**可执行的「明日操作建议」**。务必：标的来自给定标的池、给具体 6 位代码与价格区间、严格基于事实、不杜撰目标价。

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、括号配对：
{
  "market_view": "该产业链当前所处阶段与短期看法（约120字，含景气方向与资金面）",
  "buy_candidates": [
    {
      "code": "6位代码", "name": "名称",
      "priority": 推荐优先级序号(1=最优先，整数),
      "tier": "龙头|中军|弹性|后排",
      "chain_position": "瓶颈卡位|整机终端|泛受益",
      "action": "买入|关注|回避",
      "conviction": "高|中|低",
      "current": 现价数字,
      "entry": "建议买入区间(如 18.5-19.2)",
      "target": 目标价数字,
      "upside": "空间(如+25%)",
      "stop": "止损位(如 16.8)",
      "horizon": "短线(1-2周)|中线(1-3月)|长线",
      "catalyst": "近期催化/驱动事件",
      "logic": "买入逻辑(引用研报依据：卡位/份额/订单/目标价)",
      "risk": "主要风险"
    }
  ],
  "top_picks": [{"code": "6位代码", "name": "名称", "chain_position": "瓶颈卡位|泛受益", "reason": "一句话首选理由"}],
  "watch": ["次选关注标的(含代码与一句话)"],
  "notes": "组合与仓位建议、纪律与风险提示（约80字）"
}
要求：
- buy_candidates 给 **6-10 只**（尽量多给、覆盖不同 tier，不要只给少数几只），**严格按推荐优先级排序**(priority 从 1 递增，数组顺序即为优先级顺序)。
- **每只必须标注 chain_position（产业链卡位）**：瓶颈卡位(处于最卡脖子的上游核心环节,材料/芯片/设备/关键器件)、整机终端(终端整机/品牌/系统集成商)、泛受益(边际/题材受益但非卡位)。
- **排序与首选必须向「瓶颈卡位」倾斜**：在逻辑/确定性相近时，瓶颈卡位标的优先级高于整机终端；**top_picks 首选只能从 chain_position=瓶颈卡位 或 泛受益中选，禁止把 整机终端 标的放入 top_picks**（终端标的可留在 buy_candidates 供参考，但不作首选）。这是本决策的核心取向：押产业链最卡脖子的上游环节，回避终端整机巨头。
- top_picks 给 **2-3 只**首选（不要只给一只），是 buy_candidates 中确定性最强且处于瓶颈卡位的标的。
- 若上下文含【机构荐股共识】，**仅作交叉参考**（机构共识天然偏向终端大龙头），不作为排序主依据；仍以研报逻辑 + 瓶颈卡位为准、不杜撰。
- **每只必须标注 tier 定位**：龙头(行业地位最高、确定性最强)、中军(基本面扎实的二线主力/腰部)、弹性(市值小、业绩或题材爆发力强、向上弹性大)、后排(二线跟随/边际受益、确定性偏弱)。同一池内不同标的应体现出层次，不要全部标同一类。
- 优先有研报明确目标价/逻辑支撑且估值合理者；current 必须用给定行情现价；无把握的标的标 action=关注 而非买入。"""


# REDUCE-D：竞争格局（国内外排行榜）+ 上中下游三层标的拆解
_REDUCE_D_PROMPT = """你是顶尖产业链研究分析师。下面是对某产业链【全部机构研报】逐篇抽取的事实汇总与核心标的行情。
请综合所有事实，输出两块内容：【竞争格局·国内外排行榜】与【上中下游标的·分层拆解】。**严格基于研报事实，不杜撰份额数字**。

要求：
1) competitive_landscape：分别给出**全球**与**国内**两个排行榜，**每个榜都再按产业链位置拆成 上游/中游/下游 三组**(对象的键固定为 上游/中游/下游)。每组内按市场份额/地位从高到低排，每条含公司名(海外公司用原名)、所属国家/地区、市占率、卡位/优势一句话。能体现“国产替代在上中下游各环节当前所处位置”。
   **全球榜的全球市场份额(share)必须标注**——这是本表重点：优先用研报中的确切全球市占率数字(如 28%)；研报只给定性/区间时给估计值并加“约”(如 约15-20%)；确实无任何依据再退为定性描述(如 第一梯队)，但**不要留空**。国内榜的 share 填国内市占率，并**额外标注该公司的全球市场份额(global_share)**——以体现“国产替代在全球竞争中所处的位置”，同样优先用确切数字、否则给“约/全球第N”等定性，不要留空。某一组(如某游)确无代表公司时给空数组。
2) supply_chain：把产业链分成**上游/中游/下游**三段(segment=上游|中游|下游)。每段下给若干**细分环节**，每个细分环节再挂 1-4 家**代表上市公司**(优先 A 股，给 6 位代码；海外龙头可给名称、code 留空)。即“产业链位置 → 细分环节 → 标的”三层。
   每个标的**必须写清楚**：① 该公司**此项业务**在该细分环节的市场份额(share)；② 高端/中低端的份额结构(tier_share)——即该公司在高端与中低端市场各自的占比/定位（如“高端约15%、中低端约40%，正向高端突破”）。严格基于研报事实，**没有明确数字就给定性描述并标注“约/估”，不要杜撰精确数字**。

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、括号配对：
{
  "competitive_landscape": {
    "global": {
      "上游": [{"company": "公司名", "country": "国家/地区", "share": "全球市占率(必填,如28%或约15-20%)", "edge": "卡位/优势一句话"}],
      "中游": [{"company": "公司名", "country": "国家/地区", "share": "全球市占率(必填)", "edge": "卡位/优势一句话"}],
      "下游": [{"company": "公司名", "country": "国家/地区", "share": "全球市占率(必填)", "edge": "卡位/优势一句话"}]
    },
    "domestic": {
      "上游": [{"company": "公司名(代码)", "share": "国内市占率", "global_share": "该公司全球市占率(必填,如约8%或全球第5)", "edge": "卡位/优势一句话"}],
      "中游": [{"company": "公司名(代码)", "share": "国内市占率", "global_share": "该公司全球市占率(必填)", "edge": "卡位/优势一句话"}],
      "下游": [{"company": "公司名(代码)", "share": "国内市占率", "global_share": "该公司全球市占率(必填)", "edge": "卡位/优势一句话"}]
    },
    "summary": "国内外竞争格局与国产替代进展总评(约120字)"
  },
  "supply_chain": [
    {"segment": "上游", "desc": "本段定位一句话", "links": [
      {"name": "细分环节(如:光芯片)", "note": "环节说明/壁垒", "stocks": [{"code": "688498", "name": "源杰科技", "role": "卡位一句话", "share": "此项业务市占率(如本环节约25%)", "tier_share": "高端/中低端份额结构(如:高端约15%、中低端约40%)"}]}
    ]},
    {"segment": "中游", "desc": "", "links": []},
    {"segment": "下游", "desc": "", "links": []}
  ]
}
global / domestic 两榜的 上游+中游+下游 合计各给 6-12 家(按各游实际有代表公司的多寡分配，某游可多可少、确无则空数组)；domestic 每家的 global_share 必填；supply_chain 每段 2-4 个细分环节；每个标的的 share 与 tier_share 字段必填(无确切数据则给定性描述，勿留空)。"""


# REDUCE-H：瓶颈个股·卡脖子评分榜（个股维度，区别于 REDUCE-A 的「环节」维度）
_REDUCE_H_PROMPT = """你是顶尖产业链研究分析师。下面是对某产业链【全部机构研报】逐篇抽取的事实汇总与核心标的行情。
请从**个股**维度，挑出处于产业链**最卡脖子环节**的 A 股上市公司，做一张「个股卡脖子评分榜」。**严格基于研报事实，不杜撰份额与数字。**

只收录处于卡脖子上游核心环节（材料/芯片/设备/关键器件等）的标的；终端整机/泛受益标的不入榜。

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、括号配对：
{
  "bottleneck_stocks": [
    {
      "code": "6位代码",
      "name": "名称",
      "segment": "所处的卡脖子瓶颈环节(如 光芯片/磷化铟衬底/HBM)",
      "score": 0到100的整数,
      "reason": "为何卡脖子一句话(国产化率低/集中度高/技术壁垒高/不可替代)"
    }
  ]
}
要求：给 **6-15 只**，**严格按 score 从高到低排序**(score 越高越卡脖子)。每只必须给 6 位 A 股代码。score 评判标准：国产化率越低、行业集中度越高(被少数海外厂垄断)、技术壁垒越高、越不可替代 → 分越高。无合适卡脖子标的时 bottleneck_stocks 返回空数组。"""


# REDUCE-E：近期新增信息（产业链最近的边际变化/新逻辑）
_REDUCE_E_PROMPT = """你是顶尖产业链研究分析师。下面是对某产业链【全部机构研报】逐篇抽取的事实（每条开头标注了机构与发布日期）。
请**聚焦最近发布（近 1-3 个月）的研报**，提炼出该产业链**新增 / 边际变化的产业逻辑与信息**——即相比过去新出现的：新催化、新技术路线、新订单 / 产能、新政策、新价格 / 供需变化、新的市场预期等。**严格基于事实，不杜撰具体数字。**

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、括号配对：
{
  "recent_updates": [
    {
      "date": "信息时间(如 2026-05 或 2026Q2)",
      "title": "一句话标题(新逻辑/新变化)",
      "category": "催化|技术|供需|政策|订单产能|价格|竞争|预期",
      "detail": "具体说明这条新增产业逻辑/信息及其相比此前的边际变化(约60-100字)",
      "impact": "对产业链/相关标的的影响方向与一句话(如：看多 + 理由)",
      "beneficiary": "主要受益环节/公司(无则空字符串)"
    }
  ]
}
要求：给 **4-8 条**，按时间由新到旧排序，优先最新、最具边际变化的信息；只收录确有新增/变化含义的条目，老生常谈的行业背景不要列入。无可提炼的近期新信息时 recent_updates 返回空数组。"""


# REDUCE-F：海外一级催化 → A股二阶卡位供应商映射（“瓶颈理论”核心视角）
_REDUCE_F_PROMPT = """你是擅长全球供应链映射的产业链分析师。下面是对某产业链【全部机构研报】逐篇抽取的事实汇总与核心标的行情。
请从**海外一级催化倒推国内二阶卡位标的**的视角，梳理：海外龙头/终端巨头(如英伟达、台积电、博通、特斯拉、海外大厂等)的资本开支/技术路线/订单/产能等**一级催化**，会沿产业链传导到**国内哪个最卡脖子的上游环节**，对应**哪些 A 股卡位供应商**。**严格基于研报事实，不杜撰份额与数字。**

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、括号配对：
{
  "overseas_mapping": [
    {
      "overseas_anchor": "海外催化锚点(公司+事件,如 英伟达GB200放量/CoWoS扩产)",
      "catalyst": "一级催化的具体内容与方向(订单/capex/技术路线)",
      "transmission": "传导路径一句话(海外终端 → 国内卡脖子环节)",
      "domestic_segment": "对应的国内卡脖子上游环节(如 光芯片/HBM封装/PCB)",
      "stocks": [{"code": "6位代码", "name": "名称", "role": "在该环节的卡位一句话"}],
      "certainty": "高|中|低"
    }
  ]
}
要求：给 **3-6 条**，每条尽量给 1-3 家 A 股卡位供应商(给 6 位代码)；只收录有研报依据的传导链，没有明确海外催化映射时 overseas_mapping 返回空数组。"""


# REDUCE-G：链主链路分析（围绕「链主」拆出整条链路上的供应商及其份额）
_REDUCE_G_PROMPT = """你是擅长全球供应链拆解的产业链分析师。下面是对某产业链【全部机构研报】逐篇抽取的事实汇总与核心标的行情。
请识别该产业链的**链主**——即主导整条产业链需求、技术路线与利润分配的核心环节/终端巨头（如光模块的英伟达、谷歌；新能源车的特斯拉、比亚迪等，可含海外与国内）。
对**每一个链主**，沿其需求链路**逐环节**梳理出整条链路上的**供应商**及其**对该链主的供货份额**（即该供应商在链主该环节采购中的占比，而非全行业份额）。**严格基于研报事实，份额无确切数字时给"约/估"定性，不要杜撰精确数字。**

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、括号配对：
{
  "chain_masters": [
    {
      "name": "链主名称(如 英伟达)",
      "country": "国家/地区",
      "role": "链主定位一句话(如 AI算力链主,主导GB200/Rubin需求与光互联路线)",
      "demand": "其需求/资本开支/技术路线如何拉动本产业链(约60字)",
      "links": [
        {
          "segment": "链路环节(如 800G/1.6T光模块)",
          "note": "环节在该链主链路中的角色一句话",
          "suppliers": [
            {"name": "供应商名(A股给中文简称)", "code": "6位代码(海外/非上市留空)", "country": "国家/地区",
             "share": "对该链主的供货份额(如 约40% 或 第一供应商)", "role": "卡位/优势一句话"}
          ]
        }
      ]
    }
  ]
}
要求：给 **1-3 个**最核心链主（光模块这类可同时给英伟达、谷歌等多个链主）；每个链主沿链路给 **3-6 个关键环节**，每个环节给 **1-4 家**供应商（优先 A 股给 6 位代码，海外龙头给名称、code 留空）；**每家供应商的 share（对该链主的供货份额）必填**（无确切数字给"约/第N供应商"等定性，不要留空）。没有明确链主链路依据时 chain_masters 返回空数组。"""


# REDUCE-I：生产设备拆解（制造该产业链产品需要哪些专用设备 + 设备厂商份额排名 + 卡脖子逻辑）
_REDUCE_I_PROMPT = """你是顶尖产业链研究分析师，尤其精通**制造装备/生产设备**环节。下面是对某产业链【全部机构研报】逐篇抽取的事实汇总（含 equipment 设备线索）与核心标的行情。
请从**生产/制造设备**视角，拆解：制造该产业链产品**需要哪些关键专用设备**、每种设备的**厂商市场份额排名（全球/国内）**、以及**卡脖子逻辑**（国产化率、海外垄断、精度/技术壁垒、不可替代性）。**严格基于研报事实，不杜撰份额与数字。**

要求：
1) equipment_list：按**生产工序顺序**列出该产业链产品制造所需的**关键设备**（如 MLCC：流延机→印刷机→叠层机→等静压机→切割机→排胶/烧结炉→端电极被覆/电镀设备→测编机）。每种设备给：对应工序、作用、重要性、占整线设备投资比重、国产化率、卡脖子评分与逻辑、以及**设备厂商排名**（全球榜 + 国内榜）。
2) 设备厂商排名 makers：全球榜每条含厂商名(海外原名)、国家/地区、全球市占率(必填,优先确切数字,否则"约/第一梯队"等定性)、优势一句话；国内榜每条含厂商名(A股给"名称(代码)")、6位代码(非上市/海外留空)、国内市占率、全球市占率、优势一句话。**优先把对应 A 股设备上市公司挖出来**（设备国产替代是核心抓手）。

仅返回**严格合法**的 JSON，不要多余文字、不要 markdown，确保所有字符串闭合、括号配对：
{
  "equipment_summary": "本产业链生产设备全景与国产化总评(约150字，点明最卡脖子的设备环节与国产替代进展)",
  "equipment_list": [
    {
      "name": "设备名(如 叠层机)",
      "process": "对应生产工序/环节(如 成型叠层)",
      "function": "作用一句话",
      "importance": "高|中|低",
      "value_share": "占整线设备投资比重(如约20%，无依据则空字符串)",
      "localization_rate": "国产化率(如约15%或'基本依赖进口')",
      "bottleneck_score": 0到100的整数,
      "bottleneck_reason": "卡脖子逻辑一句话(海外垄断/精度壁垒/技术不可替代/材料配套)",
      "makers": {
        "global": [{"company": "厂商名(海外原名)", "country": "国家/地区", "share": "全球市占率(必填)", "edge": "优势一句话"}],
        "domestic": [{"company": "厂商名(含A股代码)", "code": "6位代码(非上市/海外留空)", "share": "国内市占率", "global_share": "全球市占率(必填)", "edge": "优势/进展一句话"}]
      }
    }
  ]
}
equipment_list 给 **4-10 种**关键设备，**按生产工序先后排序**，并把**最卡脖子**(国产化率低/海外垄断)的设备 bottleneck_score 打高；每种设备 makers.global 给 2-5 家、makers.domestic 给 1-4 家（确无国产厂商则空数组并在 bottleneck_reason 点明）。设备厂商务必尽量挖出对应 **A 股上市公司**并给 6 位代码。研报完全未涉及生产设备时 equipment_list 返回空数组。"""


# 机构荐股榜·逐只核心竞争力（独立分批小调用，结合研报事实/标题为每只标的提炼 3 句话）
_INST_LOGIC_PROMPT = """你是A股产业链投资分析师。下面给出某产业链「机构荐股共识榜」中若干标的的机构评级 / 一致目标价 / 对现价上涨空间 / 近期研报标题，以及产业研报事实摘要。
请为**每只标的**用**恰好 3 句话**说明它的【核心竞争力】，三句分别尽量覆盖：① 行业卡位 / 份额 / 技术壁垒；② 订单 / 产能 / 业绩驱动；③ 估值与目标价空间 / 主要催化。
每句精炼成一短句（不超过约 40 字），**严格基于给定信息，不杜撰具体数字**；信息不足时该句可概括定性，但不要编造。
仅返回**严格合法**的 JSON，不要多余文字、不要 markdown：
{"items": [{"code": "6位代码", "competitiveness": ["第一句", "第二句", "第三句"]}]}"""


# 为 BOM 每个层级环节（大类/中间环节/细分环节，逐层）推荐头部个股（独立分批小调用）
_LEAF_STOCK_PROMPT = """你是A股产业链选股专家。给定某产业链成本构成树里的若干「环节」(path 用 > 表示从大类到细分的层级路径，可能是大类层、中间层或最细分层)，
为**每个环节**推荐 **2-4 家**最相关的 A 股上市公司（**尽量多给、不要只给一只**），且尽量**同时覆盖龙头标的与弹性标的**：
- 龙头标的：该环节行业地位最高、份额/技术领先、确定性最强的公司；
- 弹性标的：市值偏小、业绩或题材爆发力强、向上弹性大的公司。
要求：必须是该细分环节真正相关的公司；该环节标的较少时也至少给 2 只布局该环节的代表公司；code 用 6 位数字；
每只用 tier 字段标注定位（取值仅限「龙头」或「弹性」）；reason 用一句话说明卡位/份额/技术。
仅返回**严格合法**的 JSON，不要多余文字、不要 markdown：
{"items": [{"path": "光芯片>EML芯片>100G EML", "stocks": [{"code": "688498", "name": "源杰科技", "tier": "龙头", "reason": "一句话理由"}]}]}"""


async def _recommend_leaf_stocks(keyword: str, leaves: list[dict], hint: str,
                                 batch_size: int = 8, concurrency: int = 4) -> None:
    """为每个叶子环节推荐头部个股，直接写入 leaf['node']['stocks']。"""
    if not leaves:
        return
    batches = [leaves[i:i + batch_size] for i in range(0, len(leaves), batch_size)]
    sem = asyncio.Semaphore(concurrency)
    by_path = {l["path"]: l["node"] for l in leaves}

    async def run(batch):
        lines = "\n".join(f"- {l['path']}" for l in batch)
        user = (f"产业链：{keyword}\n相关公司线索：{hint[:1200]}\n最细分环节(逐条推荐)：\n{lines}")
        async with sem:
            try:
                data = await _chat_json(_LEAF_STOCK_PROMPT, user, 4096, "industry_segstock", retries=1, provider=_research_provider())
            except Exception as e:
                logger.debug(f"leaf stock batch failed: {e}")
                return
        for it in data.get("items", []):
            node = by_path.get((it.get("path") or "").strip())
            if not node:
                continue
            stocks = []
            for s in (it.get("stocks") or []):
                c = re.sub(r"\D", "", str(s.get("code", "")))[:6]
                if c:
                    stocks.append({"code": c, "name": s.get("name", ""),
                                   "tier": _s(s.get("tier")).strip(),
                                   "reason": s.get("reason", "")})
            if stocks:
                node["stocks"] = stocks

    await asyncio.gather(*[run(b) for b in batches])


async def _recommend_inst_logic(keyword: str, picks: list[dict], digest_hint: str,
                                batch_size: int = 12, concurrency: int = 3) -> None:
    """为机构荐股榜每只标的提炼 3 句「核心竞争力」，写入 pick['competitiveness'] 列表
    （结合机构评级/目标价 + 该股近期研报标题 + 产业研报事实）。"""
    if not picks:
        return
    by_code = {p["code"]: p for p in picks}
    batches = [picks[i:i + batch_size] for i in range(0, len(picks), batch_size)]
    sem = asyncio.Semaphore(concurrency)

    async def run(batch):
        lines = []
        for p in batch:
            seg = f"- {p.get('name','')}({p['code']})：评级「{p.get('top_rating') or '-'}」"
            if p.get("org_count"):
                seg += f"、{p['org_count']}家机构覆盖"
            if p.get("target_avg"):
                seg += f"、一致目标价{p['target_avg']}"
            if p.get("upside_pct") is not None:
                seg += f"、对现价空间{p['upside_pct']:+.0f}%"
            titles = [t for t in (rp.get("title") for rp in (p.get("reports") or [])) if t][:4]
            if titles:
                seg += "；近期研报：" + " / ".join(titles)
            lines.append(seg)
        user = (f"产业链：{keyword}\n研报事实摘要（节选）：\n{(digest_hint or '')[:4000]}\n\n"
                f"机构荐股榜标的（逐只给出 3 句核心竞争力）：\n" + "\n".join(lines))
        async with sem:
            try:
                data = await _chat_json(_INST_LOGIC_PROMPT, user, 3072, "industry_instlogic", retries=1, provider=_research_provider())
            except Exception as e:
                logger.debug(f"inst logic batch failed: {e}")
                return
        for it in (data.get("items") or []):
            code = re.sub(r"\D", "", str(it.get("code", "")))[:6]
            node = by_code.get(code)
            if not node:
                continue
            comp = it.get("competitiveness")
            if isinstance(comp, list):
                sents = [_s(x).strip() for x in comp if _s(x).strip()][:3]
            else:
                sents = [s.strip() for s in re.split(r"[。\n]", _s(comp)) if s.strip()][:3]
            if sents:
                node["competitiveness"] = sents

    await asyncio.gather(*[run(b) for b in batches])


async def _seed_stocks(keyword: str, cap: int = 80) -> tuple[list[str], dict, list[str]]:
    """用一次轻量 AI 调用得到关键词产业链核心 A 股 + 细分搜索关键词，再用 smartbox 校验代码。

    （本环境 push2 / 百度概念接口不可用，故以 LLM 给种子 + 腾讯 smartbox 校验。）
    Returns: (codes, {code:name}, related_terms)
    """
    names: list[str] = []
    ai_codes: dict[str, str] = {}
    terms: list[str] = []
    seed_user = (
        f"针对「{keyword}」产业链：(1)**尽量多地**列出相关 **A股上市公司**（覆盖上中下游、龙头+弹性，"
        f"目标 50-80 家，宁多勿漏）；**优先纳入卡脖子上游核心环节（材料/芯片/设备/关键器件）的标的**，"
        f"终端整机/品牌厂可少给；"
        f"(2)列出 10-16 个该产业链的**细分环节/行业板块词**（用于检索更多研报，尽量贴近申万行业分类的命名，"
        f"如“电池/锂电池/半导体/光伏设备/汽车零部件”等上下游材料、设备、器件、板块名）。"
        f"**细分词请优先给最卡脖子的上游核心环节词（如硅光/磷化铟衬底/光芯片/HBM/CoWoS 等），少给宽泛的终端整机词。**"
        '仅返回JSON：{"stocks":[{"name":"公司简称","code":"6位代码"}],"terms":["细分/板块关键词"]}'
    )
    try:
        # _chat_json 内置重试 + “只输出合法 JSON” 追加提示，避免单次返回非 JSON 直接整段失败
        data = await _chat_json(
            "你是A股产业链研究专家，只输出JSON。不要任何解释或 markdown，直接以 { 开头。",
            seed_user, 3000, "industry_seed", provider=_research_provider(),
        )
        if isinstance(data, dict):
            for s in data.get("stocks", []):
                nm = (s.get("name") or "").strip()
                if nm:
                    names.append(nm)
                    ai_codes[nm] = re.sub(r"\D", "", str(s.get("code", "")))[:6]
            terms = [str(t).strip() for t in (data.get("terms") or []) if str(t).strip()]
    except Exception as e:
        logger.warning(f"seed stocks AI failed for {keyword}: {e}")

    codes: list[str] = []
    name_map: dict[str, str] = {}
    for nm in names[:cap]:
        hits = await asyncio.to_thread(_smartbox, nm)
        code = name = None
        if hits:
            code, name = hits[0]["code"], hits[0]["name"]
        elif len(ai_codes.get(nm, "")) == 6:
            code, name = ai_codes[nm], nm
        if code and code not in name_map:
            codes.append(code)
            name_map[code] = name

    # 兜底：AI 种子失败/解析不出股票时，直接用关键词本身 + 拆出的细分词去 smartbox 捞，
    # 保证 codes 不为空，避免整次分析退化成只靠标题搜索（如此前“光模块”只采 4 篇）
    if not codes:
        fallback_terms = [keyword] + terms
        seen_fb = set()
        for q in fallback_terms[:10]:
            for hit in await asyncio.to_thread(_smartbox, q):
                c = hit["code"]
                if c and c not in name_map and c not in seen_fb:
                    seen_fb.add(c)
                    codes.append(c)
                    name_map[c] = hit["name"]
            if len(codes) >= cap:
                break
        if codes:
            logger.info(f"seed fallback via smartbox for '{keyword}': {len(codes)} codes")
        else:
            logger.warning(f"seed produced 0 codes for '{keyword}' (AI + smartbox both empty)")

    return codes, name_map, terms


# 研报库覆盖判定：分析时若全市场研报库够新（最新日期在 N 天内），优先读库不实时拉
_DB_FRESH_DAYS = 3

# 全量精读：读库时每只个股 / 行业研报检索的「上限」给到极大值，等价于不截断。
# 真正的范围控制交给 begin_date（_REPORT_LOOKBACK_DAYS 回溯窗口）。
_FULL_COLLECT_CAP = 100000


def _collect_reports_from_db(keyword: str, codes: list[str], match_terms: list[str],
                             begin_date: str) -> list[dict]:
    """从已入库研报检索（个股按 code + 行业按关键词），返回原始字段形态列表。

    全量精读：个股 / 行业研报都不再设小上限，把库内近一年命中的研报**全部**取出
    （仍受 begin_date 回溯窗口约束）。上限给到极大值仅作防御性兜底。
    """
    from quantforge.data.storage import db_cache
    out: list[dict] = []
    for c in codes:
        for r in db_cache.reports_get(c, limit=_FULL_COLLECT_CAP):
            if (r.get("publish_date") or "") >= begin_date:
                out.append(_stored_stock_report_to_raw(r))
    for r in db_cache.industry_reports_search(match_terms, begin_date, limit=_FULL_COLLECT_CAP):
        out.append(_stored_industry_report_to_raw(r))
    return out


async def _collect_reports(keyword: str, codes: list[str], terms: list[str] = None) -> list[dict]:
    """汇总研报，去重并按日期倒序。**优先读库**，库不够新/覆盖不足时实时回补。

    读库：个股按 code 取 stock_reports + 行业按关键词检索 industry_reports（全市场
    研报已由 report_sync_scheduler 落库）。
    实时回补（库陈旧或读到 0 篇时）：
      1) 行业研报·按行业代码（服务端过滤）
      2) 个股研报·逐只
      3) 行业研报·按标题关键词
    """
    from quantforge.data.storage import db_cache
    match_terms = [keyword] + [t for t in (terms or []) if t and t != keyword]
    begin_date = (datetime.now() - timedelta(days=_REPORT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    # ── 1) 先读库 ──
    db_rows = await asyncio.to_thread(
        _collect_reports_from_db, keyword, codes, match_terms, begin_date)
    # 库是否够新：全市场最新研报日期在 _DB_FRESH_DAYS 天内即视为新鲜，跳过实时拉取
    latest = await asyncio.to_thread(db_cache.reports_global_latest_date)
    fresh_floor = (datetime.now() - timedelta(days=_DB_FRESH_DAYS)).strftime("%Y-%m-%d")
    db_fresh = bool(latest and latest >= fresh_floor)

    groups: list[list[dict]] = [db_rows]

    # ── 2) 库陈旧或读到太少 → 实时回补 ──
    if not db_fresh or len(db_rows) < 20:
        ind_codes = _match_industry_codes(match_terms, limit=40)
        logger.info(f"DB gap-fill for '{keyword}' (db_rows={len(db_rows)}, fresh={db_fresh}); "
                    f"matched {len(ind_codes)} industry codes: {ind_codes}")
        bt_stock = begin_date

        async def stock_reports():
            agg: list[dict] = []
            sem = asyncio.Semaphore(8)

            async def one(code):
                async with sem:
                    try:
                        return await asyncio.to_thread(_eastmoney_reports, code, 5, 100, bt_stock)
                    except Exception:
                        return []
            for reps in await asyncio.gather(*[one(c) for c in codes]):
                agg.extend(reps)
            return agg

        async def industry_by_code():
            if not ind_codes:
                return []
            try:
                # 全量：行业代码维度多翻页，把命中的行业研报尽量拉全
                return await asyncio.to_thread(_eastmoney_reports_by_industry, ind_codes, "1", 50, 100)
            except Exception as e:
                logger.debug(f"industry-by-code failed: {e}")
                return []

        async def industry_by_title():
            try:
                # 全量：标题关键词维度多翻页
                return await asyncio.to_thread(_eastmoney_industry_reports, match_terms, 50, 100)
            except Exception as e:
                logger.debug(f"industry-by-title failed: {e}")
                return []

        live = await asyncio.gather(stock_reports(), industry_by_code(), industry_by_title())
        groups.extend(live)
        # 回补结果顺手入库，下次直接读库命中
        try:
            flat = [r for g in live for r in g]
            await asyncio.to_thread(_store_reports_mixed, flat)
        except Exception as e:
            logger.debug(f"gap-fill store failed: {e}")
    else:
        logger.info(f"'{keyword}' served from DB: {len(db_rows)} reports (latest={latest})")

    seen: set[str] = set()
    out: list[dict] = []
    for g in groups:
        for r in g:
            ic = r.get("infoCode")
            if ic and ic not in seen:
                seen.add(ic)
                out.append(r)
    out.sort(key=lambda r: r.get("publishDate", ""), reverse=True)
    logger.info(f"collected {len(out)} unique reports for '{keyword}' "
                f"(db={len(db_rows)}, total={len(out)})")
    return out


def _collect_blog_articles(keyword: str, terms: list[str] = None) -> list[tuple[dict, str]]:
    """检索「机构荐股」(知识星球调研纪要)里命中关键词的全部文章，转成 (伪研报, 正文) 元组。

    返回的元组直接并入 MAP 逐篇抽事实管线，让机构荐股文章与东财研报一起被精读分析。
    伪研报字段对齐 MAP 所认的驼峰键（infoCode/orgSName/title/publishDate），infoCode 用
    ``blog_<post_id>`` 前缀，绝不与东财 infoCode 冲突。
    """
    from quantforge.data.storage import db_cache
    match_terms = [keyword] + [t for t in (terms or []) if t and t != keyword]
    begin_date = (datetime.now() - timedelta(days=_REPORT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    try:
        rows = db_cache.blog_posts_search(match_terms, begin_date, limit=_FULL_COLLECT_CAP)
    except Exception as e:
        logger.debug(f"blog_posts_search failed for '{keyword}': {e}")
        return []
    out: list[tuple[dict, str]] = []
    for r in rows:
        text = (r.get("content_text") or "").strip()
        if len(text) < 30:  # 过短(纯图片/转发)无分析价值，跳过
            continue
        title = (r.get("ai_title") or r.get("title") or "").strip()
        # 机构身份：优先标题里的【券商+行业】标签，否则作者，再否则统称
        org = ""
        m = re.search(r"【([^】]{2,20})】", r.get("title") or "")
        if m:
            org = m.group(1).strip()
        org = org or (r.get("author") or "").strip() or "机构荐股"
        out.append(({
            "infoCode": f"blog_{r.get('post_id')}",
            "orgSName": org,
            "title": title,
            "publishDate": (r.get("created_at") or "")[:10],
            "_source": "机构荐股",
        }, text))
    logger.info(f"collected {len(out)} 机构荐股 articles for '{keyword}'")
    return out


# 看涨类评级关键词（用于「机构荐股」共识打分：买入/增持/推荐/强烈推荐/跑赢…）
_BULLISH_RATING_KW = ("买入", "增持", "推荐", "强推", "强烈", "跑赢", "优于", "outperform", "buy", "overweight")


# 东财研报详情页：调研纪要/研报原文链接（按 infoCode 直达）
_EM_REPORT_URL = "https://data.eastmoney.com/report/info/{info_code}.html"


def _recent_report_links(code: str, limit: int = 6) -> list[dict]:
    """该股近一年已落库研报里取最近 N 篇，附东财研报详情页链接（调研纪要原文）。"""
    from quantforge.data.storage import db_cache
    try:
        reps = db_cache.reports_get(code, limit=limit)
    except Exception:
        return []
    out: list[dict] = []
    for r in reps:
        ic = (r.get("info_code") or "").strip()
        if not ic:
            continue
        out.append({
            "title": (r.get("title") or "").strip(),
            "org": (r.get("org") or "").strip(),
            "date": (r.get("publish_date") or "")[:10],
            "rating": (r.get("rating") or "").strip(),
            "url": _EM_REPORT_URL.format(info_code=ic),
        })
    return out


def _aggregate_institutional_picks(codes: list[str], names: dict,
                                   quotes: dict, top_n: int = 12) -> list[dict]:
    """从研报库聚合每只个股的【机构荐股共识】（评级分布 + 目标价一致预期 + 研报家数）。

    数据全部来自已入库的 stock_reports（机构荐股数据库），与 AI 无关，纯统计。
    返回按「看涨研报家数 → 上涨空间」排序的共识榜，供前端独立 Tab 展示 + 喂给决策 AI。
    """
    from quantforge.data.storage import db_cache
    picks: list[dict] = []
    for c in dict.fromkeys(codes):
        try:
            summ = db_cache.reports_summary(c)
        except Exception:
            continue
        if not summ or not summ.get("count"):
            continue
        ratings = summ.get("ratings") or {}
        bullish = sum(n for rt, n in ratings.items()
                      if any(k in rt.lower() for k in _BULLISH_RATING_KW))
        tgt = summ.get("target") or {}
        q = quotes.get(c) or {}
        price = q.get("price")
        upside = None
        if tgt.get("avg") and price:
            try:
                upside = round((float(tgt["avg"]) / float(price) - 1) * 100, 1)
            except (TypeError, ValueError, ZeroDivisionError):
                upside = None
        picks.append({
            "code": c,
            "name": names.get(c) or q.get("name") or "",
            "report_count": summ.get("count", 0),
            "org_count": summ.get("org_count", 0),
            "bullish_count": bullish,
            "top_rating": summ.get("top_rating") or "",
            "ratings": ratings,
            "target_avg": tgt.get("avg"),
            "target_high": tgt.get("high"),
            "target_low": tgt.get("low"),
            "target_orgs": tgt.get("count"),
            "current": price,
            "upside_pct": upside,
            "latest_date": (summ.get("latest_date") or "")[:10],
            "pe_this": summ.get("pe_this"), "pe_next": summ.get("pe_next"),
            "reports": _recent_report_links(c),
        })
    # 排序：先看涨研报家数，再上涨空间，再总研报家数
    picks.sort(key=lambda p: (
        p["bullish_count"],
        p["upside_pct"] if p["upside_pct"] is not None else -999,
        p["report_count"],
    ), reverse=True)
    return picks[:top_n]


def _institutional_digest(picks: list[dict], limit: int = 12) -> str:
    """把机构荐股共识压成一段文本，注入决策 REDUCE 的上下文。"""
    if not picks:
        return ""
    lines = ["【机构荐股共识·来自研报库统计】（覆盖期内多家机构评级/目标价聚合）："]
    for p in picks[:limit]:
        seg = f"- {p['name']}({p['code']})：研报{p['report_count']}篇"
        if p.get("bullish_count"):
            seg += f"、看涨{p['bullish_count']}篇"
        if p.get("top_rating"):
            seg += f"、主流评级「{p['top_rating']}」"
        if p.get("target_avg"):
            seg += f"、一致目标价{p['target_avg']}（{p.get('target_orgs') or '?'}家）"
        if p.get("upside_pct") is not None:
            seg += f"、对现价空间{p['upside_pct']:+.0f}%"
        lines.append(seg)
    return "\n".join(lines)


async def _map_extract_facts(reports_with_text: list[tuple], batch_size: int = 8,
                             concurrency: int = 8, progress_cb=None,
                             cancel_cb=None, provider: str | None = None,
                             on_batch=None) -> list[dict]:
    """MAP 阶段：分批并发地逐篇抽取研报事实，覆盖**全部**可读研报。

    Args:
        reports_with_text: [(report_dict, text), ...]
        progress_cb: 可选回调 progress_cb(done_batches, total_batches)。
        cancel_cb: 可选回调，返回 True 表示用户已请求中断；在每批开头检查，
            命中即抛 _AnalysisCancelled 让整个 MAP（及外层任务）尽快收尾。
    Returns:
        facts 列表，每项含 org/title/date + 抽取出的结构化字段。
    """
    from quantforge.api.ai_client import chat

    batches = [reports_with_text[i:i + batch_size] for i in range(0, len(reports_with_text), batch_size)]
    sem = asyncio.Semaphore(concurrency)
    all_facts: list[dict] = []
    _done = {"n": 0}
    _ntotal = len(batches)
    _miss = {"n": 0}  # 因解析失败/无法回填而丢弃的研报篇数

    def _stamp(obj: dict, src: dict):
        obj["_org"] = src.get("orgSName", "")
        obj["_title"] = src.get("title", "")
        obj["_date"] = (src.get("publishDate", "") or "")[:10]
        obj["_info"] = str(src.get("infoCode") or "")
        # _source: "机构荐股" for blog/纪要, "research" for real research reports
        obj["_source"] = src.get("_source", "research")

    async def _ask(prompt_parts: list[str], max_tokens: int):
        """调一次 MAP；失败重试一次（提高 token 上限 + 追加“只输出合法 JSON”）。"""
        for attempt in range(2):
            user = "\n".join(prompt_parts)
            if attempt == 1:
                user += "\n\n注意：请只输出**严格合法**的 JSON 数组，确保每个对象都带 idx、所有字符串闭合、括号配对。"
            try:
                # 重试 +2048 给截断留头寸，但 clamp 到模型硬顶——否则顶格的
                # _MAP_MAX_TOKENS 再 +2048 会越界触发 400（重试路径反被废掉）。
                _mt = min(max_tokens + attempt * 2048, _MODEL_MAX_OUTPUT)
                # patient=True：碰到 429 限流不丢批，长档重试（每5分钟→每半小时）扛过去，
                # MAP 流程不断；MAP 期间有 _map_heartbeat 持续刷新进度，长等待不会被判僵尸。
                txt = await chat(system=_MAP_PROMPT, user=user,
                                 max_tokens=_mt, caller="industry_map",
                                 provider=provider, patient=True, cancel_cb=cancel_cb)
                arr = _loads_lenient(txt)
                if isinstance(arr, list):
                    return arr
            except Exception as e:
                logger.debug(f"map batch parse failed (attempt {attempt}): {e}")
        return None

    async def _extract_single(r: dict, t: str) -> dict | None:
        """整批失败后的逐篇兜底：单篇重抽，命中即回填。"""
        parts = [f"【1】机构:{r.get('orgSName','')} 标题:《{r.get('title','')}》 日期:{r.get('publishDate','')[:10]}",
                 t[:2800], ""]
        async with sem:
            arr = await _ask(parts, 2048)
        if arr:
            obj = arr[0] if isinstance(arr[0], dict) else None
            if obj:
                _stamp(obj, r)
                return obj
        return None

    async def run_batch(batch: list[tuple]):
        # 中断检查点：用户请求取消后，已在飞行中的 ≤concurrency 批仍会跑完，但不再
        # 启动新批，整段 MAP 在一波内收敛退出（asyncio.gather 见到首个异常即停）。
        if cancel_cb and cancel_cb():
            raise _AnalysisCancelled()
        parts = []
        for i, (r, t) in enumerate(batch, 1):
            parts.append(f"【{i}】机构:{r.get('orgSName','')} 标题:《{r.get('title','')}》 日期:{r.get('publishDate','')[:10]}")
            parts.append(t[:2800])
            parts.append("")
        async with sem:
            arr = await _ask(parts, _MAP_MAX_TOKENS)
        _done["n"] += 1
        if progress_cb:
            try:
                progress_cb(_done["n"], _ntotal)
            except Exception:
                pass

        # 本批 facts 单独收集，跑完即回调入库（增量）→ report_facts 实时增长、断点不丢
        batch_facts: list[dict] = []
        if not isinstance(arr, list):
            # 整批解析失败：逐篇兜底重抽，不让整批 8 篇凭空消失
            singles = await asyncio.gather(*[_extract_single(r, t) for r, t in batch])
            for r_t, obj in zip(batch, singles):
                if obj:
                    batch_facts.append(obj)
                else:
                    _miss["n"] += 1
        else:
            # idx 兜底：模型漏写/写错 idx 时，按对象在数组中的顺序映射回 batch[i]
            objs = [o for o in arr if isinstance(o, dict)]
            for pos, obj in enumerate(objs):
                idx = obj.get("idx", 0)
                if isinstance(idx, int) and 1 <= idx <= len(batch):
                    src = batch[idx - 1][0]
                elif pos < len(batch):
                    src = batch[pos][0]  # 顺序兜底
                else:
                    _miss["n"] += 1
                    continue
                _stamp(obj, src)
                batch_facts.append(obj)
            # 本批返回条数少于输入篇数：缺的篇逐篇兜底重抽
            if len(objs) < len(batch):
                covered = {f.get("_info") for f in batch_facts}
                missing = [(r, t) for r, t in batch if str(r.get("infoCode") or "") not in covered]
                if missing:
                    singles = await asyncio.gather(*[_extract_single(r, t) for r, t in missing])
                    for obj in singles:
                        if obj:
                            batch_facts.append(obj)
                        else:
                            _miss["n"] += 1

        all_facts.extend(batch_facts)
        if on_batch and batch_facts:
            try:
                await on_batch(batch_facts)   # 增量入库（异常不影响继续抽其余批）
            except Exception as e:
                logger.warning(f"map on_batch ingest failed: {e}")

    await asyncio.gather(*[run_batch(b) for b in batches])
    valid = sum(1 for f in all_facts if f.get("_info"))
    logger.info(f"map extract: input={len(reports_with_text)} facts={len(all_facts)} "
                f"valid_info={valid} dropped={_miss['n']}")
    return all_facts


async def _run_keyword_analysis(keyword: str, read_limit: int = 0,
                                keywords: list[str] | None = None):
    """后台执行：关键词 → 研报下载入库 → AI 精读（全部）→ 自动保存。

    keyword: 主题名称（用于 slug / 展示 / 报告标题）。
    keywords: 检索关键词清单（**全部作为搜索材料**，逐个 seed 取并集）；缺省时按 slug
        从命名主题注册表还原，再缺省则回退 ``[keyword]``（单关键词模式，行为不变）。
    read_limit: 精读的研报上限；0 表示**全部**。
    """
    slug = _slug(keyword)
    # 单任务精读篇数硬上限：read_limit=0(全部)或超限时都收口到 _RESEARCH_MAX_REPORTS，
    # 防上万篇把单进程吃到 OOM（线上 14514 篇曾触发内核 oom-killer）。0=不限则放行。
    if _RESEARCH_MAX_REPORTS > 0:
        read_limit = _RESEARCH_MAX_REPORTS if read_limit <= 0 else min(read_limit, _RESEARCH_MAX_REPORTS)
    # 检索材料清单：显式传入优先；否则查命名主题注册表（让重试/队列/定时按 slug 自动
    # 还原多关键词）；都没有就退回单关键词。
    if keywords is None:
        _t = _get_topic(slug)
        if _t and _t.get("keywords"):
            keywords = _t["keywords"]
    search_kws = [k.strip() for k in (keywords or [keyword]) if k and k.strip()] or [keyword]
    # 清掉可能残留的旧取消标志（上一轮被取消/崩溃留下的），避免新任务一进来就被秒杀。
    _clear_cancel(slug)
    # 开始时间：沿用触发端/队列已写入的 started_at（保持计时器连续），缺失则现在起算。
    _started_at = (_RUNNING_TASKS.get(slug) or {}).get("started_at") or datetime.now().isoformat()

    def upd(stage: str, progress: int, **extra):
        # 每个进度检查点都顺带探一次取消标志：命中即抛出，外层统一收口为 cancelled。
        # 覆盖所有阶段边界；MAP 内部另有 cancel_cb 做波内中断。
        if _is_cancel_requested(slug):
            raise _AnalysisCancelled()
        _RUNNING_TASKS[slug] = {
            "status": "running", "slug": slug, "keyword": keyword,
            "stage": stage, "progress": progress, "started_at": _started_at,
            "updated_at": datetime.now().isoformat(), **extra,
        }

    try:
        upd("识别核心标的", 8)
        # 这几段都是「单段长 await、内部无检查点」：seed/收集研报可达数分钟（慢模型/弱网），
        # 不包一层的话取消要干等整段返回（实测可达 40s+）。用 _cancellable 包住，任何阶段
        # 都能 ~2s 响应中断。
        # 多关键词：逐个 seed 并取并集（codes/names/terms 全合并），所有关键词本身也作为检索词。
        codes: list[str] = []
        names: dict[str, str] = {}
        terms: list[str] = []
        _seen_code, _seen_term = set(), set()
        for _kw_i in search_kws:
            c_i, n_i, t_i = await _cancellable(slug, _seed_stocks(_kw_i))
            for c in c_i:
                if c and c not in _seen_code:
                    _seen_code.add(c); codes.append(c); names[c] = n_i.get(c, "")
            for t in t_i:
                if t and t not in _seen_term:
                    _seen_term.add(t); terms.append(t)
        # 把每个检索关键词也并入 terms，确保多关键词全部进入研报/机构荐股检索匹配。
        for _kw_i in search_kws:
            if _kw_i not in _seen_term:
                _seen_term.add(_kw_i); terms.append(_kw_i)
        # 标的数过多时截断行情拉取（避免多关键词并集后 quote 调用过大），不影响检索。
        codes = codes[:150]

        upd("获取行情数据", 20, report_count=0)
        from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
        quotes = {}
        if codes:
            quotes = await asyncio.to_thread(_tencent_quote, [_normalize_code(c) for c in codes])

        upd("收集机构研报", 32)
        reports = await _cancellable(slug, _collect_reports(keyword, codes, terms))

        # 收集到的个股研报元数据落库（stock_reports，按股票代码；行业研报无 stockCode 跳过）
        try:
            from quantforge.data.storage import db_cache
            stock_rows = [_norm_report_row(r.get("stockCode"), r)
                          for r in reports if r.get("infoCode") and r.get("stockCode")]
            if stock_rows:
                n = await asyncio.to_thread(db_cache.reports_upsert_many, stock_rows)
                logger.info(f"[{keyword}] stored {n} stock-report rows to DB")
        except Exception as e:
            logger.debug(f"store collected reports failed: {e}")

        n_read = len(reports) if read_limit <= 0 else min(read_limit, len(reports))
        eta = _estimate_eta(n_read)
        upd("下载研报并入库", 45, report_count=len(reports),
            read_total=n_read, eta_seconds=eta, eta_text=_fmt_eta(eta))

        from quantforge.api import research_lib

        def _dl_progress(done, total):
            # 下载阶段占 45→58 的进度条；同步收敛 ETA
            pct = 45 + int(13 * done / max(total, 1))
            remain = _estimate_eta(max(0, total - done))
            upd("下载研报并入库", pct, report_count=len(reports),
                pdf_done=done, pdf_total=total,
                read_total=n_read, eta_seconds=remain, eta_text=_fmt_eta(remain))

        lib = await _cancellable(slug, asyncio.to_thread(
            research_lib.download_and_extract_many, reports, read_limit,
            _DL_WORKERS, _dl_progress, _MAP_TEXT_CHARS))
        texts = lib.get("texts", {})

        # 收集可用于分析的文本：
        #   1) 成功抽取到 PDF 正文：优先用 PDF 正文
        #   2) 未成功抽取 PDF：用「机构 + 标题 + 日期」做元数据摘要，
        #      这样行业研报即使 dfcfw 404 也能进入分析池，提高样本数
        reports_with_text = []
        hints = ("占比", "成本", "构成", "BOM", "环节", "格局", "份额", "产业链", "价值量", "拆解")
        n_full = 0
        n_meta = 0
        # read_limit 是「精读上限」：不仅限制 PDF 下载，也要限制进入 AI 精读池的研报数。
        # 否则超出上限的研报会走 else 分支以元数据摘要并入分析池，导致精读仍是全量。
        # 与 download_and_extract_many(reports[:cap]) 取同一批前 read_limit 篇，保证一致。
        read_pool = reports if read_limit <= 0 else reports[:read_limit]
        for r in read_pool:
            t = texts.get(r.get("infoCode") or r.get("info_code"))
            if t:
                # PDF 正文 → 高相关度优先
                score = sum(t.count(h) for h in hints) + 10  # PDF 正文保底 10 分
                reports_with_text.append((score, r, t))
                n_full += 1
            else:
                # 没有 PDF → 用元数据生成一段"摘要文本"
                title = (r.get("title") or "").strip()
                org = (r.get("orgSName") or r.get("orgName") or "").strip()
                date = (str(r.get("publishDate") or "")[:10]).strip()
                industry = (r.get("industryName") or r.get("industry") or "").strip()
                summary_parts = []
                if org:
                    summary_parts.append(f"【机构】{org}")
                if industry:
                    summary_parts.append(f"【行业】{industry}")
                if date:
                    summary_parts.append(f"【发布日期】{date}")
                if title:
                    summary_parts.append(f"【标题】{title}")
                summary_parts.append("（正文未在东财 PDF 库中获取到，以下为 AI 基于标题与行业生成的摘要占位，可用于主题判断与趋势聚合。）")
                meta_text = "\n".join(summary_parts)
                score = sum(title.count(h) for h in hints) if title else 0
                reports_with_text.append((score, r, meta_text))
                n_meta += 1
        reports_with_text.sort(key=lambda x: (x[0], x[1].get("publishDate", "")), reverse=True)
        rt = [(r, t) for _, r, t in reports_with_text]
        pdf_used = len(rt)

        # 机构荐股(调研纪要)文章：命中关键词的全部文章并入精读池（已有正文，无需下载 PDF）
        # QF_RESEARCH_NO_BLOG=1 时跳过 blog，只精读研报（用于纯研报灌库）。
        blog_docs = []
        if not os.getenv("QF_RESEARCH_NO_BLOG"):
            try:
                blog_docs = await asyncio.to_thread(_collect_blog_articles, keyword, terms)
                if blog_docs:
                    rt.extend(blog_docs)
            except Exception as e:
                logger.debug(f"collect blog articles failed: {e}")
                blog_docs = []
        n_blog = len(blog_docs)
        upd("收集调研纪要", 59, report_count=len(reports), n_blog=n_blog,
            pdf_done=lib.get("downloaded", 0), pdf_total=len(reports))
        logger.info(f"[{keyword}] texts ready: full={n_full} meta-only={n_meta} "
                    f"blog={n_blog} total={len(rt)}")

        # ── 精读·MAP：按 infoCode 命中全局缓存，只对未命中篇调 LLM（复用费 token 的逐篇抽取）──
        prior = _load_task(slug)
        round_no = int((prior.get("analysis_round", 0) if prior else 0)) + 1

        # MAP 逐篇仍走全局廉价模型（量大，不强切 opus）；据此算「本轮目标模型/质量分」，
        # 缓存里模型质量 < 本轮目标时不复用（避免拿低质结果冒充高质）。
        from quantforge.api.ai_client import provider_to_model, model_tier
        from quantforge.data.storage import db_cache
        # MAP 默认走全局廉价模型（None）；设 QF_RESEARCH_MAP_PROVIDER（如 claude-code）
        # 可让逐篇抽取也走指定模型（如本地 Opus），用于高质量灌库/绕开限流。
        _map_provider = os.getenv("QF_RESEARCH_MAP_PROVIDER") or None
        want_model = provider_to_model(_map_provider)
        want_tier = model_tier(want_model)
        # force 全量重抽开关：QF_MAP_FORCE_RERUN=1 时跳过缓存（仍写回，刷新缓存）
        _force_map = bool(os.getenv("QF_MAP_FORCE_RERUN"))

        facts_cache = {}
        total_count = len(rt)

        if rt:
            # 查全局缓存，分流命中/未命中
            info_to_hash = {}
            for r, t in rt:
                ic = str(r.get("infoCode") or "")
                if ic:
                    info_to_hash[ic] = _map_text_hash(t)
            cached = {} if _force_map else await asyncio.to_thread(
                db_cache.report_facts_get_many, list(info_to_hash.keys()))
            todo_rt = []
            n_hit = 0
            for r, t in rt:
                ic = str(r.get("infoCode") or "")
                h = info_to_hash.get(ic)
                c = cached.get(ic) if ic else None
                cached_tier = int(c.get("model_tier", 0)) if c else 0
                if (c and ic and c.get("prompt_version") == _MAP_PROMPT_VERSION
                        and cached_tier >= want_tier
                        and (c.get("text_hash") == h or cached_tier > want_tier)):
                    # hash 匹配 → 标准命中；hash 漂移但现有质量更高 → 也复用（不重抽，
                    # 避免低质模型因 PDF 重提取后格式微变而反复重抽浪费 token）
                    facts_cache[ic] = c["fact"]      # 命中：直接复用，不调 LLM
                    n_hit += 1
                else:
                    todo_rt.append((r, t))
            logger.info(f"[{keyword}] round {round_no}: MAP 缓存命中 {n_hit}/{total_count}，"
                        f"待抽 {len(todo_rt)}（目标模型 {want_model} tier={want_tier}）")

            todo_count = len(todo_rt)
            if todo_rt:
                stg = "AI 精读·逐篇提取（增量）"
                # ETA 用「波数（wave）」公式：_MAP_CONC 个批次并发为一波，
                # 已完成 done_waves 波耗时 elapsed，剩余 remain_waves 波做线性外推。
                # 旧公式 elapsed*(total_b-done_b)/done_b 把并发批次当串行算，
                # done_b=1 时估出 (total_b-1)×elapsed，严重偏高。
                _map_t = {"start": time.monotonic()}
                _map_state = {"done_b": 0, "total_b": 0}

                def _do_map_upd(done_b, total_b):
                    pct = 60 + int(22 * done_b / max(total_b, 1))
                    elapsed = time.monotonic() - _map_t["start"]
                    if done_b > 0 and elapsed > 1:
                        done_waves = max(1, math.ceil(done_b / _MAP_CONC))
                        remain_waves = math.ceil((total_b - done_b) / _MAP_CONC)
                        remain = (elapsed / done_waves) * remain_waves + _T_REDUCE_TAIL
                    else:
                        remain = _estimate_eta(todo_count)
                    _map_done_now = min(done_b * _MAP_BATCH, todo_count)
                    upd(stg, pct, report_count=len(reports), pdf_count=lib.get("downloaded", 0),
                        analysis_round=round_no,
                        read_done=n_hit + _map_done_now,
                        read_total=total_count,
                        cached_count=n_hit, map_total=todo_count, map_done=_map_done_now,
                        eta_seconds=int(remain), eta_text=_fmt_eta(remain))

                def _map_progress(done_b, total_b):
                    _map_state["done_b"] = done_b
                    _map_state["total_b"] = total_b
                    _do_map_upd(done_b, total_b)

                # 心跳：每 5s 刷一次统计，让前端在长 LLM 调用期间也能看到最新 ETA
                async def _map_heartbeat():
                    while True:
                        await asyncio.sleep(5)
                        try:
                            _do_map_upd(_map_state["done_b"], _map_state["total_b"])
                        except _AnalysisCancelled:
                            return
                        except Exception:
                            pass

                upd(stg, 60, report_count=len(reports), pdf_count=lib.get("downloaded", 0),
                    analysis_round=round_no, read_done=n_hit, read_total=total_count,
                    cached_count=n_hit, map_total=todo_count, map_done=0)
                # cancel_cb 防止启动新批（波边界生效）；外面再包 _cancellable 让在飞的
                # 批次也能 ~2s 内被打断，二者叠加=任何时刻取消都快。
                # 增量入库回调：每批抽完即写 report_facts（有多少入多少），
                # 中途崩/休眠也不丢已抽的；facts_cache 同步填充供后续使用。
                async def _ingest_batch(batch_facts):
                    rows = []
                    for f in batch_facts:
                        real_ic = str(f.get("_info") or "")
                        ic = real_ic or f"_noinfo_{round_no}_{id(f)}"
                        facts_cache[ic] = f
                        if real_ic and real_ic in info_to_hash:   # 有 infoCode 才入全局缓存
                            rows.append({"info_code": real_ic, "fact": f,
                                "model": want_model, "model_tier": want_tier,
                                "prompt_version": _MAP_PROMPT_VERSION,
                                "text_hash": info_to_hash[real_ic]})
                    if rows:
                        await asyncio.to_thread(db_cache.report_facts_upsert_many, rows)

                _hb = asyncio.create_task(_map_heartbeat())
                try:
                    await _cancellable(slug, _map_extract_facts(
                        todo_rt, batch_size=_MAP_BATCH, concurrency=_MAP_CONC,
                        progress_cb=_map_progress, cancel_cb=lambda: _is_cancel_requested(slug),
                        provider=_map_provider, on_batch=_ingest_batch))
                finally:
                    _hb.cancel()
                    try:
                        await _hb
                    except asyncio.CancelledError:
                        pass
            else:
                # 全命中：MAP 无需调 LLM，直接把进度推到 MAP 完成点，别卡在 60%
                upd("AI 精读·逐篇提取（全部命中缓存）", 82,
                    report_count=len(reports), pdf_count=lib.get("downloaded", 0),
                    analysis_round=round_no, read_done=total_count, read_total=total_count,
                    cached_count=total_count, map_total=0, map_done=0)

            _save_facts(slug, facts_cache)

        facts = list(facts_cache.values())

        # MAP-only 灌库模式（QF_RESEARCH_MAP_ONLY=1）：研报 MAP 事实已入库 report_facts，
        # 直接收尾、跳过 REDUCE 等后续合成（用于纯灌缓存/绕开 REDUCE 超长问题）。
        if os.getenv("QF_RESEARCH_MAP_ONLY"):
            logger.info(f"[{keyword}] MAP-only：已入库 {len(facts)} 篇研报事实，跳过 REDUCE")
            upd("MAP 灌库完成（跳过 REDUCE）", 100, report_count=len(reports),
                analysis_round=round_no, read_done=total_count, read_total=total_count)
            _RUNNING_TASKS.pop(slug, None)
            return

        # 主题标签：多关键词时把检索词清单一并交代给合成模型（名称 + 关键词）。
        _kw_label = keyword if len(search_kws) <= 1 else f"{keyword}（检索关键词：{ '、'.join(search_kws) }）"
        try:
            if facts:
                digest = _facts_digest(facts)
                quote_lines = [
                    f"{code} {q.get('name','')} 现价{q.get('price',0)} PE={q.get('pe_ttm',0)} PB={q.get('pb',0)}"
                    for code, q in list(quotes.items())[:20]
                ]
                reduce_user = (
                    f"分析关键词：{_kw_label}\n\n核心标的（行情）：\n" + "\n".join(quote_lines)
                    + f"\n\n【全部 {len(facts)} 篇研报逐篇抽取的事实汇总】：\n" + digest
                )
            else:
                # 无可读 PDF：退化为标题模式
                titles = "\n".join(f"[{r.get('orgSName','')}] {r.get('title','')}" for r in reports[:40])
                reduce_user = f"分析关键词：{_kw_label}\n（PDF 正文不可用，仅研报标题）：\n{titles}"

            # REDUCE 六路并发：结构拆解 + 洞察估值 + 明日操作决策 + 竞争格局与产业链分层
            #                  + 近期新增信息 + 海外一级催化→国内卡位映射
            upd("AI 精读·汇总合成", 85, report_count=len(reports),
                pdf_count=lib.get("downloaded", 0), analysis_round=round_no)
            # 合成(REDUCE)是最吃模型质量的一段 → 走后台配置的 research provider
            # （如 "claude-code" 本地 Opus 4.8）；不可用自动跌回 HTTP 链。
            _rp = _research_provider()
            # 用可取消的 gather：REDUCE 单次可达数分钟、中间无其它检查点，包一层让
            # 中断能在 ~2s 内打断在飞的合成调用，而不是干等整段跑完。
            # REDUCE 超时给 480s：万字摘要 + 16K 输出，Opus 4.8 单路实际可达 5~7 分钟
            _reduce_timeout = 480.0
            # 八路 REDUCE 全部经 _reduce_bounded 限流：每波至多 _REDUCE_CONC 路真正在飞，
            # 其余在信号量上排队，根治「八路一把砸单 LLM 号」的 529 过载风暴。
            # patient=True + cancel_cb：碰到 429 限流时长档重试（每5分钟→每半小时）不中断；
            # 后台心跳 _reduce_heartbeat 每 10s 刷新 updated_at，长等待期间不被僵尸 TTL 误清。
            _cc = lambda: _is_cancel_requested(slug)
            def _reduce_tick():
                _RUNNING_TASKS[slug] = {
                    "status": "running", "slug": slug, "keyword": keyword,
                    "stage": "AI 精读·汇总合成", "progress": 85, "started_at": _started_at,
                    "updated_at": datetime.now().isoformat(),
                    "report_count": len(reports), "pdf_count": lib.get("downloaded", 0),
                    "analysis_round": round_no,
                }

            async def _reduce_heartbeat():
                while True:
                    await asyncio.sleep(10)
                    try:
                        _reduce_tick()
                    except Exception:
                        pass

            def _rj(system, mt, caller):
                return _reduce_bounded(_chat_json(
                    system, reduce_user, mt, caller, provider=_rp, timeout=_reduce_timeout,
                    patient=True, cancel_cb=_cc, on_wait=_reduce_tick))

            _rhb = asyncio.create_task(_reduce_heartbeat())
            try:
                part_a, part_b, part_c, part_d, part_e, part_f, part_g, part_h, part_i = await _cancellable_gather(
                    slug,
                    _rj(_REDUCE_A_PROMPT, 16000, "industry_research"),
                    _rj(_REDUCE_B_PROMPT, 8000, "industry_research"),
                    _rj(_REDUCE_C_PROMPT, 8000, "industry_decision"),
                    _rj(_REDUCE_D_PROMPT, 8000, "industry_research"),
                    _rj(_REDUCE_E_PROMPT, 6000, "industry_research"),
                    _rj(_REDUCE_F_PROMPT, 6000, "industry_research"),
                    _rj(_REDUCE_G_PROMPT, 8000, "industry_research"),
                    _rj(_REDUCE_H_PROMPT, 6000, "industry_research"),
                    _rj(_REDUCE_I_PROMPT, 8000, "industry_research"),
                    return_exceptions=True,
                )
            finally:
                _rhb.cancel()
                try:
                    await _rhb
                except asyncio.CancelledError:
                    pass
            result = {}
            if isinstance(part_a, dict):
                result.update(part_a)
            else:
                # REDUCE-A 失败(BOM 这一路最深最长、最易被截断)。单独降级重试只取 BOM，
                # 避免其余 tab 正常、唯独「成本构成」整页空白且无线索。
                logger.warning(f"keyword analysis REDUCE-A failed (bom lost): {part_a}")
            if not (result.get("bom") or []):
                try:
                    bom_only = await _chat_json(_BOM_ONLY_PROMPT, reduce_user, 16000, "industry_research", provider=_rp, timeout=_reduce_timeout)
                    if isinstance(bom_only, dict) and (bom_only.get("bom") or []):
                        result["bom"] = bom_only["bom"]
                        # A 整体失败时，顺带补回结构字段，避免总览/环节也空
                        for k in ("overview", "market_size", "key_players", "key_segments",
                                  "cost_down_paths", "product_targets"):
                            if not result.get(k) and bom_only.get(k):
                                result[k] = bom_only[k]
                        logger.info("keyword analysis recovered bom via fallback prompt")
                except Exception as e:
                    logger.warning(f"bom fallback failed: {e}")
            if isinstance(part_b, dict):
                result.update(part_b)
            if isinstance(part_c, dict):
                result["decision"] = part_c
            if isinstance(part_d, dict):
                # 竞争格局 + 上中下游三层标的
                if part_d.get("competitive_landscape"):
                    result["competitive_landscape"] = part_d["competitive_landscape"]
                if part_d.get("supply_chain"):
                    result["supply_chain"] = part_d["supply_chain"]
            if isinstance(part_e, dict) and part_e.get("recent_updates"):
                # 近期新增信息（产业链最近的边际变化/新逻辑）
                result["recent_updates"] = part_e["recent_updates"]
            if isinstance(part_f, dict) and part_f.get("overseas_mapping"):
                # 海外一级催化 → 国内卡位供应商映射（瓶颈理论核心视角）
                result["overseas_mapping"] = part_f["overseas_mapping"]
            if isinstance(part_g, dict) and part_g.get("chain_masters"):
                # 链主链路分析（围绕链主拆整条链路上的供应商及份额）
                result["chain_masters"] = part_g["chain_masters"]
            if isinstance(part_h, dict) and part_h.get("bottleneck_stocks"):
                # 个股维度卡脖子评分榜（瓶颈卡位 Tab）
                result["bottleneck_stocks"] = part_h["bottleneck_stocks"]
            if isinstance(part_i, dict) and (part_i.get("equipment_list") or part_i.get("equipment_summary")):
                # 生产设备拆解（设备 → 工序/厂商份额/卡脖子 Tab）
                result["production_equipment"] = {
                    "summary": part_i.get("equipment_summary", ""),
                    "equipment_list": part_i.get("equipment_list") or [],
                }
            if not result:
                raise RuntimeError(
                    f"reduce failed: A={part_a}; B={part_b}; C={part_c}; D={part_d}; "
                    f"E={part_e}; F={part_f}; G={part_g}; H={part_h}; I={part_i}")
        except Exception as e:
            logger.warning(f"keyword analysis AI parse failed: {e}")
            result = {
                "overview": f"{keyword}产业链分析（AI 解析失败，展示已采集研报与行情）。",
                "key_players": [f"{c} {names.get(c,'')}" for c in codes[:8]],
                "bom": [],
                "key_segments": [],
                "substitution_risk": [],
                "risks": ["AI 分析异常，请重试"],
                "summary": "",
                "error": str(e),
            }

        # 为 BOM 每个最细分环节(叶子)推荐头部个股，并补齐行情供前端展示
        from quantforge.data.feed.mootdx_feed import _tencent_quote as _tq, _normalize_code as _nc
        stock_info = dict(quotes)
        try:
            # 成本构成「每个层级」都挂龙头/弹性票（不再仅叶子节点）
            nodes = _bom_all_nodes(result.get("bom") or [])
            if nodes:
                upd("匹配头部个股", 92, report_count=len(reports), pdf_count=lib.get("downloaded", 0))
                hint = "; ".join(f"{c} {names.get(c,'')}" for c in codes[:15])
                await _recommend_leaf_stocks(keyword, nodes, hint)
                bom_codes = []
                for l in nodes:
                    for s in (l["node"].get("stocks") or []):
                        bom_codes.append(s["code"])
                need = [c for c in dict.fromkeys(bom_codes) if c not in stock_info]
                if need:
                    extra = await asyncio.to_thread(_tq, [_nc(c) for c in need])
                    stock_info.update(extra)
        except Exception as e:
            logger.debug(f"leaf stock rec/quotes failed: {e}")

        # 上中下游三层标的：规整代码并补齐行情，供前端展示现价
        try:
            sc_codes = []
            for seg in (result.get("supply_chain") or []):
                for link in (seg.get("links") or []):
                    for s in (link.get("stocks") or []):
                        code = re.sub(r"\D", "", str(s.get("code", "")))[:6]
                        s["code"] = code if len(code) == 6 else ""
                        if s["code"]:
                            sc_codes.append(s["code"])
            need = [c for c in dict.fromkeys(sc_codes) if c not in stock_info]
            if need:
                extra = await asyncio.to_thread(_tq, [_nc(c) for c in need])
                stock_info.update(extra)
        except Exception as e:
            logger.debug(f"supply_chain quotes failed: {e}")

        # 生产设备：规整国内设备厂商代码并补齐行情，供前端展示现价
        try:
            pe = result.get("production_equipment") or {}
            eq_codes = []
            for eq in (pe.get("equipment_list") or []):
                for m in ((eq.get("makers") or {}).get("domestic") or []):
                    code = re.sub(r"\D", "", str(m.get("code", "")))[:6]
                    m["code"] = code if len(code) == 6 else ""
                    if m["code"]:
                        eq_codes.append(m["code"])
            need = [c for c in dict.fromkeys(eq_codes) if c not in stock_info]
            if need:
                extra = await asyncio.to_thread(_tq, [_nc(c) for c in need])
                stock_info.update(extra)
        except Exception as e:
            logger.debug(f"production_equipment quotes failed: {e}")

        # 瓶颈视角后处理：细分环节按卡脖子评分降序（高分=最卡脖子置顶）；瓶颈排行规整排序
        try:
            def _score(x) -> float:
                try:
                    return float(x)
                except Exception:
                    return -1.0
            segs = result.get("key_segments")
            if isinstance(segs, list):
                segs.sort(key=lambda s: _score((s or {}).get("bottleneck_score")), reverse=True)
            ranking = result.get("bottleneck_ranking")
            if isinstance(ranking, list):
                ranking.sort(key=lambda r: _score((r or {}).get("score")), reverse=True)
        except Exception as e:
            logger.debug(f"bottleneck sort failed: {e}")

        # 个股卡脖子评分榜：补行情(市值/PE/现价)、年涨幅、关注度(研报家数)、
        # 一致预期利润增速、估值判定。「能取的真实取，缺的留空」——不杜撰数字。
        try:
            bstocks = result.get("bottleneck_stocks")
            if isinstance(bstocks, list) and bstocks:
                for s in bstocks:
                    code = re.sub(r"\D", "", str(s.get("code", "")))[:6]
                    s["code"] = code if len(code) == 6 else ""
                bs_codes = [s["code"] for s in bstocks if s["code"]]
                need = [c for c in dict.fromkeys(bs_codes) if c not in stock_info]
                if need:
                    extra = await asyncio.to_thread(_tq, [_nc(c) for c in need])
                    stock_info.update(extra)

                def _enrich_bottleneck_stocks() -> None:
                    from quantforge.data.storage import db_cache as _dbc
                    for s in bstocks:
                        code = s.get("code")
                        q = stock_info.get(code) or {}
                        s["name"] = s.get("name") or q.get("name", "")
                        s["price"] = q.get("price")
                        s["mcap_yi"] = q.get("mcap_yi")          # 市值(亿)
                        s["pe_ttm"] = q.get("pe_ttm")            # PE(TTM)
                        if not code:
                            continue
                        # 年涨幅：近一年日K首末收盘价（缺K线则留空）
                        s["year_change"] = None
                        try:
                            bars = _dbc.kline_load(code, "day", 250)
                            closes = [b.get("close") for b in (bars or []) if b.get("close")]
                            if len(closes) >= 2 and closes[0]:
                                s["year_change"] = round((closes[-1] / closes[0] - 1) * 100, 1)
                        except Exception:
                            pass
                        # 关注度：库内该股研报篇数
                        try:
                            s["attention"] = _dbc.reports_count(code)
                        except Exception:
                            s["attention"] = None
                        # 一致预期利润增速(本年→明年 EPS)：缺则留空
                        fwd = None
                        try:
                            summ = _dbc.reports_summary(code)
                            et, en = summ.get("eps_this"), summ.get("eps_next")
                            et = float(et) if et not in (None, "") else None
                            en = float(en) if en not in (None, "") else None
                            if et and en and et > 0:
                                fwd = round((en / et - 1) * 100, 1)
                        except Exception:
                            pass
                        s["fwd_growth"] = fwd
                        s["prev_growth"] = None   # 上季度增速：暂无干净数据源，留空
                        # 估值判定：有预期增速则 PEG，否则按 PE 绝对水平定性
                        verdict = ""
                        try:
                            pe = float(q.get("pe_ttm")) if q.get("pe_ttm") not in (None, "") else None
                            if pe is not None and pe <= 0:
                                verdict = "亏损"
                            elif pe is not None and fwd and fwd > 0:
                                peg = pe / fwd
                                verdict = "低估" if peg < 0.8 else ("合理" if peg <= 1.3 else "高估")
                            elif pe is not None:
                                verdict = "高估" if pe > 60 else ("低估" if pe < 20 else "合理")
                        except Exception:
                            pass
                        s["valuation"] = verdict

                await asyncio.to_thread(_enrich_bottleneck_stocks)

                def _sc(x) -> float:
                    try:
                        return float(x)
                    except Exception:
                        return -1.0
                bstocks.sort(key=lambda s: _sc((s or {}).get("score")), reverse=True)
        except Exception as e:
            logger.debug(f"bottleneck_stocks enrich failed: {e}")

        # 海外映射：规整代码并补齐行情，供前端展示卡位供应商现价
        try:
            om_codes = []
            for m in (result.get("overseas_mapping") or []):
                for s in (m.get("stocks") or []):
                    code = re.sub(r"\D", "", str(s.get("code", "")))[:6]
                    s["code"] = code if len(code) == 6 else ""
                    if s["code"]:
                        om_codes.append(s["code"])
            need = [c for c in dict.fromkeys(om_codes) if c not in stock_info]
            if need:
                extra = await asyncio.to_thread(_tq, [_nc(c) for c in need])
                stock_info.update(extra)
        except Exception as e:
            logger.debug(f"overseas_mapping quotes failed: {e}")

        # 链主链路：规整供应商代码并补齐行情，供前端展示现价
        try:
            cm_codes = []
            for m in (result.get("chain_masters") or []):
                for link in (m.get("links") or []):
                    for s in (link.get("suppliers") or []):
                        code = re.sub(r"\D", "", str(s.get("code", "")))[:6]
                        s["code"] = code if len(code) == 6 else ""
                        if s["code"]:
                            cm_codes.append(s["code"])
            need = [c for c in dict.fromkeys(cm_codes) if c not in stock_info]
            if need:
                extra = await asyncio.to_thread(_tq, [_nc(c) for c in need])
                stock_info.update(extra)
        except Exception as e:
            logger.debug(f"chain_masters quotes failed: {e}")

        # 决策候选：回填实时现价并据目标价重算上涨空间（确保价格准确、可执行）
        try:
            decision = result.get("decision") or {}
            cands = decision.get("buy_candidates") or []
            for c in cands:
                c["code"] = re.sub(r"\D", "", str(c.get("code", "")))[:6]
            dcodes = [c["code"] for c in cands if len(c["code"]) == 6]
            need = [c for c in dict.fromkeys(dcodes) if c not in stock_info]
            if need:
                extra = await asyncio.to_thread(_tq, [_nc(c) for c in need])
                stock_info.update(extra)
            for c in cands:
                q = stock_info.get(c["code"])
                if q and q.get("price"):
                    c["current"] = q["price"]
                    c["name"] = c.get("name") or q.get("name", "")
                    c["change_pct"] = q.get("change_pct")
                    c["pe_ttm"] = q.get("pe_ttm")
                    try:
                        tp = float(c.get("target"))
                        if tp and q["price"]:
                            c["upside"] = f"{(tp / q['price'] - 1) * 100:+.0f}%"
                    except Exception:
                        pass
            # 瓶颈取向兜底：终端整机标的不得进首选(top_picks)，只保留瓶颈卡位/泛受益
            pos_by_code = {c["code"]: _s(c.get("chain_position")).strip()
                           for c in cands if c.get("code")}
            tp_list = decision.get("top_picks")
            if isinstance(tp_list, list):
                filtered = [p for p in tp_list
                            if "终端" not in (_s(p.get("chain_position")).strip()
                                            or pos_by_code.get(re.sub(r"\D", "", str(p.get("code", "")))[:6], ""))]
                # 全被过滤掉时保留原列表，避免首选区整体空白
                decision["top_picks"] = filtered or tp_list
        except Exception as e:
            logger.debug(f"decision backfill failed: {e}")

        # blog_articles：本轮命中的调研纪要/机构荐股文章，供前端单独展示（不混入研报列表）
        blog_article_metas = [
            {"infoCode": meta.get("infoCode", ""), "title": meta.get("title", ""),
             "org": meta.get("orgSName", ""), "date": meta.get("publishDate", "")[:10],
             "source": meta.get("_source", "机构荐股")}
            for meta, _ in blog_docs
        ]

        # 合并历史研报（追加模式：保留过往采集，库随每次分析增长）
        prior_reports = (prior.get("reports") if prior else None) or []
        seen_ic, merged_reports = set(), []
        for _r in (reports + prior_reports):
            ic = _r.get("infoCode")
            if ic and ic not in seen_ic:
                seen_ic.add(ic)
                merged_reports.append(_r)
        merged_reports.sort(key=lambda r: r.get("publishDate", ""), reverse=True)

        # 时间戳与数据覆盖区间
        now = datetime.now()
        dates = [(_r.get("publishDate", "") or "")[:10] for _r in merged_reports if _r.get("publishDate")]
        dates = [d for d in dates if d]
        data_range = {"from": min(dates), "to": max(dates)} if dates else {}

        task_result = {
            "topic": slug,
            "slug": slug,
            "keyword": keyword,
            "topic_name": keyword,
            "keywords": search_kws,
            "status": "done",
            "result": result,
            "quotes": quotes,
            "stock_info": stock_info,
            "reports": merged_reports,
            "blog_articles": blog_article_metas,
            "pdf_used": pdf_used,
            "facts_count": len(facts),
            "analysis_round": round_no,
            "data_range": data_range,
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "extracted_codes": list(facts_cache.keys()),
            "pdf_stats": {k: v for k, v in lib.items() if k != "texts"},
            "created_at": (prior.get("created_at") if prior else now.isoformat()),
            "updated_at": now.isoformat(),
        }
        _save_task(slug, task_result)
        _clear_failure(slug)  # 本轮成功：清掉历史失败记录
        # 写终态进度（代理仅持久化轻量字段，补上 progress/stage 让前端进度条收尾到 100%）。
        _RUNNING_TASKS[slug] = {
            "status": "done", "slug": slug, "keyword": keyword,
            "stage": "完成", "progress": 100,
            "report_count": len(merged_reports), "read_total": pdf_used, "read_done": pdf_used,
            "updated_at": now.isoformat(),
        }
        logger.info(f"Keyword analysis complete: {keyword} ({slug}) "
                    f"round={round_no} facts={len(facts)} (全量)")
    except _AnalysisCancelled:
        # 用户主动中断：写 cancelled 终态，**不覆盖**已有的历史报告（_save_task 没被调到）。
        logger.info(f"Keyword analysis cancelled by user: {keyword} ({slug})")
        _RUNNING_TASKS[slug] = {
            "status": "cancelled", "slug": slug, "keyword": keyword,
            "stage": "已取消", "progress": 100,
            "updated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Keyword analysis failed for {keyword}: {e}")
        _fail_stage = _RUNNING_TASKS.get(slug, {}).get("stage") or "未知阶段"
        _RUNNING_TASKS[slug] = {
            "status": "error", "slug": slug, "keyword": keyword,
            "stage": _fail_stage, "progress": 100, "error": str(e),
            "updated_at": datetime.now().isoformat(),
        }
        # 持久化失败记录，让「生成记录」也能看到这次失败及原因（600s 后 running 态会被
        # 自愈清掉，故另存一份不过期的）。
        _record_failure(slug, keyword, str(e), stage=_fail_stage)
    except BaseException as e:
        # server 重启/asyncio.CancelledError：BaseException 绕过 except Exception，
        # 留一条持久失败记录让前端可见（否则没有文件也没有 failure 记录→「暂无报告」）。
        _fail_stage = _RUNNING_TASKS.get(slug, {}).get("stage") or "未知阶段"
        _record_failure(slug, keyword, f"被中断({type(e).__name__}): {e}", stage=_fail_stage)
        raise  # 必须 re-raise：让 asyncio.CancelledError 正常传播给事件循环
    finally:
        # 无论成功/失败/取消，都清掉取消标志，避免污染下一轮同 slug 任务。
        _clear_cancel(slug)


@router.post("/keyword-analyze")
async def keyword_analyze(keyword: str, background_tasks: BackgroundTasks,
                          refresh: bool = True, read_limit: int = 0,
                          _: dict = Depends(get_admin_user)):
    """启动关键词产业链研报精读分析。**仅管理员可触发**（与后台 /admin/research/analyze 同源）。

    产业链分析的触发已统一收口到管理后台：普通用户的前端页面只读已生成的报告，
    不再开放任意关键词触发（重活会拖垮后端）。新增/重跑主题请走管理后台。

    read_limit: 精读的研报上限；**0（默认）= 精读全部**。篇数越多耗时越久，
    任务在后台运行，可通过 /keyword-status 轮询进度与预计剩余时间（eta_text）。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"status": "error", "message": "关键词不能为空"}
    slug = _slug(keyword)
    rejected = _admission_check(slug)
    if rejected:
        # 已在跑→照旧提示；并发已满→改为排队（跑完一个自动顶上），不再直接拒绝。
        if rejected.get("status") == "busy":
            return _enqueue(keyword, read_limit)
        return rejected
    if not refresh:
        cached = _load_task(slug)
        if cached:
            return {"status": "done", "slug": slug, "message": "已有缓存结果"}
    _RUNNING_TASKS[slug] = {
        "status": "running", "slug": slug, "keyword": keyword,
        "stage": "初始化", "progress": 2, "started_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    background_tasks.add_task(_run_keyword_analysis, keyword, read_limit)
    note = "精读全部研报" if read_limit <= 0 else f"精读最多 {read_limit} 篇"
    return {"status": "started", "slug": slug,
            "message": f"AI 研报精读已在后台启动（{note}），请轮询进度查看预计剩余时间"}


# ── 每日定时产业链分析（后台跑，前端只读结果）──────────────────────────────────
# 需求：每天 0 点自动重跑指定关键词的产业链精读，用户进页面只看已生成的报告，
# 不再点按钮触发重活（重活会把后端拖垮）。
#
# 关键词清单可由管理员在后台增删，落 app_config（SQLite，跨 worker 共享）持久化，
# 修改即时生效（定时任务/启动补跑每次都重新读库，不吃进程内存里的旧值）。这样删除
# 某主题的报告后，把它从清单里移除即可，定时任务不会再把它生成回来。
# 下面的常量仅作「首次未配置时的默认种子」。
_DAILY_KEYWORDS_DEFAULT = ["光模块"]
_DAILY_KEYWORDS_CFG_KEY = "research:daily_keywords"      # 手动新增的额外关键词（可能尚无报告）
_DAILY_EXCLUDED_CFG_KEY = "research:daily_excluded"      # 被移出每日清单的 slug（默认全部纳入的例外）
# 定时任务的精读篇数上限：0 = **全量精读**（默认），把命中的研报全部下载正文并逐篇精读。
# 注意：大主题(如光模块)可采上千篇，全量每天重读会长时间占满线程池、拉高 LLM 调用量，
# 极端情况下后端会变慢甚至无响应。若线上需要稳态，可用 QF_RESEARCH_DAILY_LIMIT 设一个上限
# （如 800/1000）按相关度排序后截断。
_DAILY_READ_LIMIT = int(os.getenv("QF_RESEARCH_DAILY_LIMIT") or 0)

# 已生成报告主题名缓存（默认把全部历史报告纳入每日定时，避免每次扫盘读全部文件）。
_SAVED_TOPICS_CACHE: dict = {"ts": 0.0, "data": []}


def _saved_topics_for_daily() -> list[tuple[str, str]]:
    """扫描「已生成报告」（含失败记录），返回 [(展示名, slug)]，按更新时间倒序，带 60s 缓存。

    用于「默认把全部历史主题纳入每日定时」。报告文件较大故缓存，调度每 ≥30s 一跳够用。
    """
    now = time.time()
    if _SAVED_TOPICS_CACHE["data"] and now - _SAVED_TOPICS_CACHE["ts"] < 60:
        return _SAVED_TOPICS_CACHE["data"]
    items: list[tuple[str, str, str]] = []   # (name, slug, sort_key)
    seen: set[str] = set()
    if _TASKS_DIR.exists():
        for p in _TASKS_DIR.glob("kw_*.json"):
            if p.stem.endswith("_facts"):
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            slug = d.get("slug") or p.stem
            if slug in seen:
                continue
            name = str(d.get("display_name") or d.get("keyword")
                       or d.get("topic_name") or "").strip()
            if not name:
                continue
            seen.add(slug)
            items.append((name, slug, str(d.get("updated_at") or d.get("created_at") or "")))
    for slug, f in _all_failures().items():       # 失败主题也纳入（仍想每日重试）
        if slug in seen:
            continue
        name = str(f.get("keyword") or "").strip()
        if not name:
            continue
        seen.add(slug)
        items.append((name, slug, str(f.get("failed_at") or "")))
    items.sort(key=lambda x: x[2], reverse=True)
    data = [(n, s) for (n, s, _k) in items]
    _SAVED_TOPICS_CACHE["ts"] = now
    _SAVED_TOPICS_CACHE["data"] = data
    return data


def _get_daily_extra_keywords() -> list[str]:
    """手动新增的额外每日关键词（可能尚无报告）。缺省为空。"""
    from quantforge.data.storage import db_cache

    raw = db_cache.app_config_get(_DAILY_KEYWORDS_CFG_KEY)
    if raw is None:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            out, seen = [], set()
            for kw in v:
                k = str(kw or "").strip()
                if k and k not in seen:
                    seen.add(k); out.append(k)
            return out
    except Exception:
        pass
    return []


def _set_daily_extra_keywords(keywords: list[str]) -> list[str]:
    """覆盖写入手动新增的额外关键词，返回规整后的清单。"""
    from quantforge.data.storage import db_cache

    out, seen = [], set()
    for kw in keywords or []:
        k = str(kw or "").strip()
        if k and k not in seen:
            seen.add(k); out.append(k)
    if out:
        db_cache.app_config_set(_DAILY_KEYWORDS_CFG_KEY, json.dumps(out, ensure_ascii=False))
    else:
        db_cache.app_config_delete(_DAILY_KEYWORDS_CFG_KEY)
    return out


def _get_daily_excluded() -> set[str]:
    """被移出每日清单的 slug 集合（默认全部纳入时的例外）。"""
    from quantforge.data.storage import db_cache

    raw = db_cache.app_config_get(_DAILY_EXCLUDED_CFG_KEY)
    if not raw:
        return set()
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return {str(s).strip() for s in v if str(s).strip()}
    except Exception:
        pass
    return set()


def _set_daily_excluded(slugs: set[str]) -> None:
    from quantforge.data.storage import db_cache

    s = sorted({str(x).strip() for x in (slugs or set()) if str(x).strip()})
    if s:
        db_cache.app_config_set(_DAILY_EXCLUDED_CFG_KEY, json.dumps(s, ensure_ascii=False))
    else:
        db_cache.app_config_delete(_DAILY_EXCLUDED_CFG_KEY)


def _get_daily_keywords() -> list[str]:
    """每日定时清单 = 全部历史报告主题 ∪ 手动新增关键词 − 已移除项。

    默认把所有已生成报告的主题都纳入每日定时（按更新时间倒序）；用户手动新增的额外
    关键词排在其后；被移出的（_get_daily_excluded）不计入。冷启动且无任何报告/移除记录
    时回退默认种子，保证清单非空。每次都重新计算，增删/新报告即时生效。
    """
    excluded = _get_daily_excluded()
    out, seen = [], set()
    for name, slug in _saved_topics_for_daily():
        if slug in excluded or slug in seen:
            continue
        seen.add(slug); out.append(name)
    for kw in _get_daily_extra_keywords():
        slug = _slug(kw)
        if slug in excluded or slug in seen:
            continue
        seen.add(slug); out.append(kw)
    if not out and not excluded:
        return list(_DAILY_KEYWORDS_DEFAULT)
    return out


# ── 关键词顺序连跑排期 ───────────────────────────────────────────────────────
# 需求：每天到「起跑时刻」后，按清单顺序一个接一个串行跑完——前一个跑完立刻接力跑
# 下一个，不再按小时错开干等。每次只唤醒跑一个，天然串行、绝不并发；今天全部跑完后
# 睡到明天的起跑时刻再开新一轮。起跑时刻可由 QF_RESEARCH_START_HOUR 调整（默认 0 点）。
_DAILY_START_HOUR = int(os.getenv("QF_RESEARCH_START_HOUR") or 0)             # 每轮起跑整点（默认 0 点）
# 记录每个关键词「今天已尝试运行」的日期（slug → YYYY-MM-DD）。失败时 generated_at
# 不会更新，靠它避免在当天反复紧凑重试拖垮后端；跨天自然失效，次日按时重跑。
_DAILY_ATTEMPTED: dict[str, str] = {}


def _kw_done_today(kw: str, today: str) -> bool:
    """该关键词今天是否已生成过报告（按 generated_at 日期）、已尝试过运行或已失败过。"""
    if _DAILY_ATTEMPTED.get(_slug(kw)) == today:
        return True
    d = _load_task(_slug(kw))
    gen = (d or {}).get("generated_at", "") if d else ""
    if bool(gen.startswith(today)):
        return True
    # server 重启后 _DAILY_ATTEMPTED 清零——若今天已失败过（含被重启杀死），
    # 也视为「今天已尝试」，等到下次预定时刻再跑，不立即重试循环。
    f = _all_failures().get(_slug(kw))
    if f:
        failed_at = (f.get("failed_at") or "")[:10]
        if failed_at == today:
            return True
    return False


async def _run_one_keyword(kw: str) -> None:
    """重跑单个关键词（同名任务正在跑则跳过）。串行调用，从不并发。"""
    slug = _slug(kw)
    if _RUNNING_TASKS.get(slug, {}).get("status") == "running":
        logger.info(f"daily research: '{kw}' already running, skip")
        return
    _DAILY_ATTEMPTED[slug] = datetime.now().strftime("%Y-%m-%d")  # 标记今天已尝试，防失败紧凑重试
    _RUNNING_TASKS[slug] = {
        "status": "running", "slug": slug, "keyword": kw,
        "stage": "定时任务·初始化", "progress": 2,
        "started_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    try:
        await _run_keyword_analysis(kw, _DAILY_READ_LIMIT)
    except Exception as e:
        logger.error(f"daily research '{kw}' failed: {e}")
    except BaseException as e:
        # server 重启(CancelledError)：记录日志后 re-raise，让调度任务正常退出
        logger.info(f"daily research '{kw}' interrupted ({type(e).__name__}), propagating")
        raise


def _next_due_keyword() -> tuple[str, float] | None:
    """选出下一个该运行的关键词及需等待的秒数。

    规则（顺序连跑）：
      - 今天的起跑时刻已过 → 按清单顺序取**第一个今天还没跑过**的关键词，立即接力跑
        （返回极小等待）；前一个跑完后下一次唤醒自然取到下一个，串行跑完整张清单。
      - 今天清单已全部跑完 → 睡到明天的起跑时刻。
      - 还没到今天的起跑时刻 → 睡到起跑时刻。
    无关键词时返回 None。每次都重新读库取清单，增删即时生效。
    """
    kws = _get_daily_keywords()
    if not kws:
        return None
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    start = now.replace(hour=_DAILY_START_HOUR, minute=0, second=0, microsecond=0)
    if now >= start:
        for kw in kws:
            if not _kw_done_today(kw, today):
                return (kw, 1.0)            # 顺序里第一个没跑的 → 立即接力
        nxt = start + timedelta(days=1)     # 今天全部跑完 → 等明天起跑时刻
        return (kws[0], max(1.0, (nxt - now).total_seconds()))
    return (kws[0], max(1.0, (start - now).total_seconds()))  # 还没到起跑时刻 → 等


async def daily_keyword_scheduler() -> None:
    """后台循环：每天到起跑时刻后按清单顺序「连跑」重跑每日关键词。

    起跑时刻（QF_RESEARCH_START_HOUR，默认 0 点）一到，就按清单顺序一个接一个串行跑——
    前一个跑完立刻接力下一个，绝不并发、也不再按小时干等。启动时若起跑时刻已过且当天还有
    没跑的关键词，立即补跑保证页面有最新内容；当天全部跑完后睡到明天再开新一轮。
    """
    import asyncio
    logger.info(
        f"research.daily_keyword_scheduler: starting "
        f"(start_hour={_DAILY_START_HOUR}, sequential, "
        f"keywords={_get_daily_keywords()})"
    )
    while True:
        try:
            nxt = _next_due_keyword()
        except Exception as e:
            logger.warning(f"daily research schedule error: {e}")
            await asyncio.sleep(600)
            continue
        if nxt is None:
            await asyncio.sleep(3600)        # 暂无关键词，1h 后再看（可能被后台新增）
            continue
        kw, wait = nxt
        logger.info(f"daily research: next '{kw}' in {wait/3600:.2f}h")
        try:
            # 始终至少睡一会儿再跑：当某关键词正在运行(_run_one_keyword 会 skip)时，
            # _next_due_keyword 会持续返回 wait≈1.0s，若不睡满最小间隔就会变成热循环、
            # 饿死事件循环导致整站无法响应。下限 30s 既防饿死又不刷屏。
            await asyncio.sleep(max(wait, 30.0))
            await _run_one_keyword(kw)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"daily research loop error: {e}")
            await asyncio.sleep(600)         # 出错后 10min 再试，避免空转


@router.get("/daily-keywords")
def get_daily_keywords():
    """前端只读页面用：返回每日定时分析的关键词及其 slug。"""
    return {"keywords": [{"keyword": kw, "slug": _slug(kw)} for kw in _get_daily_keywords()]}


@router.get("/keyword-status/{slug}")
async def keyword_status(slug: str):
    """轮询关键词分析进度。"""
    running = _RUNNING_TASKS.get(slug)
    if running:
        return {
            "status": running.get("status"),
            "slug": slug,
            "stage": running.get("stage"),
            "progress": running.get("progress", 0),
            "report_count": running.get("report_count", 0),
            "pdf_count": running.get("pdf_count", 0),
            "read_total": running.get("read_total", 0),
            "read_done": running.get("read_done", 0),
            "pdf_done": running.get("pdf_done", 0),
            "pdf_total": running.get("pdf_total", 0),
            # MAP 精读阶段细化（之前未暴露，前端 cached_count/map_total/map_done 始终为空）
            "cached_count": running.get("cached_count"),
            "map_total": running.get("map_total"),
            "map_done": running.get("map_done"),
            # 调研纪要篇数（blog 收集阶段写入）
            "n_blog": running.get("n_blog"),
            "eta_seconds": running.get("eta_seconds"),
            "eta_text": running.get("eta_text"),
            "started_at": running.get("started_at"),
            "updated_at": running.get("updated_at"),
            "error": running.get("error"),
        }
    cached = _load_task(slug)
    if cached:
        return {"status": cached.get("status", "done"), "slug": slug, "progress": 100}
    return {"status": "not_found", "slug": slug}


@router.get("/saved-reports")
async def saved_reports():
    """列出所有已保存的关键词分析报告。"""
    items = []
    seen = set()
    if _TASKS_DIR.exists():
        for p in _TASKS_DIR.glob("kw_*.json"):
            if p.stem.endswith("_facts"):
                continue  # 跳过事实缓存文件(kw_xxx_facts.json),它不是独立报告
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                slug = d.get("slug") or p.stem
                seen.add(slug)
                items.append({
                    "slug": slug,
                    "keyword": d.get("keyword") or d.get("topic_name") or p.stem,
                    "display_name": d.get("display_name"),
                    "keywords": d.get("keywords") or [],   # 命名主题的检索关键词清单
                    "status": "done",
                    "created_at": d.get("created_at"),
                    "updated_at": d.get("updated_at"),        # 最新一次刷新时间
                    "generated_at": d.get("generated_at"),    # 同上(展示用字符串)
                    "report_count": len(d.get("reports", [])),
                    "summary": (d.get("result", {}) or {}).get("summary", "")[:80],
                })
            except Exception:
                continue
    # 合并失败记录：已成功生成过(有文件)的 slug 不会有失败记录(成功时已 _clear_failure)，
    # 故这里都是「从未成功产出」的失败任务——作为独立记录展示，并带上失败原因。
    for slug, f in _all_failures().items():
        if slug in seen:
            continue
        _tp = _get_topic(slug)
        items.append({
            "slug": slug,
            "keyword": f.get("keyword") or slug,
            "display_name": None,
            "keywords": (_tp or {}).get("keywords") or [],
            "status": "error",
            "created_at": f.get("failed_at"),
            "updated_at": f.get("failed_at"),
            "generated_at": None,
            "report_count": 0,
            "summary": "",
            "error": f.get("error") or "未知错误",
            "stage": f.get("stage") or "",
        })
    # 按最新刷新时间排序(最近重跑的排最前)，缺失时回退创建时间
    items.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or "", reverse=True)
    return {"reports": items, "count": len(items)}


@router.delete("/saved-report/{slug}")
async def delete_saved_report(slug: str):
    """删除已保存的关键词分析报告（含「失败」记录）。"""
    p = _task_path(slug)
    had_failure = slug in _all_failures()
    if p.exists():
        try:
            p.unlink()
            fp = _facts_path(slug)        # 同时清掉增量事实缓存
            if fp.exists():
                fp.unlink()
            _RUNNING_TASKS.pop(slug, None)
            _clear_failure(slug)
            _delete_topic(slug)           # 同时移除命名主题登记，避免重跑复活
            return {"status": "deleted", "slug": slug}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    # 没有报告文件但存在失败记录：删除这条失败记录（让用户能从生成记录里清掉它）
    if had_failure:
        _clear_failure(slug)
        _RUNNING_TASKS.pop(slug, None)
        _delete_topic(slug)
        return {"status": "deleted", "slug": slug}
    return {"status": "not_found", "slug": slug}


@router.patch("/saved-report/{slug}")
async def rename_saved_report(slug: str, name: str):
    """重命名已保存的关键词分析报告。"""
    d = _load_task(slug)
    if not d:
        return {"status": "not_found", "slug": slug}
    d["display_name"] = name
    _save_task(slug, d)
    return {"status": "ok", "slug": slug, "display_name": name}


@router.get("/report-text/{info_code}")
async def report_text(info_code: str):
    """获取研报抽取正文（前端「查看精读」）：库内优先，缺则按需下载 PDF 再抽取并落库。

    单股研报通常没被产业链精读预下载过，故先读库内缓存，命中即返回；
    未命中则现下载东财 PDF（curl 绕反爬）+ 抽取正文，成功后落库供后续命中。
    返回 ``pdf_url`` 供前端做「打开原文」兜底。
    """
    from quantforge.api import research_lib

    info_code = (info_code or "").strip()
    text = await asyncio.to_thread(research_lib.get_text, info_code)
    if not text:
        text = await asyncio.to_thread(research_lib.fetch_text, info_code)
    return {
        "info_code": info_code,
        "text": text,
        "chars": len(text),
        "pdf_url": PDF_TPL.format(info_code=info_code),
    }


@router.get("/report-pdf/{info_code}")
async def report_pdf(info_code: str):
    """同源代理东财研报 PDF，供前端 <iframe> 直接内嵌阅读。

    东财 PDF 在 EdgeOne CDN 后面有防盗链/反爬：浏览器 iframe 直连会带上本站
    Referer，被判定为盗链而返回 HTTP 567 + 反爬 HTML（无法显示）。后端用已有的
    curl 通道把 PDF 抓下来落地缓存（与文本抽取共用同一份），再由本端点同源吐回，
    即可绕开防盗链、实现「点开直接看 PDF」。命中本地缓存时为纯文件读取，秒开。
    """
    from fastapi.responses import FileResponse, RedirectResponse
    from quantforge.api import research_lib

    info_code = (info_code or "").strip()
    path = await asyncio.to_thread(research_lib.download_pdf, info_code)
    if path and Path(path).exists():
        return FileResponse(
            str(path),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{info_code}.pdf"',
                "Cache-Control": "public, max-age=86400",
            },
        )
    # 兜底：本地抓取失败时，让浏览器顶层跳转到东财原文（顶层导航能过反爬）
    return RedirectResponse(PDF_TPL.format(info_code=info_code))


# ── 研报库（research_pdfs 持久化）检索 ────────────────────────────────────────
@router.get("/library")
async def research_library(
    q: str = None, code: str = None, org: str = None,
    start: str = None, end: str = None, has_text: bool = False,
    sort: str = "date", order: str = "desc",
    page: int = 1, page_size: int = 50,
):
    """检索已入库研报：标题/机构/代码模糊 + 日期区间 + 排序 + 分页。

    - q: 关键词（匹配标题/机构/代码，可用行业词如“电池”近似按行业筛）
    - code: 精确股票代码  · org: 机构名包含
    - start/end: 发布日期区间 YYYY-MM-DD
    - has_text: 仅含已抽取正文的  · sort: date|chars|downloaded
    """
    from quantforge.data.storage import db_cache
    rows, total = await asyncio.to_thread(
        db_cache.research_pdf_query,
        q=q, code=code, org=org, start=start, end=end, has_text=has_text,
        sort_by=sort, order=order, page=page, page_size=page_size,
    )
    return {"reports": rows, "total": total, "page": page, "page_size": page_size}


@router.get("/library/stats")
async def research_library_stats():
    """研报库概览：总数/已抽取/日期区间/Top 机构。"""
    from quantforge.data.storage import db_cache
    return await asyncio.to_thread(db_cache.research_pdf_stats)
