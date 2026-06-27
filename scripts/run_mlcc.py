import os, sys, asyncio
os.environ.setdefault("QF_LLM_TIMEOUT", "240")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from quantforge.api.routes.research import _run_keyword_analysis, _slug

KW = "MLCC"

async def main():
    print(f"slug={_slug(KW)}", flush=True)
    await _run_keyword_analysis(KW, 0)
    print("DONE", flush=True)

asyncio.run(main())
