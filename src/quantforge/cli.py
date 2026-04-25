"""QuantForge CLI entry point."""

import asyncio
import importlib
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _load_strategy(strategy_path: str):
    """Load a strategy class from a dotted path or file path.

    Accepts:
      - module.path.ClassName  (e.g. strategies.examples.dual_ma_strategy.DualMAStrategy)
      - file path              (e.g. strategies/examples/dual_ma_strategy.py::DualMAStrategy)
    """
    if "::" in strategy_path:
        file_path, class_name = strategy_path.rsplit("::", 1)
        p = Path(file_path)
        if not p.exists():
            raise click.BadParameter(f"File not found: {file_path}")
        # Add directory to sys.path
        sys.path.insert(0, str(p.parent.parent))
        module_name = ".".join(p.with_suffix("").parts)
        module = importlib.import_module(module_name)
    else:
        parts = strategy_path.rsplit(".", 1)
        if len(parts) != 2:
            raise click.BadParameter(
                f"Invalid strategy path: {strategy_path}. "
                "Use 'module.path.ClassName' or 'path/file.py::ClassName'"
            )
        module = importlib.import_module(parts[0])
        class_name = parts[1]

    cls = getattr(module, class_name, None)
    if cls is None:
        raise click.BadParameter(f"Class '{class_name}' not found in module.")
    return cls


@click.group()
@click.version_option("0.1.0", prog_name="QuantForge")
def main():
    """QuantForge — Quantitative Trading System"""


@main.command()
@click.option(
    "--strategy", "-s",
    required=True,
    help="Strategy class path, e.g. 'strategies.examples.dual_ma_strategy.DualMAStrategy'",
)
@click.option("--symbol", multiple=True, default=["000001"], show_default=True)
@click.option("--start", default="2022-01-01", show_default=True, help="Start date YYYY-MM-DD")
@click.option("--end", default=None, help="End date YYYY-MM-DD (default: today)")
@click.option("--capital", default=1_000_000.0, show_default=True, type=float)
@click.option("--exchange", default="SZSE", show_default=True)
@click.option(
    "--param", "-p",
    multiple=True,
    help="Strategy params as key=value, e.g. -p fast_period=10 -p slow_period=30",
)
@click.option("--data-dir", default="data", show_default=True)
def backtest(strategy, symbol, start, end, capital, exchange, param, data_dir):
    """Run a backtest on historical data."""
    from quantforge.core.constants import Exchange as Exc, Interval
    from quantforge.backtest.engine import BacktestEngine

    # Parse params
    params: dict = {}
    for p in param:
        if "=" not in p:
            raise click.BadParameter(f"Invalid param format: {p}. Use key=value")
        k, v = p.split("=", 1)
        # Try to convert to int or float
        try:
            v = int(v)
        except ValueError:
            try:
                v = float(v)
            except ValueError:
                pass
        params[k] = v

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()

    try:
        exc = Exc(exchange.upper())
    except ValueError:
        raise click.BadParameter(f"Unknown exchange: {exchange}")

    # Add project root to path so strategy imports work
    project_root = Path(data_dir).parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        strategy_cls = _load_strategy(strategy)
    except Exception as e:
        console.print(f"[red]Failed to load strategy: {e}[/red]")
        raise SystemExit(1)

    console.print(f"\n[bold cyan]QuantForge Backtest[/bold cyan]")
    console.print(f"Strategy : [green]{strategy_cls.__name__}[/green]")
    console.print(f"Symbols  : {', '.join(symbol)}")
    console.print(f"Period   : {start} → {end_dt:%Y-%m-%d}")
    console.print(f"Capital  : {capital:,.0f}")
    if params:
        console.print(f"Params   : {params}")
    console.print()

    engine = BacktestEngine(data_dir=data_dir)

    result = asyncio.run(
        engine.run(
            strategy_cls=strategy_cls,
            symbols=list(symbol),
            start=start_dt,
            end=end_dt,
            exchange=exc,
            interval=Interval.DAILY,
            initial_capital=capital,
            params=params,
        )
    )

    # Display results
    console.print(result.summary())

    # Metrics table
    table = Table(title="Performance Metrics", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    rows = [
        ("Total Return", f"{result.total_return:.2%}"),
        ("Annualized Return", f"{result.metrics.get('annualized_return', 0):.2%}"),
        ("Sharpe Ratio", f"{result.sharpe_ratio:.3f}"),
        ("Sortino Ratio", f"{result.metrics.get('sortino_ratio', 0):.3f}"),
        ("Calmar Ratio", f"{result.metrics.get('calmar_ratio', 0):.3f}"),
        ("Max Drawdown", f"{result.max_drawdown:.2%}"),
        ("Win Rate", f"{result.win_rate:.2%}"),
        ("Trade Count", str(result.metrics.get("trade_count", 0))),
        ("Profit Factor", f"{result.metrics.get('profit_factor', 0):.2f}"),
    ]
    for metric, value in rows:
        table.add_row(metric, value)
    console.print(table)


@main.command()
@click.option("--symbol", required=True)
@click.option("--start", default="2020-01-01", show_default=True)
@click.option("--end", default=None)
@click.option("--exchange", default="SZSE", show_default=True)
@click.option("--data-dir", default="data", show_default=True)
def download(symbol, start, end, exchange, data_dir):
    """Download historical market data."""
    from quantforge.core.constants import Exchange as Exc, Interval
    from quantforge.data.manager import DataManager

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()

    try:
        exc = Exc(exchange.upper())
    except ValueError:
        raise click.BadParameter(f"Unknown exchange: {exchange}")

    console.print(f"Downloading [green]{symbol}[/green] from {start} to {end_dt:%Y-%m-%d}...")

    dm = DataManager(data_dir)

    async def run():
        df = await dm.download(symbol, Interval.DAILY, start_dt, end_dt, exc)
        return df

    df = asyncio.run(run())
    console.print(f"[green]Done![/green] {len(df)} bars saved.")


if __name__ == "__main__":
    main()
