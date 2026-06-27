"""管理后台 API —— 仅管理员账号可访问。

后台模块用于运营视角的横向查看：所有用户、各账号的自选股、各账号的 LLM
token 用量/调用次数等。所有端点都用 ``get_admin_user`` 守卫，非管理员一律
403；前端也据 ``/me`` 返回的 ``is_admin`` 隐藏入口，对其他账号完全不可见。

Endpoints:
  GET /api/admin/overview                 → 全局汇总(用户数/自选总数/token/费用)
  GET /api/admin/users                    → 用户列表(含自选数 + token 用量)
  GET /api/admin/admins                    → 管理员名单(超管/锁定/注册标记)
  POST /api/admin/admins                    → 超管按用户名添加管理员(可预授权)
  DELETE /api/admin/admins/{username}       → 超管撤销某管理员
  POST /api/admin/users/{user_id}/admin    → 超管对已注册账号授予/撤销管理员
  GET /api/admin/users/{user_id}/watchlist → 指定用户的自选股明细
  GET /api/admin/users/{user_id}/chats     → 指定用户的 AI 对话会话列表
  GET /api/admin/chats                     → 全站 AI 对话会话列表
  GET /api/admin/chats/{session_id}        → 某会话完整对话内容
  GET /api/admin/tokens                   → token 用量明细(按账号/按调用方/最近调用)
  GET /api/admin/activity                 → 活跃统计(DAU趋势/活跃概览/功能热度/留存)
"""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from quantforge.api.ai_client import get_llm_stats
from quantforge.api.routes.auth import (
    add_managed_admin,
    get_admin_user,
    get_current_user,
    get_super_admin_user,
    is_env_admin,
    is_super_admin,
    list_admins,
    list_users_public,
    remove_managed_admin,
    set_user_admin,
)
from quantforge.data.storage import db_cache

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_token_map() -> dict[str, dict]:
    """{username: {calls, input_tokens, output_tokens, cost_usd}} 从 LLM 记账聚合。"""
    return get_llm_stats().get("by_user", {})


@router.get("/overview")
async def admin_overview(_: dict = Depends(get_admin_user)):
    """全局汇总卡片用的数据。"""
    users = list_users_public()
    stats = get_llm_stats()
    active = db_cache.activity_active_counts()
    # 自选股总条数(跨所有账号)
    watch_total = 0
    for u in users:
        watch_total += len(db_cache.get_watchlist(u["id"]))
    dau = active.get("dau", 0)
    yesterday = active.get("yesterday", 0)
    mau = active.get("mau", 0)
    return {
        "user_count":          len(users),
        "admin_count":         sum(1 for u in users if u["is_admin"]),
        "watchlist_total":     watch_total,
        "dau":                 dau,
        "dau_yesterday":       yesterday,
        "dau_delta":           dau - yesterday,       # 今日较昨日活跃增减
        "wau":                 active.get("wau", 0),
        "mau":                 mau,
        # 粘性 = DAU/MAU，反映日活在月活里的占比（越高越黏）
        "stickiness":          round(dau / mau, 3) if mau else 0.0,
        "total_calls":         stats.get("total_calls", 0),
        "total_input_tokens":  stats.get("total_input_tokens", 0),
        "total_output_tokens": stats.get("total_output_tokens", 0),
        "total_cost_usd":      stats.get("total_cost_usd", 0.0),
        # 最近 14 天成本/调用趋势，供概览卡片画 sparkline
        "cost_series":         stats.get("daily_series", [])[-14:],
    }


@router.get("/users")
async def admin_users(_: dict = Depends(get_admin_user)):
    """所有用户 + 每个账号的自选数与 token 用量。"""
    users = list_users_public()
    tok = _user_token_map()
    seen = db_cache.activity_user_last_seen()
    out = []
    for u in users:
        wl = db_cache.get_watchlist(u["id"])
        usage = tok.get(u["username"], {})
        act = seen.get(u["username"], {})
        out.append({
            **u,
            "watchlist_count": len(wl),
            "tokens": {
                "calls":         usage.get("calls", 0),
                "input_tokens":  usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cost_usd":      round(usage.get("cost_usd", 0.0), 6),
            },
            "activity": {
                "last_seen":    act.get("last_seen"),
                "active_today": act.get("active_today", False),
                "days_7":       act.get("days_7", 0),
                "days_30":      act.get("days_30", 0),
                "events_30":    act.get("events_30", 0),
            },
        })
    # 最近活跃的排前面（无活跃记录的沉到底），方便运营一眼看到活跃账号
    out.sort(key=lambda x: (x["activity"]["last_seen"] or "", x["tokens"]["calls"]),
             reverse=True)
    return {"users": out, "count": len(out)}


