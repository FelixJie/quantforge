"""Unified AI client — supports OpenAI-compatible and Anthropic protocols.

Configure via (priority order):
  1. data/cache/llm_config.json  — runtime config saved via /api/llm-stats/config
  2. Environment variables: ARK_API_KEY, ARK_BASE_URL, AI_MODEL
  3. Hardcoded defaults

LLM cost tracking is stored in data/cache/llm_costs.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import datetime as _dt
from pathlib import Path

from loguru import logger

# ── Built-in provider presets ───────────────────────────────────────────────────
# Selectable via config "provider" field. The default preset is used when no
# provider/override is configured.
_PRESETS: dict[str, dict] = {
    "deepseek-v4-pro": {
        "label":    "DeepSeek V4 Pro",
        "base_url": "https://api.deepseek.com",
        "api_key":  os.getenv("DEEPSEEK_API_KEY", ""),
        "model":    "deepseek-v4-pro",
    },
    "minimax-m3": {
        "label":    "MiniMax M3",
        "base_url": "https://api.minimaxi.com/anthropic",
        # key 优先 MINIMAX_API_KEY；回退 ANTHROPIC_API_KEY —— .env 里 minimax 的
        # 凭证用的是 ANTHROPIC_* 变量名(ANTHROPIC_BASE_URL 已指向 api.minimaxi.com)。
        "api_key":  os.getenv("MINIMAX_API_KEY") or os.getenv("ANTHROPIC_API_KEY", ""),
        "model":    "MiniMax-M3",
    },
}
# MiniMax-M3 is the default lead provider (DeepSeek 账号长期欠费 402，仅作兜底)。
# config(llm_config.json provider) 仍可覆盖；这里改硬编码默认避免 config 丢失时
# 误用欠费的 DeepSeek。
_DEFAULT_PRESET = "minimax-m3"

_DEFAULT_BASE_URL = _PRESETS[_DEFAULT_PRESET]["base_url"]
_DEFAULT_API_KEY  = _PRESETS[_DEFAULT_PRESET]["api_key"]
_DEFAULT_MODEL    = _PRESETS[_DEFAULT_PRESET]["model"]

# 过载(529/overloaded)退避重试：MiniMax 高峰会临时 529，重试大概率能成，
# 避免立刻跌到欠费的 DeepSeek 备用号。仅对过载类错误生效。
_OVERLOAD_RETRIES = 3
_OVERLOAD_BACKOFF = [2, 5, 10]   # 秒；第 N 次重试前等待

# 「耐心重试」档（后台长任务专用，patient=True 才启用）：碰到 429（MiniMax Token Plan
# 限流，额度够时只是 TPM/RPM 触顶，等一会就恢复）等过载类错误**不放弃**——开始每 5 分钟
# 重试一次，30 分钟后改每半小时一次，扛过限流窗口让流程不断。短任务(chat UI)不开此档。
# 总上限 ~6.5h(6×5min + 12×30min)，仍不行才真正失败回退。可经 env 覆盖间隔/次数。
_PATIENT_SHORT = int(os.getenv("QF_PATIENT_SHORT_SEC") or 300)    # 前段间隔(默认5分钟)
_PATIENT_LONG = int(os.getenv("QF_PATIENT_LONG_SEC") or 1800)     # 后段间隔(默认半小时)
_PATIENT_SHORT_N = int(os.getenv("QF_PATIENT_SHORT_N") or 6)      # 前段重试次数(默认6=覆盖30分钟)
_PATIENT_LONG_N = int(os.getenv("QF_PATIENT_LONG_N") or 12)       # 后段重试次数(默认12=覆盖6小时)
_PATIENT_BACKOFF = [_PATIENT_SHORT] * _PATIENT_SHORT_N + [_PATIENT_LONG] * _PATIENT_LONG_N


async def _interruptible_sleep(total: float, cancel_cb=None, on_tick=None,
                               chunk: float = 20.0) -> None:
    """分块睡 ``total`` 秒：每 ``chunk`` 秒查一次 ``cancel_cb``（返回 True 则抛
    CancelledError 干净中断），并调 ``on_tick``（心跳，刷新任务进度防僵尸 TTL 误杀）。

    用于「耐心重试」的长等待（可达半小时）：不能用一个裸 sleep——否则取消要干等、且
    长于僵尸阈值会被判死。分块 + 回调两个问题一并解决。
    """
    import asyncio
    slept = 0.0
    while slept < total:
        if cancel_cb and cancel_cb():
            raise asyncio.CancelledError()
        dt = min(chunk, total - slept)
        await asyncio.sleep(dt)
        slept += dt
        if on_tick:
            try:
                on_tick()
            except Exception:
                pass
    if cancel_cb and cancel_cb():
        raise asyncio.CancelledError()


def _is_overloaded(e: Exception) -> bool:
    """判定是否为临时性服务端错误(值得对同一 provider 退避重试)。

    MiniMax 高峰会轮流抛 529 过载 / 500(内含 520) / 502 / 503 / 429 限流——
    都是瞬时的，重试大概率能成，避免立刻跌到欠费的 DeepSeek 备用号。
    **不含** 402 欠费 / 401 鉴权 / 400 参数 这类重试也没用的硬错误。
    """
    s = f"{type(e).__name__} {e}".lower()
    if any(code in s for code in ("402", "401", "400", "insufficient", "invalid api")):
        return False
    return (
        "529" in s or "overloaded" in s
        or "429" in s or "rate limit" in s or "too many requests" in s
        or "500" in s or "502" in s or "503" in s or "520" in s
        or "internalservererror" in s or "api_error" in s
        or "timeout" in s or "timed out" in s
    )

_COST_FILE   = Path("data/cache/llm_costs.json")
_CONFIG_FILE = Path("data/cache/llm_config.json")


def get_presets() -> list[dict]:
    """Return selectable provider presets (api_key masked) for the UI."""
    out = []
    for name, p in _PRESETS.items():
        key = p["api_key"]
        out.append({
            "id":       name,
            "label":    p["label"],
            "base_url": p["base_url"],
            "model":    p["model"],
            "api_key":  key[:8] + "****" + key[-4:] if len(key) > 12 else "****",
        })
    # Claude Code 本地 provider（特殊：无 base_url/api_key，走子进程）。available
    # 反映本机是否装/登录了 claude；local_only 提示前端它在服务器上不可用。
    out.append({
        "id":         _CLAUDE_CODE,
        "label":      "Claude Code (本地 Opus 4.8)",
        "base_url":   "local-cli",
        "model":      _claude_code_model(),
        "api_key":    "本地登录",
        "available":  _claude_code_available(),
        "local_only": True,
    })
    return out


def _load_config() -> dict:
    """Load runtime config from JSON file (written by /api/llm-stats/config PUT)."""
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    """Persist config to JSON file."""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

# Approximate cost per 1K tokens in USD (adjust as needed)
_COST_PER_1K_INPUT  = 0.001
_COST_PER_1K_OUTPUT = 0.002


def _effective() -> dict:
    """Resolve the effective {provider, base_url, api_key, model}.

    Resolution order:
      1. If config selects a known provider preset → use that preset wholesale.
      2. Otherwise (custom/legacy) → per-field config, then env, then default preset.
    """
    cfg = _load_config()
    provider = cfg.get("provider")
    if provider and provider in _PRESETS:
        p = _PRESETS[provider]
        return {"provider": provider, "base_url": p["base_url"],
                "api_key": p["api_key"], "model": p["model"]}
    return {
        "provider": provider or "custom",
        "base_url": cfg.get("base_url") or os.getenv("ARK_BASE_URL") or _DEFAULT_BASE_URL,
        "api_key":  cfg.get("api_key")  or os.getenv("ARK_API_KEY")  or _DEFAULT_API_KEY,
        "model":    cfg.get("model")    or os.getenv("AI_MODEL")     or _DEFAULT_MODEL,
    }


def _fallback_chain(lead: str | None = None) -> list[dict]:
    """Ordered providers to try: the effective one first, then the rest.

    "Mutual" fallback — whichever provider is configured leads, the others back
    it up. If the lead call fails (402/timeout/network/empty reply), chat() moves
    to the next entry. Returns list of {provider, base_url, api_key, model}.

    ``lead`` — optional preset name (e.g. "minimax-m3") to force as the leading
    provider for this call only, regardless of global config. The other presets
    still follow as fallbacks. Unknown name falls back to the effective provider.
    """
    if lead and lead in _PRESETS:
        p = _PRESETS[lead]
        eff = {"provider": lead, "base_url": p["base_url"],
               "api_key": p["api_key"], "model": p["model"]}
    else:
        eff = _effective()
    chain = [eff]
    seen_keys = {(eff["base_url"], eff["model"])}
    for name, p in _PRESETS.items():
        key = (p["base_url"], p["model"])
        if key in seen_keys:
            continue
        # 跳过没有 api_key 的预设——MiniMax 是默认主力，DeepSeek 账号长期欠费且
        # 多半没配 DEEPSEEK_API_KEY，空 key 进链只会每次抛 "Authentication Fails"
        # 的噪声日志。配上 key 后它会自动重新作为兜底加入。
        if not (p.get("api_key") or "").strip():
            continue
        seen_keys.add(key)
        chain.append({"provider": name, "base_url": p["base_url"],
                      "api_key": p["api_key"], "model": p["model"]})
    return chain


def get_base_url() -> str:
    return _effective()["base_url"]


def get_api_key() -> str:
    return _effective()["api_key"]


def get_model() -> str:
    return _effective()["model"]


def get_config() -> dict:
    """Return current effective config (for display, api_key masked)."""
    eff = _effective()
    key = eff["api_key"]
    return {
        "provider": eff["provider"],
        "base_url": eff["base_url"],
        "api_key":  key[:8] + "****" + key[-4:] if len(key) > 12 else "****",
        "api_key_raw": key,
        "model":    eff["model"],
        "presets":  get_presets(),
    }


def _is_anthropic() -> bool:
    """Check if current base_url uses Anthropic protocol."""
    url = get_base_url()
    return url.endswith("/anthropic") or "anthropic" in url.lower()


def _is_anthropic_url(url: str) -> bool:
    return url.endswith("/anthropic") or "anthropic" in url.lower()


# 单次 LLM 请求超时（秒）。SDK 默认可达 10 分钟，慢/卡住的请求会一直占住
# 一个线程池线程；产业链全量精读会并发上百次 LLM 调用，无超时会把线程池占满
# → 整个后端无响应。给一个偏紧的上限，超时即报错触发回退/丢弃单篇。
_LLM_TIMEOUT = float(os.getenv("QF_LLM_TIMEOUT") or 90)


def _build_client_for(prov: dict, timeout: float | None = None):
    """Build a client for an explicit provider dict ({base_url, api_key, ...}).

    ``timeout`` overrides the default per-request timeout for a single call —
    used by slow/large single-shot jobs (e.g. ai_picks) that legitimately need
    longer than the tight bulk-concurrency default.
    """
    to = timeout or _LLM_TIMEOUT
    if _is_anthropic_url(prov["base_url"]):
        from anthropic import Anthropic
        return Anthropic(api_key=prov["api_key"], base_url=prov["base_url"],
                         timeout=to, max_retries=0)
    else:
        from openai import OpenAI
        return OpenAI(api_key=prov["api_key"], base_url=prov["base_url"],
                      timeout=to, max_retries=0)


def build_client():
    """Return a configured client based on the protocol (effective provider)."""
    return _build_client_for(_effective())


# ── Cost tracking ──────────────────────────────────────────────────────────────

def _load_costs() -> dict:
    if _COST_FILE.exists():
        try:
            return json.loads(_COST_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0, "calls": []}


def _save_costs(data: dict) -> None:
    try:
        _COST_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COST_FILE.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


def _record_cost(caller: str, model: str, input_tokens: int, output_tokens: int,
                 user: str | None = None) -> None:
    cost_usd = (input_tokens / 1000) * _COST_PER_1K_INPUT + (output_tokens / 1000) * _COST_PER_1K_OUTPUT
    data = _load_costs()
    data["total_input_tokens"]  = data.get("total_input_tokens", 0) + input_tokens
    data["total_output_tokens"] = data.get("total_output_tokens", 0) + output_tokens
    data["total_cost_usd"]      = round(data.get("total_cost_usd", 0.0) + cost_usd, 6)
    entry = {
        "ts":            _dt.datetime.now().isoformat(timespec="seconds"),
        "caller":        caller,
        "user":          user or "",       # 归属账号(用户名)；后台/系统任务为空
        "model":         model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "cost_usd":      round(cost_usd, 6),
    }
    calls: list = data.setdefault("calls", [])
    calls.append(entry)
    # Keep only last 500 call records to bound file size
    if len(calls) > 500:
        data["calls"] = calls[-500:]
    _save_costs(data)


def get_llm_stats() -> dict:
    """Return aggregated LLM usage statistics."""
    data = _load_costs()
    calls = data.get("calls", [])

    def _agg(key_fn, default_key):
        out: dict[str, dict] = {}
        for c in calls:
            key = key_fn(c) or default_key
            if key not in out:
                out[key] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            out[key]["calls"] += 1
            out[key]["input_tokens"]  += c.get("input_tokens", 0)
            out[key]["output_tokens"] += c.get("output_tokens", 0)
            out[key]["cost_usd"]      = round(out[key]["cost_usd"] + c.get("cost_usd", 0.0), 6)
        return out

    # 日次趋势：用每条记录 ts 的日期前缀聚合，供后台画成本/调用 sparkline。
    daily: dict[str, dict] = {}
    for c in calls:
        day = (c.get("ts") or "")[:10]
        if not day:
            continue
        d = daily.setdefault(day, {"calls": 0, "cost_usd": 0.0,
                                   "input_tokens": 0, "output_tokens": 0})
        d["calls"]         += 1
        d["cost_usd"]       = round(d["cost_usd"] + c.get("cost_usd", 0.0), 6)
        d["input_tokens"]  += c.get("input_tokens", 0)
        d["output_tokens"] += c.get("output_tokens", 0)
    daily_series = [{"day": k, **v} for k, v in sorted(daily.items())]

    return {
        "total_calls":         len(calls),
        "total_input_tokens":  data.get("total_input_tokens", 0),
        "total_output_tokens": data.get("total_output_tokens", 0),
        "total_cost_usd":      data.get("total_cost_usd", 0.0),
        "by_caller":           _agg(lambda c: c.get("caller"), "unknown"),
        "by_user":             _agg(lambda c: c.get("user"), "系统/后台"),
        "by_model":            _agg(lambda c: c.get("model"), "unknown"),
        "daily_series":        daily_series,
        "recent_calls":        calls[-20:],
    }


# ── Claude Code 本地 CLI provider ────────────────────────────────────────────────
# 走本机已登录的 Claude Code（Opus 4.8 订阅），用子进程 `claude -p` 一次性出文。
# 仅本地可用：服务器上没有 claude 二进制 / 未登录 → _claude_code_available() 为 False，
# chat() 自动跌回 HTTP 链（MiniMax）。无需在服务器做任何特殊处理。
#
# 关键坑：本项目 .env 把 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL 借给了 MiniMax
# （指向 api.minimaxi.com）。若把这些变量原样传给 claude 子进程，claude 会用
# MiniMax 的 key/url 而非本机 OAuth 登录 → 既不是 Opus 也会鉴权乱。故子进程环境
# 必须**剥掉** ANTHROPIC_* 这些变量，强制 claude 回退到它自己存储的订阅登录。
_CLAUDE_CODE = "claude-code"
# 子进程并发上限：Opus 子进程重，产业链 MAP 阶段会并发上百次，无上限会瞬间起一堆
# claude 进程拖垮本机。给一个偏小的闸门，超出的排队。可经环境变量覆盖。
_CC_CONCURRENCY = int(os.getenv("QF_CLAUDE_CODE_CONCURRENCY") or 3)
_cc_sem: asyncio.Semaphore | None = None
# 在中性临时目录里跑，避免 claude 自动发现并加载本项目的 CLAUDE.md / auto-memory /
# 钩子，污染产业链分析的上下文，也更快。
_CC_WORKDIR = Path(tempfile.gettempdir()) / "qf_claude_code"
# 子进程默认超时（秒）：Opus 推理较慢，产业链 REDUCE 合成给足时间。
_CC_TIMEOUT = float(os.getenv("QF_CLAUDE_CODE_TIMEOUT") or 300)


def _claude_code_bin() -> str | None:
    """返回 claude CLI 路径（QF_CLAUDE_CODE_BIN 覆盖，否则 PATH 查找）。"""
    explicit = os.getenv("QF_CLAUDE_CODE_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("claude")


def _claude_code_model() -> str:
    return os.getenv("QF_CLAUDE_CODE_MODEL") or "claude-opus-4-8"


# ── 模型质量分级（MAP 阶段缓存复用判定）─────────────────────────────────────────
# 缓存里记录了抽取时所用模型；本轮要复用时，只要缓存模型质量 ≥ 目标即可复用，
# 不降级重跑。等级数字越大越好。有序列表(子串→分)便于以后扩展新模型；命中
# 第一个即返回。子串匹配大小写不敏感，能覆盖带后缀的名字(如 "...(cc)")。
_MODEL_TIERS: list[tuple[str, int]] = [
    ("opus",     100),
    ("deepseek",  60),
    ("minimax",   50),
]


def model_tier(model: str) -> int:
    """返回模型质量等级(数字越大越好)；无命中或空名 → 10。"""
    s = (model or "").lower()
    for sub, tier in _MODEL_TIERS:
        if sub in s:
            return tier
    return 10


def provider_to_model(provider: str | None) -> str:
    """给定 provider 名，返回它实际会使用的 model 名(供上层算 want_tier)。

    - "claude-code" → 本机 Claude Code 模型
    - 已知预设名     → 该预设的 model
    - 其它(None/custom/未知) → 全局 effective model
    """
    if provider == _CLAUDE_CODE:
        return _claude_code_model()
    if provider and provider in _PRESETS:
        return _PRESETS[provider]["model"]
    return get_model()


def _claude_code_available() -> bool:
    """本机是否可用 Claude Code provider（二进制存在且未被显式禁用）。"""
    if os.getenv("QF_DISABLE_CLAUDE_CODE"):
        return False
    return _claude_code_bin() is not None


def _cc_child_env() -> dict:
    """子进程环境：剥掉被 MiniMax 借用的 ANTHROPIC_* 变量，强制走本机订阅登录。"""
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
              "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
              "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
        env.pop(k, None)
    return env


async def _claude_code_chat(system: str, user: str, max_tokens: int,
                            caller: str, account: str | None,
                            timeout: float | None) -> str:
    """用 `claude -p` 子进程出文，返回正文。失败抛异常以触发 HTTP 回退。"""
    bin_path = _claude_code_bin()
    if not bin_path:
        raise RuntimeError("claude code CLI not found")
    global _cc_sem
    if _cc_sem is None:
        _cc_sem = asyncio.Semaphore(_CC_CONCURRENCY)
    try:
        _CC_WORKDIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    model = _claude_code_model()
    # 长/多行 system **不能走命令行**：Windows 下 claude.CMD(batch wrapper) 经 cmd.exe
    # 解析，system 里的换行/超长会截断参数行、丢失后面的 --output-format json → claude
    # 退回默认 text 格式吐 markdown，json.loads 当场失败。故把 system 写**临时文件**用
    # --system-prompt-file 传（每次调用独立文件名，MAP 并发也安全），命令行只剩短参数。
    #
    # 超大 user（REDUCE 几万字全量摘要）同样不能走 stdin：Windows pipe / claude CLI
    # 内部对超大 stdin 有限制，会导致 exit 1 或截断。阈值以上改为把 user 追写进
    # system 文件（磁盘读取无大小限制），stdin 只传一句短指令。
    _LARGE_USER = 20_000  # chars
    fd, sys_path = tempfile.mkstemp(dir=str(_CC_WORKDIR), prefix="sys_", suffix=".txt")
    os.close(fd)
    if len(user) > _LARGE_USER:
        Path(sys_path).write_text(
            system + "\n\n===以下是分析所需数据（请基于此生成JSON报告）===\n\n" + user,
            encoding="utf-8",
        )
        stdin_bytes = "请严格按照system prompt中的schema输出JSON，不输出其他内容。".encode("utf-8")
    else:
        Path(sys_path).write_text(system, encoding="utf-8")
        stdin_bytes = user.encode("utf-8")
    args = [
        bin_path, "-p",
        "--system-prompt-file", sys_path,
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        "--setting-sources", "",      # 不加载 user/project/local 设置
        "--disable-slash-commands",   # 关掉 skills
        "--tools", "",                # 禁用全部工具 → 纯文本生成，不读盘不跑命令
    ]

    try:
        async with _cc_sem:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_CC_WORKDIR),
                env=_cc_child_env(),
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(input=stdin_bytes),
                    timeout=timeout or _CC_TIMEOUT,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise RuntimeError("claude code CLI timed out")
    finally:
        try:
            os.unlink(sys_path)
        except Exception:
            pass

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude code CLI exit {proc.returncode}: {err.decode('utf-8', 'ignore')[:200]}")

    raw_out = out.decode("utf-8", "ignore")
    try:
        data = json.loads(raw_out)
    except json.JSONDecodeError:
        # 仍非 JSON（理论上不应再发生）→ 报清晰错误带输出头，便于定位
        raise RuntimeError(f"claude code non-JSON output (head={raw_out[:120]!r})")
    if data.get("is_error"):
        raise RuntimeError(f"claude code error: {str(data.get('result'))[:200]}")
    text = data.get("result") or ""
    if not str(text).strip():
        raise RuntimeError("empty reply from claude code")

    usage = data.get("usage") or {}
    in_tok = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
    out_tok = int(usage.get("output_tokens") or 0)
    _record_cost(caller=caller, model=f"{model} (cc)",
                 input_tokens=in_tok, output_tokens=out_tok, user=account)
    return text


def get_research_provider() -> str | None:
    """产业链分析专用 provider（后台 research_provider 配置）；空=用全局链。"""
    p = (_load_config().get("research_provider") or "").strip()
    return p or None


# ── Chat interface ─────────────────────────────────────────────────────────────

async def chat(
    system: str,
    user: str,
    max_tokens: int = 1024,
    caller: str = "unknown",
    images: list[str] | None = None,
    account: str | None = None,
    timeout: float | None = None,
    provider: str | None = None,
    patient: bool = False,
    cancel_cb=None,
    on_wait=None,
) -> str:
    """Send a chat message and return the assistant reply text.

    Args:
        system: System prompt.
        user: User message.
        max_tokens: Max response tokens.
        caller: Label for cost tracking (e.g. 'ai_picks', 'yaml_strategy').
        images: Optional list of base64-encoded images for Vision LLM calls.
        account: Username to attribute token usage to (admin console). None for
            background/system tasks.
        timeout: Per-request timeout override (seconds). Defaults to the tight
            bulk-safe limit; pass a larger value for slow single-shot jobs.
        provider: Optional preset name (e.g. "minimax-m3") to lead the call with,
            ignoring global config for this call only. Other presets still back
            it up as fallbacks. Special value "claude-code" routes to the local
            Claude Code CLI (Opus 4.8); unavailable (e.g. on server) → HTTP chain.
        patient: 开启「耐心重试」档——过载/429 限流时按 _PATIENT_BACKOFF 长等待重试
            （每 5 分钟→每半小时，~6.5h 上限），让后台长任务(MAP/REDUCE)扛过限流不中断。
            短任务勿开（会把请求阻塞很久）。
        cancel_cb: 返回 True 表示用户已请求取消；耐心等待期间每 ~20s 探一次，命中即抛
            CancelledError 干净退出（避免长睡眠期间无法中断）。
        on_wait: 每个等待分片回调一次（心跳），用于刷新任务 updated_at，防长等待被僵尸
            TTL 误判清理。
    """
    # Claude Code 本地 provider：显式请求或全局配置选中时优先走它（本地 Opus 4.8）。
    # 图文消息 CLI 不便传，直接跳过走 HTTP。本机不可用（服务器）则静默跌回 HTTP 链。
    want_cc = (provider == _CLAUDE_CODE) or (
        provider is None and _effective().get("provider") == _CLAUDE_CODE)
    if want_cc and not images and _claude_code_available():
        try:
            return await _claude_code_chat(system, user, max_tokens, caller, account, timeout)
        except Exception as e:
            logger.warning(f"ai chat: claude-code provider failed ({type(e).__name__}: "
                           f"{str(e)[:120]}); falling back to HTTP chain for caller={caller}")

    chain = _fallback_chain(None if provider == _CLAUDE_CODE else provider)
    last_err: Exception | None = None

    for idx, prov in enumerate(chain):
        client = _build_client_for(prov, timeout)
        model = prov["model"]
        is_anthropic = _is_anthropic_url(prov["base_url"])

        def _call():
            if is_anthropic:
                if images:
                    # Anthropic 协议的图文消息：图片块在前、文本块在后。
                    a_content: list = [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/jpeg", "data": b}}
                        for b in images
                    ]
                    a_content.append({"type": "text", "text": user})
                else:
                    a_content = user
                return client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": a_content}],
                )
            if images:
                content = [{"type": "text", "text": user}]
                for img_b64 in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                    })
            else:
                content = user
            return client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": content},
                ],
            )

        try:
            # 过载(529/overloaded)是临时的 → 对**同一 provider** 退避重试，
            # 不立刻跌到下一个(可能欠费的)备用号。仅过载类错误重试，其它直接回退。
            # patient=True 走「耐心重试」长档（每 5 分钟→每半小时，扛过 429 限流，流程不断）。
            backoff = _PATIENT_BACKOFF if patient else _OVERLOAD_BACKOFF
            max_retries = len(backoff) if patient else _OVERLOAD_RETRIES
            resp = None
            for attempt in range(max_retries + 1):
                try:
                    resp = await asyncio.to_thread(_call)
                    break
                except Exception as inner:
                    if attempt < max_retries and _is_overloaded(inner):
                        wait = backoff[min(attempt, len(backoff) - 1)]
                        logger.warning(
                            f"ai chat: provider '{prov.get('provider')}' overloaded/limited "
                            f"({type(inner).__name__}), {'patient ' if patient else ''}"
                            f"retry {attempt + 1}/{max_retries} in {wait}s (caller={caller})"
                        )
                        await _interruptible_sleep(wait, cancel_cb, on_wait)
                        continue
                    raise

            if is_anthropic:
                # 仅取 text 块；带思考的模型(如 MiniMax)会先返回 thinking 块，
                # 它没有 text 内容，需跳过，否则正文会被漏掉/拼成空。
                text = ""
                for block in resp.content:
                    if getattr(block, "type", None) == "text":
                        text += getattr(block, "text", "") or ""
                    elif getattr(block, "type", None) is None and getattr(block, "text", None):
                        text += block.text   # 兼容无 type 字段的旧响应
                input_tokens = resp.usage.input_tokens
                output_tokens = resp.usage.output_tokens
            else:
                text = resp.choices[0].message.content or ""
                usage = getattr(resp, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", 0)
                output_tokens = getattr(usage, "completion_tokens", 0)

            # 空回复也视为失败，触发回退（如某模型思考占满 token 返回空正文）
            if not text.strip():
                raise RuntimeError("empty reply from model")

            _record_cost(caller=caller, model=model,
                         input_tokens=input_tokens, output_tokens=output_tokens,
                         user=account)
            if idx > 0:
                logger.warning(f"ai chat: fell back to '{prov['provider']}' ({model}) for caller={caller}")
            return text

        except Exception as e:
            last_err = e
            logger.warning(
                f"ai chat: provider '{prov.get('provider')}' ({model}) failed "
                f"({type(e).__name__}: {str(e)[:120]}); "
                + ("trying next…" if idx + 1 < len(chain) else "no more fallbacks")
            )
            continue

    # 全部 provider 失败
    raise last_err if last_err else RuntimeError("all AI providers failed")


# ── Streaming chat (multi-turn) ──────────────────────────────────────────────────

def _stream_chain(messages: list[dict], system: str, max_tokens: int, caller: str,
                  account: str | None = None):
    """Blocking generator: yield text deltas, trying the fallback chain.

    `messages` is the multi-turn history [{role: user|assistant, content: str}, ...]
    WITHOUT the system message (passed separately). Falls back to the next provider
    only if the current one fails *before* emitting any token; a mid-stream failure
    just ends (partial text already sent — can't cleanly switch providers).
    """
    chain = _fallback_chain()
    last_err: Exception | None = None

    for idx, prov in enumerate(chain):
        client = _build_client_for(prov)
        model = prov["model"]
        is_anthropic = _is_anthropic_url(prov["base_url"])

        # 过载退避重试：只要还**没吐出任何 token**，过载类错误就对同一 provider
        # 退避重试(对齐非流式 chat() 的策略)，避免 MiniMax 高峰首 token 失败就
        # 立刻跌到欠费的 DeepSeek。一旦已 emit，则不能干净重来(会重复)，直接 raise。
        for attempt in range(_OVERLOAD_RETRIES + 1):
            emitted = False
            in_tok = out_tok = 0
            try:
                if is_anthropic:
                    with client.messages.stream(
                        model=model, max_tokens=max_tokens,
                        system=system, messages=messages,
                    ) as stream:
                        for text in stream.text_stream:
                            if text:
                                emitted = True
                                yield text
                        final = stream.get_final_message()
                        in_tok = final.usage.input_tokens
                        out_tok = final.usage.output_tokens
                else:
                    resp = client.chat.completions.create(
                        model=model, max_tokens=max_tokens, stream=True,
                        stream_options={"include_usage": True},
                        messages=[{"role": "system", "content": system}, *messages],
                    )
                    for chunk in resp:
                        if chunk.choices:
                            delta = chunk.choices[0].delta.content
                            if delta:
                                emitted = True
                                yield delta
                        usage = getattr(chunk, "usage", None)
                        if usage:
                            in_tok = getattr(usage, "prompt_tokens", 0) or in_tok
                            out_tok = getattr(usage, "completion_tokens", 0) or out_tok

                _record_cost(caller=caller, model=model,
                             input_tokens=in_tok, output_tokens=out_tok,
                             user=account)
                if idx > 0:
                    logger.warning(f"ai chat_stream: fell back to '{prov['provider']}' ({model}) for caller={caller}")
                return

            except Exception as e:
                last_err = e
                if emitted:
                    # 已流出部分内容 —— 无法干净回退/重试
                    raise
                # 首 token 前的过载错：退避重试同一 provider
                if attempt < _OVERLOAD_RETRIES and _is_overloaded(e):
                    wait = _OVERLOAD_BACKOFF[min(attempt, len(_OVERLOAD_BACKOFF) - 1)]
                    logger.warning(
                        f"ai chat_stream: provider '{prov.get('provider')}' overloaded "
                        f"({type(e).__name__}), retry {attempt + 1}/{_OVERLOAD_RETRIES} in {wait}s"
                    )
                    time.sleep(wait)
                    continue
                # 非过载错或重试用尽 → 跳出重试循环，回退到下一个 provider
                logger.warning(
                    f"ai chat_stream: provider '{prov.get('provider')}' ({model}) failed "
                    f"({type(e).__name__}: {str(e)[:120]}); "
                    + ("trying next…" if idx + 1 < len(chain) else "no more fallbacks")
                )
                break

    raise last_err if last_err else RuntimeError("all AI providers failed")


class _StreamErr:
    __slots__ = ("exc",)

    def __init__(self, exc: Exception):
        self.exc = exc


async def chat_stream(
    messages: list[dict],
    system: str,
    max_tokens: int = 2048,
    caller: str = "chat",
    account: str | None = None,
):
    """Async generator yielding text deltas for a multi-turn conversation.

    Bridges the blocking SDK stream onto the event loop via a queue so the
    FastAPI handler can `async for` over deltas without blocking the loop.

    ``account`` attributes token usage to a username for the admin console.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    def _produce():
        try:
            for delta in _stream_chain(messages, system, max_tokens, caller, account):
                loop.call_soon_threadsafe(queue.put_nowait, delta)
        except Exception as e:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, _StreamErr(e))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

    loop.run_in_executor(None, _produce)

    while True:
        item = await queue.get()
        if item is _DONE:
            break
        if isinstance(item, _StreamErr):
            raise item.exc
        yield item