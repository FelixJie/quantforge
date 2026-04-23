"""HTML report generator for backtest results.

Generates a self-contained, single-file HTML report with:
- Summary metrics table
- Equity curve (ECharts)
- Drawdown chart (ECharts)
- Monthly return heatmap
- Trade list table
- Embedded CSS + JS (no external dependencies needed offline)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from quantforge.backtest.engine import BacktestResult


# ── CDN links (ECharts via unpkg) ─────────────────────────────────────────────
_ECHARTS_CDN = "https://unpkg.com/echarts@5.4.3/dist/echarts.min.js"


def generate_report(
    result: BacktestResult,
    output_path: str | Path | None = None,
    title: str | None = None,
) -> str:
    """Generate a self-contained HTML backtest report.

    Args:
        result: BacktestResult from BacktestEngine.run()
        output_path: if given, write the HTML to this file
        title: report title (defaults to strategy name + dates)

    Returns:
        HTML string
    """
    title = title or (
        f"{result.strategy_name} | "
        f"{result.start:%Y-%m-%d} → {result.end:%Y-%m-%d}"
    )

    equity_df = result.equity_curve.copy()
    equity_df["date_str"] = pd.to_datetime(equity_df["date"]).dt.strftime("%Y-%m-%d")

    equity_dates = equity_df["date_str"].tolist()
    equity_values = equity_df["equity"].round(2).tolist()

    # Drawdown series
    eq_series = pd.Series(equity_values)
    rolling_max = eq_series.cummax()
    drawdown = ((eq_series - rolling_max) / rolling_max * 100).round(4).tolist()

    # Monthly returns heatmap
    monthly_data = _compute_monthly_returns(equity_df)

    # Trade list
    trades_rows = _format_trades(result.trades)

    m = result.metrics
    html = _HTML_TEMPLATE.format(
        title=_esc(title),
        strategy=_esc(result.strategy_name),
        symbols=", ".join(result.symbols),
        period=f"{result.start:%Y-%m-%d} → {result.end:%Y-%m-%d}",
        initial_capital=f"¥{result.initial_capital:,.0f}",
        final_equity=f"¥{m.get('final_equity', 0):,.2f}",
        total_return=f"{m.get('total_return', 0):.2%}",
        annual_return=f"{m.get('annualized_return', 0):.2%}",
        sharpe=f"{m.get('sharpe_ratio', 0):.3f}",
        sortino=f"{m.get('sortino_ratio', 0):.3f}",
        calmar=f"{m.get('calmar_ratio', 0):.3f}",
        max_drawdown=f"{m.get('max_drawdown', 0):.2%}",
        volatility=f"{m.get('volatility', 0):.2%}",
        win_rate=f"{m.get('win_rate', 0):.2%}",
        profit_factor=f"{m.get('profit_factor', 0):.2f}",
        trade_count=m.get('trade_count', 0),
        avg_trade_pnl=f"¥{m.get('avg_trade_pnl', 0):,.2f}",
        return_color="pos" if m.get("total_return", 0) >= 0 else "neg",
        equity_dates=json.dumps(equity_dates),
        equity_values=json.dumps(equity_values),
        drawdown_values=json.dumps(drawdown),
        monthly_data=json.dumps(monthly_data),
        trades_rows=trades_rows,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        echarts_cdn=_ECHARTS_CDN,
    )

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(html, encoding="utf-8")

    return html


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _compute_monthly_returns(equity_df: pd.DataFrame) -> list[list]:
    """Return [[year, month_idx, return_pct], ...] for ECharts heatmap."""
    df = equity_df.copy()
    df["date_dt"] = pd.to_datetime(df["date"])
    df["year"] = df["date_dt"].dt.year
    df["month"] = df["date_dt"].dt.month

    rows = []
    for (year, month), grp in df.groupby(["year", "month"]):
        if len(grp) < 2:
            continue
        first = grp["equity"].iloc[0]
        last = grp["equity"].iloc[-1]
        pct = (last / first - 1) * 100
        rows.append([int(year), int(month) - 1, round(float(pct), 2)])  # month 0-indexed
    return rows


def _format_trades(trades: list) -> str:
    if not trades:
        return "<tr><td colspan='6' class='no-data'>暂无交易记录</td></tr>"
    rows = []
    for t in trades:
        direction = "买入" if str(t.direction).endswith("LONG") else "卖出"
        dt_str = t.datetime.strftime("%Y-%m-%d") if t.datetime else "-"
        rows.append(
            f"<tr>"
            f"<td>{dt_str}</td>"
            f"<td>{_esc(t.symbol)}</td>"
            f"<td class='{'pos' if 'LONG' in str(t.direction) else 'neg'}'>{direction}</td>"
            f"<td>{t.price:.3f}</td>"
            f"<td>{int(t.volume):,}</td>"
            f"<td>{t.commission:.2f}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuantForge | {title}</title>
<script src="{echarts_cdn}"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e2e8f0;line-height:1.5;}}
.container{{max-width:1100px;margin:0 auto;padding:32px 20px;}}
h1{{font-size:20px;font-weight:700;color:#63b3ed;margin-bottom:4px;}}
.subtitle{{font-size:13px;color:#718096;margin-bottom:28px;}}
.grid-4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;}}
.grid-3{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px;}}
.card{{background:#161b27;border:1px solid #2d3748;border-radius:8px;padding:16px;}}
.card-label{{font-size:11px;color:#718096;margin-bottom:6px;}}
.card-value{{font-size:20px;font-weight:700;}}
.pos{{color:#48bb78;}}.neg{{color:#f56565;}}.neutral{{color:#e2e8f0;}}
.chart-card{{background:#161b27;border:1px solid #2d3748;border-radius:8px;padding:16px;margin-bottom:16px;}}
.chart-card h2{{font-size:13px;color:#a0aec0;margin-bottom:10px;font-weight:600;}}
.chart{{width:100%;height:280px;}}
.chart-sm{{width:100%;height:180px;}}
table{{width:100%;border-collapse:collapse;font-size:12px;background:#161b27;border:1px solid #2d3748;border-radius:8px;overflow:hidden;}}
th{{text-align:left;padding:10px 12px;color:#718096;border-bottom:1px solid #2d3748;font-weight:500;background:#0f1117;}}
td{{padding:8px 12px;border-bottom:1px solid #1a2035;}}
tr:last-child td{{border-bottom:none;}}
.no-data{{text-align:center;color:#4a5568;padding:20px;}}
.footer{{text-align:center;font-size:11px;color:#4a5568;margin-top:32px;padding-top:16px;border-top:1px solid #2d3748;}}
.section-title{{font-size:15px;font-weight:600;margin-bottom:12px;color:#a0aec0;}}
</style>
</head>
<body>
<div class="container">
  <h1>QuantForge 回测报告</h1>
  <div class="subtitle">
    策略: {strategy} &nbsp;|&nbsp; 标的: {symbols} &nbsp;|&nbsp; 区间: {period}
  </div>

  <!-- Key metrics -->
  <div class="grid-4">
    <div class="card">
      <div class="card-label">初始资金</div>
      <div class="card-value neutral">{initial_capital}</div>
    </div>
    <div class="card">
      <div class="card-label">最终净值</div>
      <div class="card-value neutral">{final_equity}</div>
    </div>
    <div class="card">
      <div class="card-label">总收益率</div>
      <div class="card-value {return_color}">{total_return}</div>
    </div>
    <div class="card">
      <div class="card-label">年化收益</div>
      <div class="card-value {return_color}">{annual_return}</div>
    </div>
  </div>

  <div class="grid-4">
    <div class="card">
      <div class="card-label">夏普比率</div>
      <div class="card-value neutral">{sharpe}</div>
    </div>
    <div class="card">
      <div class="card-label">索提诺比率</div>
      <div class="card-value neutral">{sortino}</div>
    </div>
    <div class="card">
      <div class="card-label">卡玛比率</div>
      <div class="card-value neutral">{calmar}</div>
    </div>
    <div class="card">
      <div class="card-label">最大回撤</div>
      <div class="card-value neg">{max_drawdown}</div>
    </div>
  </div>

  <div class="grid-4">
    <div class="card">
      <div class="card-label">波动率 (年化)</div>
      <div class="card-value neutral">{volatility}</div>
    </div>
    <div class="card">
      <div class="card-label">胜率</div>
      <div class="card-value neutral">{win_rate}</div>
    </div>
    <div class="card">
      <div class="card-label">盈亏比</div>
      <div class="card-value neutral">{profit_factor}</div>
    </div>
    <div class="card">
      <div class="card-label">交易次数</div>
      <div class="card-value neutral">{trade_count}</div>
    </div>
  </div>

  <!-- Equity curve -->
  <div class="chart-card">
    <h2>净值曲线</h2>
    <div id="equity" class="chart"></div>
  </div>

  <!-- Drawdown -->
  <div class="chart-card">
    <h2>回撤</h2>
    <div id="drawdown" class="chart-sm"></div>
  </div>

  <!-- Monthly returns -->
  <div class="chart-card">
    <h2>月度收益热力图</h2>
    <div id="monthly" class="chart-sm"></div>
  </div>

  <!-- Trade list -->
  <div class="section-title" style="margin-top:24px">交易明细</div>
  <table>
    <thead><tr><th>日期</th><th>代码</th><th>方向</th><th>成交价</th><th>数量</th><th>手续费</th></tr></thead>
    <tbody>{trades_rows}</tbody>
  </table>

  <div class="footer">
    由 QuantForge 生成 &nbsp;|&nbsp; {generated_at}
  </div>
</div>

<script>
const DATES = {equity_dates};
const EQUITY = {equity_values};
const DRAWDOWN = {drawdown_values};
const MONTHLY = {monthly_data};

// Equity curve
const eq = echarts.init(document.getElementById('equity'));
eq.setOption({{
  backgroundColor:'transparent',
  tooltip:{{trigger:'axis',formatter:p=>`${{p[0].name}}<br/>净值: ¥${{p[0].value.toLocaleString()}}`}},
  grid:{{left:70,right:20,top:10,bottom:40}},
  dataZoom:[{{type:'inside',start:0,end:100}},{{type:'slider',start:0,end:100,height:20,bottom:4,borderColor:'#2d3748',fillerColor:'rgba(99,179,237,0.15)',handleStyle:{{color:'#63b3ed'}},textStyle:{{color:'#718096'}}}}],
  xAxis:{{type:'category',data:DATES,axisLabel:{{color:'#718096',fontSize:10}},axisLine:{{lineStyle:{{color:'#2d3748'}}}}}},
  yAxis:{{type:'value',axisLabel:{{color:'#718096',fontSize:10,formatter:v=>'¥'+(v/10000).toFixed(0)+'w'}},axisLine:{{lineStyle:{{color:'#2d3748'}}}},splitLine:{{lineStyle:{{color:'#2d3748'}}}}}},
  series:[{{type:'line',data:EQUITY,smooth:true,symbol:'none',lineStyle:{{color:'#63b3ed',width:2}},areaStyle:{{color:{{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{{offset:0,color:'rgba(99,179,237,0.25)'}},{{offset:1,color:'rgba(99,179,237,0)'}}]}}}}}}]
}});

// Drawdown
const dd = echarts.init(document.getElementById('drawdown'));
dd.setOption({{
  backgroundColor:'transparent',
  tooltip:{{trigger:'axis',formatter:p=>`${{p[0].name}}<br/>回撤: ${{p[0].value.toFixed(2)}}%`}},
  grid:{{left:70,right:20,top:10,bottom:40}},
  dataZoom:[{{type:'inside',start:0,end:100}}],
  xAxis:{{type:'category',data:DATES,axisLabel:{{color:'#718096',fontSize:10}},axisLine:{{lineStyle:{{color:'#2d3748'}}}}}},
  yAxis:{{type:'value',axisLabel:{{color:'#718096',fontSize:10,formatter:v=>v.toFixed(1)+'%'}},axisLine:{{lineStyle:{{color:'#2d3748'}}}},splitLine:{{lineStyle:{{color:'#2d3748'}}}}}},
  series:[{{type:'line',data:DRAWDOWN,smooth:true,symbol:'none',lineStyle:{{color:'#f56565',width:1.5}},areaStyle:{{color:'rgba(245,101,101,0.2)'}}}}]
}});

// Monthly heatmap
const months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];
const years = [...new Set(MONTHLY.map(d=>d[0]))].sort();
const mdata = MONTHLY.map(d=>[d[1], years.indexOf(d[0]), d[2]]);
const minV = Math.min(...MONTHLY.map(d=>d[2]));
const maxV = Math.max(...MONTHLY.map(d=>d[2]));

const mo = echarts.init(document.getElementById('monthly'));
mo.setOption({{
  backgroundColor:'transparent',
  tooltip:{{formatter:p=>`${{years[p.data[1]]}}年 ${{months[p.data[0]]}}<br/>收益: ${{p.data[2].toFixed(2)}}%`}},
  grid:{{left:60,right:80,top:10,bottom:30}},
  xAxis:{{type:'category',data:months,axisLabel:{{color:'#718096',fontSize:10}},axisLine:{{lineStyle:{{color:'#2d3748'}}}}}},
  yAxis:{{type:'category',data:years.map(String),axisLabel:{{color:'#718096',fontSize:10}},axisLine:{{lineStyle:{{color:'#2d3748'}}}}}},
  visualMap:{{min:minV,max:maxV,calculable:true,orient:'vertical',right:0,top:'center',textStyle:{{color:'#718096',fontSize:10}},inRange:{{color:['#f56565','#1a2035','#48bb78']}}}},
  series:[{{type:'heatmap',data:mdata,label:{{show:true,color:'#e2e8f0',fontSize:9,formatter:p=>p.data[2].toFixed(1)+'%'}}}}]
}});

window.addEventListener('resize',()=>{{eq.resize();dd.resize();mo.resize();}});
</script>
</body>
</html>
"""
