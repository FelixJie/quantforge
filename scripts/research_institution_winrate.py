# -*- coding: utf-8 -*-
"""调研纪要推荐机构胜率分析（命令行）。

复用 quantforge.api.research_winrate 核心；离线读 data/cache.db。
胜率口径：发帖当日(或之后首个交易日)收盘为基准，N 个交易日后收盘：
  绝对胜率=收益>0 占比；相对胜率=跑赢沪深300同期占比。

用法： python scripts/research_institution_winrate.py [--days N] [--min M] [--detail]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quantforge.api.research_winrate import compute, HORIZONS  # noqa: E402


def _lbl(n: int) -> str:
    return "昨日" if n == 1 else f"{n}日"


def main():
    days = 120
    mins = 3
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    if "--min" in sys.argv:
        mins = int(sys.argv[sys.argv.index("--min") + 1])

    res = compute(lookback_days=days, min_samples=mins)
    m = res["meta"]
    print(f"调研纪要帖子 {m['posts_total']} 篇 | 识别机构 {m['posts_with_inst']} 篇 | "
          f"含推荐个股 {m['posts_with_stock']} 篇 | 机构数 {m['inst_count']}")
    print(f"帖子区间 {m['post_start']}..{m['post_end']} | K线最新 {m['kline_latest']} | "
          f"基准 {m['benchmark']}")
    if m["note"]:
        print(f"※ {m['note']}")
    print()

    insts = res["institutions"]
    print("=" * 104)
    print("各机构胜率(交易日)  —  相对胜率% / 绝对胜率% (样本n, 平均超额%)")
    print("=" * 104)
    hdr = f"{'机构':<14}"
    for n in HORIZONS:
        hdr += f"{_lbl(n):>22}"
    print(hdr)
    print("-" * 104)
    for r in insts:
        line = f"{r['name']:<14}"
        for n in HORIZONS:
            s = r["horizons"].get(str(n))
            if not s:
                line += f"{'-':>22}"
            else:
                wr = "" if s["win_rel"] is None else f"{s['win_rel']*100:.0f}"
                exc = "" if s["avg_exc"] is None else f"{s['avg_exc']*100:+.1f}"
                cell = f"{wr}/{s['win_abs']*100:.0f}% (n{s['n']} {exc})"
                line += cell.rjust(22)
        print(line)

    for n in HORIZONS:
        key = str(n)
        names = res["rankings"][key]
        print(f"\n----- {_lbl(n)} 相对胜率排名 (样本≥{mins}) -----")
        if not names:
            print(f"  (无机构样本量达到 {mins}，数据深度不足)")
            continue
        idx = {r["name"]: r for r in insts}
        for i, nm in enumerate(names[:15], 1):
            s = idx[nm]["horizons"][key]
            wr = "-" if s["win_rel"] is None else f"{s['win_rel']*100:.0f}%"
            exc = "-" if s["avg_exc"] is None else f"{s['avg_exc']*100:+.1f}%"
            print(f"  {i:>2}. {nm:<14} 相对胜率{wr:>5}  绝对{s['win_abs']*100:>3.0f}%  "
                  f"平均超额{exc:>6}  平均收益{s['avg_ret']*100:+5.1f}%  n={s['n']}")


if __name__ == "__main__":
    main()
