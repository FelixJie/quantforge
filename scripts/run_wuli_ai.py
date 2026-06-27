# 独立脚本：跑「物理AI」产业链分析
# MAP 结果落 SQLite report_facts 表；REDUCE 走 Claude Code (Opus 4.8)
import os
import sys
import asyncio
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)                                  # db_cache 的 data/cache.db 要在 CWD
sys.path.insert(0, str(ROOT / "src"))

# 手动加载 .env（同 app.py 的 _load_dotenv），要在任何 quantforge import 前
env_file = ROOT / ".env"
if env_file.exists():
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

# MAP 也走 Claude Code (Opus 4.8)；REDUCE 同上
# MAP 走默认 MiniMax（不设 QF_RESEARCH_MAP_PROVIDER）

KEYWORD = "物理AI"
slug = "kw_" + hashlib.md5(KEYWORD.encode()).hexdigest()[:10]
print(f"keyword={KEYWORD}  slug={slug}", flush=True)
print(f"results will be written to: {ROOT}/data/cache/industry_tasks/{slug}.json", flush=True)
print(f"MAP cache in: {ROOT}/data/cache.db  (table: report_facts)", flush=True)
print("=" * 60, flush=True)

from quantforge.api.routes.research import _run_keyword_analysis

asyncio.run(_run_keyword_analysis(KEYWORD, 0))

print("=" * 60, flush=True)
print("DONE", flush=True)
