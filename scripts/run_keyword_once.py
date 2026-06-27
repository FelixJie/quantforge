"""独立跑一次关键词产业链精读（绕开 web/admin 鉴权，无进程 churn）。
落库与 web 同源：data/cache/industry_tasks/<slug>.json。
用法: python scripts/run_keyword_once.py "AI算力" [read_limit]
"""
import os, sys, asyncio, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                      # CWD=项目根，决定 data/cache 路径
sys.path.insert(0, str(ROOT / "src"))

# 手动加载 .env（直接跑脚本不会经过 app.py 的 load_dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception as e:
    print(f"[warn] load_dotenv failed: {e}", flush=True)

# 给思考型 MiniMax 跑大型 REDUCE 留时间
os.environ.setdefault("QF_LLM_TIMEOUT", "240")

kw = sys.argv[1] if len(sys.argv) > 1 else "AI算力"
read_limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0

from quantforge.api.routes.research import _run_keyword_analysis, _slug, _RUNNING_TASKS

slug = _slug(kw)
print(f"[start] keyword={kw!r} slug={slug} read_limit={read_limit} "
      f"anthropic_key={'yes' if os.getenv('ANTHROPIC_API_KEY') else 'NO'}", flush=True)


async def main():
    await _run_keyword_analysis(kw, read_limit)
    out = ROOT / "data" / "cache" / "industry_tasks" / f"{slug}.json"
    if out.exists():
        d = json.loads(out.read_text(encoding="utf-8"))
        res = d.get("result", {})
        print(f"[done] saved={out}", flush=True)
        print(f"[done] error={res.get('error')!r} "
              f"overview_len={len(res.get('overview') or '')} "
              f"bom={len(res.get('bom') or [])} segments={len(res.get('segments') or [])} "
              f"decisions={len((res.get('decision') or {}).get('buys') or [])}", flush=True)
    else:
        print(f"[done] but no file at {out}", flush=True)


asyncio.run(main())
print("[exit] ok", flush=True)
