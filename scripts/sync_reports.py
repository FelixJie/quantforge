"""全市场研报入库（手动首灌 / 补跑）。

近一年个股研报(qType=0)约 1.5 万篇、行业研报(qType=1)约 1.8 万篇，全市场翻页拉取后
分别落库 stock_reports / industry_reports。每日增量由后端 report_sync_scheduler 接管
（QF_ENABLE_REPORT_SYNC=1），本脚本用于首次灌库或手动补跑。

用法（在项目根目录，用系统 Python；.venv 不全）：
    py -3.14 scripts/sync_reports.py            # 库空→近一年全量；非空→增量
    py -3.14 scripts/sync_reports.py --full     # 强制近一年全量
    py -3.14 scripts/sync_reports.py --days 90  # 自定义回溯天数（配合 --full）
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from quantforge.api.routes import research  # noqa: E402
from quantforge.data.storage import db_cache  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="强制近一年全量（默认按库空与否自动判定）")
    ap.add_argument("--days", type=int, default=research._REPORT_LOOKBACK_DAYS,
                    help="全量回溯天数（默认 365）")
    args = ap.parse_args()

    print(f"开始同步：stock={db_cache.reports_total_count()} "
          f"industry={db_cache.industry_reports_total_count()} (入库前)")
    res = await research.sync_all_reports(lookback_days=args.days, full=args.full)
    print(f"完成：{res}")
    print(f"库存：stock={db_cache.reports_total_count()} "
          f"industry={db_cache.industry_reports_total_count()} "
          f"latest(stock)={db_cache.reports_global_latest_date()} "
          f"latest(industry)={db_cache.industry_reports_latest_date()}")


if __name__ == "__main__":
    asyncio.run(main())