class AdminToggle(BaseModel):
    is_admin: bool


class AdminName(BaseModel):
    username: str


@router.get("/admins")
async def admin_list(_: dict = Depends(get_admin_user)):
    """当前管理员名单（含超管/锁定/是否已注册标记）。管理员均可看，仅超管可改。"""
    admins = list_admins()
    return {"admins": admins, "count": len(admins)}


@router.post("/admins")
async def admin_add(body: AdminName, _: dict = Depends(get_super_admin_user)):
    """超管按用户名添加管理员（对方未注册也可，预授权，登录后即生效）。"""
    name = (body.username or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    add_managed_admin(name)
    admins = list_admins()
    return {"admins": admins, "count": len(admins), "added": name}


@router.delete("/admins/{username}")
async def admin_remove(username: str, current: dict = Depends(get_super_admin_user)):
    """超管撤销某管理员。超管/环境/内置管理员不可撤销；不能撤销自己。"""
    username = (username or "").strip()
    if is_super_admin({"username": username}):
        raise HTTPException(status_code=400, detail="超级管理员不可撤销")
    if is_env_admin(username):
        raise HTTPException(status_code=400, detail="环境/内置管理员不可在后台撤销")
    if username == current["username"]:
        raise HTTPException(status_code=400, detail="不能撤销自己的管理员权限")
    remove_managed_admin(username)
    admins = list_admins()
    return {"admins": admins, "count": len(admins), "removed": username}


@router.post("/users/{user_id}/admin")
async def admin_set_user_admin(
    user_id: str,
    body: AdminToggle,
    current: dict = Depends(get_super_admin_user),
):
    """超管授予 / 撤销某已注册账号的管理员权限（落到可撤销的后台名单）。

    约束：
    - 不能撤销自己的管理员权限，避免把自己锁在门外；
    - 锁定管理员（环境/内置/超管）身份不受此开关影响（返回里标 ``env_admin``）。
    """
    users = {u["id"]: u for u in list_users_public()}
    target = users.get(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not body.is_admin and target["username"] == current["username"]:
        raise HTTPException(status_code=400, detail="不能撤销自己的管理员权限")
    if not body.is_admin and is_env_admin(target["username"]):
        raise HTTPException(status_code=400, detail="环境/内置/超级管理员不可在后台撤销")
    try:
        updated = set_user_admin(user_id, body.is_admin)
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"user": updated}


@router.get("/users/{user_id}/watchlist")
async def admin_user_watchlist(user_id: str, _: dict = Depends(get_admin_user)):
    """指定用户的自选股明细。"""
    users = {u["id"]: u for u in list_users_public()}
    if user_id not in users:
        raise HTTPException(status_code=404, detail="用户不存在")
    items = db_cache.get_watchlist(user_id)
    return {
        "user": users[user_id],
        "items": items,
        "count": len(items),
    }


@router.get("/users/{user_id}/chats")
async def admin_user_chats(user_id: str, _: dict = Depends(get_admin_user)):
    """指定用户的 AI 对话会话列表（按最近活跃倒序）。"""
    users = {u["id"]: u for u in list_users_public()}
    if user_id not in users:
        raise HTTPException(status_code=404, detail="用户不存在")
    sessions = db_cache.chat_sessions(user_id=user_id)
    return {
        "user": users[user_id],
        "sessions": sessions,
        "count": len(sessions),
    }


@router.get("/chats")
async def admin_chats(_: dict = Depends(get_admin_user)):
    """全站 AI 对话会话列表（跨所有用户，按最近活跃倒序）。"""
    sessions = db_cache.chat_sessions()
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/chats/{session_id}")
async def admin_chat_messages(session_id: str, _: dict = Depends(get_admin_user)):
    """某会话的完整对话内容（按顺序）。"""
    messages = db_cache.chat_session_messages(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="会话不存在或无消息")
    return {
        "session_id": session_id,
        "messages": messages,
        "count": len(messages),
    }


@router.get("/activity")
async def admin_activity(days: int = 30, _: dict = Depends(get_admin_user)):
    """活跃统计：DAU 趋势曲线、活跃概览、功能热度、新增/留存。

    ``days`` 控制趋势/功能热度的回看窗口（默认 30 天，最多 90）。留存队列固定看
    最近 14 天。所有数据来自 ``activity_log``，匿名请求与后台自查端点不计入。
    """
    days = max(1, min(int(days), 90))
    return {
        "window_days":  days,
        "active":       db_cache.activity_active_counts(),
        "dau_series":   db_cache.activity_dau_series(days),
        "by_feature":   db_cache.activity_feature_counts(days),
        "retention":    db_cache.activity_retention(14),
    }


# ── 研报分析（仅管理员触发，后台跑，跑完呈现到产业链投研模块）────────────────────
# 复用 routes.research 里已有的关键词精读任务系统（单任务闸门 / slug / 落盘 / 进度），
# 这里只是包一层管理员守卫，让运营在后台输入关键词触发，普通用户进模块只读结果。
@router.post("/research/analyze")
async def admin_research_analyze(
    background_tasks: BackgroundTasks,
    keyword: str = "",
    name: str = "",
    keywords: str = "",
    read_limit: int = 0,
    _: dict = Depends(get_admin_user),
):
    """管理员触发产业链研报精读（后台执行）。

    支持两种用法：
    - 单关键词（兼容旧版）：传 ``keyword``。
    - 命名多关键词主题：传 ``name``（主题名称，可空=取首个关键词）+ ``keywords``
      （多个关键词，支持用 ``,`` / ``、`` / 空格 / 换行 分隔）；**所有关键词都作为
      检索材料**，并集后统一精读，结果存为同一份命名报告。

    read_limit: 精读研报上限，0=全部。返回 slug，前端据此轮询进度，完成后到
    /industry-research 模块查看。
    """
    from quantforge.api.routes import research as R

    # 解析关键词清单：keywords 多分隔符切分；空则回退单 keyword。
    kw_list = [k for k in re.split(r"[,，、\s]+", (keywords or "").strip()) if k]
    if not kw_list and keyword.strip():
        kw_list = [keyword.strip()]
    # 未填关键词但有分析名称：默认用分析名称作为检索关键词
    if not kw_list and name.strip():
        kw_list = [name.strip()]
    display = (name or "").strip() or (keyword.strip() if keyword.strip() else (kw_list[0] if kw_list else ""))
    if not display or not kw_list:
        raise HTTPException(status_code=400, detail="请至少提供一个关键词")

    multi = len(kw_list) > 1 or bool(name.strip())
    # 命名/多关键词主题：登记到注册表，重试/队列/定时可按 slug 还原关键词清单。
    if multi:
        R._save_topic(display, kw_list, read_limit)
    slug = R._slug(display)

    # 并行准入（最多 R._RESEARCH_MAX_CONCURRENT 个同时跑，跨 worker 一致）
    rejected = R._admission_check(slug)
    if rejected:
        rejected.setdefault("keyword", display)
        # 并发已满 → 排进等待队列（跑完一个自动顶上），不再直接拒绝
        if rejected.get("status") == "busy":
            return R._enqueue(display, read_limit, keywords=kw_list if multi else None)
        return rejected
    R._RUNNING_TASKS[slug] = {
        "status": "running", "slug": slug, "keyword": display,
        "stage": "初始化", "progress": 2, "started_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    background_tasks.add_task(R._run_keyword_analysis, display, read_limit,
                             kw_list if multi else None)
    note = "精读全部研报" if read_limit <= 0 else f"精读最多 {read_limit} 篇"
    kw_note = f"，检索关键词 {len(kw_list)} 个" if multi else ""
    return {"status": "started", "slug": slug, "keyword": display,
            "message": f"AI 研报精读已在后台启动（{note}{kw_note}）"}


@router.get("/research/jobs")
async def admin_research_jobs(_: dict = Depends(get_admin_user)):
    """后台研报分析总览：正在跑的任务 + 已生成的报告列表。"""
    from quantforge.api.routes import research as R

    running = [
        {
            "slug": s, "keyword": t.get("keyword", ""),
            "stage": t.get("stage"), "progress": t.get("progress", 0),
            "report_count": t.get("report_count", 0),
            "pdf_count": t.get("pdf_count", 0),
            "read_done": t.get("read_done", 0), "read_total": t.get("read_total", 0),
            "pdf_done": t.get("pdf_done", 0), "pdf_total": t.get("pdf_total", 0),
            # 精读细化：缓存命中 / MAP 待抽总数·已抽 / 机构荐股篇数
            "cached_count": t.get("cached_count"),
            "map_total": t.get("map_total"), "map_done": t.get("map_done"),
            "n_blog": t.get("n_blog"),
            "eta_text": t.get("eta_text"), "eta_seconds": t.get("eta_seconds"),
            "started_at": t.get("started_at"), "updated_at": t.get("updated_at"),
        }
        for s, t in R._RUNNING_TASKS.running_items()
    ]
    running.sort(key=lambda r: r.get("started_at") or r.get("updated_at") or "", reverse=True)
    # 等待队列（手动触发超并发的排队项，按队列次序）
    queue = [
        {"slug": it.get("slug"), "keyword": it.get("keyword", ""),
         "keywords": it.get("keywords") or [],
         "read_limit": it.get("read_limit", 0), "enqueued_at": it.get("enqueued_at"),
         "position": i + 1}
        for i, it in enumerate(R._get_queue())
    ]
    saved = await R.saved_reports()
    return {"running": running, "queue": queue,
            "reports": saved.get("reports", []),
            "max_concurrent": R._RESEARCH_MAX_CONCURRENT}


@router.post("/research/cancel/{slug}")
async def admin_research_cancel(slug: str, force: bool = False,
                               _: dict = Depends(get_admin_user)):
    """中断一个正在运行的产业链分析任务（协作式取消，跨 worker 生效）。

    两段式，避免「停止中」卡死：
    - 首次调用（取消标志未置位）：置标志 + 把阶段标记为「取消中…」，由活着的 worker
      在下个检查点落 cancelled 终态。
    - 再次调用 **或** force=true（标志已置位却迟迟没落终态，多半是僵尸记录/卡在无
      检查点阶段）：**强制**直接写 cancelled 终态并清标志，立即解除前端卡住。
      强制只动进度记录、不动已生成报告；若那一刻真有活协程，它下个检查点也会自行退出。
    """
    from quantforge.api.routes import research as R

    running = R._RUNNING_TASKS.get(slug)
    if not running or running.get("status") != "running":
        return {"status": "not_running", "slug": slug, "message": "该任务未在运行"}

    already_requested = R._is_cancel_requested(slug)
    if force or already_requested:
        # 强制落终态：覆盖运行记录为 cancelled（终态会进 TTL 自愈清理）。
        # **保留**取消标志（不清）：万一那一刻任务其实还活着、只是卡在无检查点阶段，
        # 标志留着能让它在下个检查点自行抛出退出，而不会因为「标志没了」在下次 upd
        # 时又把 running 记录重新写回来（看起来像「强制结束后又复活」）。残留的标志由
        # 该 slug 下次启动时 _run_keyword_analysis 开头的 _clear_cancel 统一清掉。
        R._request_cancel(slug)
        R._RUNNING_TASKS[slug] = {
            "status": "cancelled", "slug": slug, "keyword": running.get("keyword", ""),
            "stage": "已取消（强制）", "progress": 100,
            "updated_at": datetime.now().isoformat(),
        }
        return {"status": "forced", "slug": slug, "keyword": running.get("keyword", ""),
                "message": "已强制结束该任务"}

    R._request_cancel(slug)
    # 即时反馈：把阶段标记为取消中（保持 running 状态，等 worker 落终态）
    try:
        rec = dict(running)
        rec["stage"] = "取消中…"
        rec["updated_at"] = datetime.now().isoformat()
        R._RUNNING_TASKS[slug] = rec
    except Exception:
        pass
    return {"status": "cancelling", "slug": slug, "keyword": running.get("keyword", ""),
            "message": "已请求中断，任务将在下个检查点停止；若长时间停在「取消中」，再点一次可强制结束"}


@router.delete("/research/queue/{slug}")
async def admin_research_dequeue(slug: str, _: dict = Depends(get_admin_user)):
    """把一个尚未开始的关键词移出等待队列。"""
    from quantforge.api.routes import research as R

    ok = R._dequeue(slug)
    return {"status": "removed" if ok else "not_found", "slug": slug,
            "message": "已移出等待队列" if ok else "队列中没有该任务"}


@router.post("/research/queue/{slug}/move")
async def admin_research_queue_move(slug: str, direction: str = "up",
                                    _: dict = Depends(get_admin_user)):
    """调整等待队列里某项的优先级：direction = up/down/top/bottom（队首=下一个开跑）。"""
    from quantforge.api.routes import research as R

    return R._move_in_queue(slug, direction)


@router.delete("/research/jobs/{slug}")
async def admin_research_delete(slug: str, _: dict = Depends(get_admin_user)):
    """删除一份已生成的研报分析报告。"""
    from quantforge.api.routes import research as R

    return await R.delete_saved_report(slug)


# ── 每日定时关键词清单 ───────────────────────────────────────────────────────
# 模型：每日清单**默认 = 全部已生成报告主题 ∪ 手动新增关键词 − 已移除项**。
# 新生成的报告自动纳入；手动可加额外关键词（尚无报告也行）、可移除任意项（落排除集，
# 不会被「默认全部」重新带回）。下面接口都返回「生效清单」，manual=是否手动新增项。
def _daily_payload(R) -> dict:
    kws = R._get_daily_keywords()
    extra_slugs = {R._slug(k) for k in R._get_daily_extra_keywords()}
    excluded = R._get_daily_excluded()
    return {
        "keywords": [{"keyword": kw, "slug": R._slug(kw),
                      "manual": R._slug(kw) in extra_slugs} for kw in kws],
        "count": len(kws),
        "excluded_count": len(excluded),
    }


@router.get("/research/daily-keywords")
async def admin_daily_keywords(_: dict = Depends(get_admin_user)):
    """当前生效的每日定时清单（默认含全部历史报告主题；manual 标记手动新增项）。"""
    from quantforge.api.routes import research as R

    return _daily_payload(R)


@router.post("/research/daily-keywords")
async def admin_daily_keywords_add(keyword: str, _: dict = Depends(get_admin_user)):
    """新增一个每日关键词（尚无报告也可加）；若此前被移除则一并恢复。"""
    from quantforge.api.routes import research as R

    keyword = (keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="关键词不能为空")
    slug = R._slug(keyword)
    # 取消其排除（若曾被移除）
    excluded = R._get_daily_excluded()
    if slug in excluded:
        excluded.discard(slug)
        R._set_daily_excluded(excluded)
    # 记入手动新增（按 slug 去重）
    extras = R._get_daily_extra_keywords()
    if slug not in {R._slug(k) for k in extras}:
        extras.append(keyword)
        R._set_daily_extra_keywords(extras)
    return _daily_payload(R)


@router.post("/research/daily-keywords/include-all")
async def admin_daily_keywords_include_all(_: dict = Depends(get_admin_user)):
    """一键纳入全部历史：清空「已移除」集合，让所有已生成报告主题重新进入每日定时。"""
    from quantforge.api.routes import research as R

    before = len(R._get_daily_excluded())
    R._set_daily_excluded(set())
    payload = _daily_payload(R)
    payload["restored_count"] = before
    return payload


@router.delete("/research/daily-keywords/{keyword}")
async def admin_daily_keywords_remove(keyword: str, _: dict = Depends(get_admin_user)):
    """从每日定时清单移除一个主题：记入排除集（默认全部纳入时不再带回）+ 从手动新增里删除。

    注意：仅移出定时清单，不删除已生成的报告；如需一并清掉报告，另调
    ``DELETE /research/jobs/{slug}``。
    """
    from quantforge.api.routes import research as R

    keyword = (keyword or "").strip()
    slug = R._slug(keyword)
    extras = [k for k in R._get_daily_extra_keywords() if R._slug(k) != slug]
    R._set_daily_extra_keywords(extras)
    excluded = R._get_daily_excluded()
    excluded.add(slug)
    R._set_daily_excluded(excluded)
    payload = _daily_payload(R)
    payload["removed"] = keyword
    return payload


# ── AI 荐股（仅管理员重跑；例行由计划任务定时跑，对外页面只读最新结果）──────────
# 把原本暴露在 /ai-picks 页面的「重新分析」收口到后台：复用 routes.ai_picks 的
# 生成逻辑（全市场扫描 + 时段缓存 + 单任务闸门），这里只加一层管理员守卫。
@router.post("/ai-picks/refresh")
async def admin_ai_picks_refresh(
    background_tasks: BackgroundTasks,
    force: bool = True,
    strategy: str = "momentum",
    _: dict = Depends(get_admin_user),
):
    """管理员手动重跑 AI 荐股（后台执行）。默认 force=true 强制重生成当前时段。

    ``strategy`` 指定荐股策略（momentum / pring / ultra / probe，全部可重跑），
    转交底层按策略维度生成与缓存（ultra/probe 为纯规则、不走 AI）。
    """
    from quantforge.api.routes import ai_picks as P

    return await P.refresh_picks(background_tasks, force=force, strategy=strategy)


@router.get("/ai-picks/status")
async def admin_ai_picks_status(strategy: str = "momentum", _: dict = Depends(get_admin_user)):
    """AI 荐股当前状态：是否在跑 / 当前时段 / 最新一份的生成时间与只数 / 扫描覆盖度。"""
    from quantforge.api.routes import ai_picks as P

    return await P.get_status(strategy=strategy)


@router.get("/ai-picks/history")
async def admin_ai_picks_history(strategy: str | None = None, _: dict = Depends(get_admin_user)):
    """AI 荐股历次生成记录（日期/时段/策略/荐股数），按时间倒序。

    与产业链分析的「已生成报告」列表对应：管理员在后台审视每一次生成的产出。
    ``strategy`` 给定时只返回该策略；为空时返回全部（含策略标记）。
    """
    from quantforge.api.routes import ai_picks as P

    return await P.get_history(strategy=strategy)


@router.post("/heartbeat")
async def admin_heartbeat(current: dict = Depends(get_current_user)):
    """任何已登录用户的在线心跳（非管理员专用）。前端每 30 s 调一次，用于统计在线状态与在线时长。"""
    result = db_cache.heartbeat(current["username"])
    return {"ok": True, **result}


@router.get("/presence")
async def admin_presence(_: dict = Depends(get_admin_user)):
    """当前在线用户列表（90 s 内有心跳即视为在线）。仅管理员可查。"""
    users = db_cache.get_online_users()
    return {"online": users, "count": len(users)}


@router.get("/query-distribution")
async def admin_query_distribution(days: int = 7, _: dict = Depends(get_admin_user)):
    """查询量级与分布：近 days 天按小时的请求量分布 + 量级摘要。"""
    days = max(1, min(int(days), 90))
    return {
        "window_days": days,
        "hourly": db_cache.activity_hourly_distribution(days),
        "volume": db_cache.activity_query_volume(days),
        "by_feature": db_cache.activity_feature_counts(days),
    }


@router.get("/tokens")
async def admin_tokens(_: dict = Depends(get_admin_user)):
    """token 用量明细：按账号、按调用方、最近调用记录。"""
    stats = get_llm_stats()
    return {
        "total_calls":         stats.get("total_calls", 0),
        "total_input_tokens":  stats.get("total_input_tokens", 0),
        "total_output_tokens": stats.get("total_output_tokens", 0),
        "total_cost_usd":      stats.get("total_cost_usd", 0.0),
        "by_user":             stats.get("by_user", {}),
        "by_caller":           stats.get("by_caller", {}),
        "by_model":            stats.get("by_model", {}),
        "daily_series":        stats.get("daily_series", []),
        "recent_calls":        list(reversed(stats.get("recent_calls", []))),
    }
