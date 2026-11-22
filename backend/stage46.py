"""Stage 4.6: chronological walk-forward robustness test.

Uses a fixed, predeclared Stage 4.4 baseline configuration. No parameter search
is performed on fold holdouts. Each fold is independently simulated with its
own equity curve and ends before the next fold begins.
"""
from __future__ import annotations

try:
    from .stage44 import build_stage44_signals
    from .stage43 import run_breakout_backtest
except ImportError:  # uvicorn main:app with backend as app-dir
    from stage44 import build_stage44_signals
    from stage43 import run_breakout_backtest


def run_stage46_report(
    bars: list[dict], starting_equity: float = 100.0,
    notional_usd: float = 10.0, fee_rate: float = 0.0025,
    slippage_bps: float = 5.0, folds: int = 3,
) -> dict:
    if folds < 2 or folds > 5:
        raise ValueError("folds must be between 2 and 5")
    if len(bars) < 3000:
        raise ValueError("At least 3000 bars are required")
    # Freeze this configuration before examining any fold results.
    parameters = {
        "donchian_lookback": 20,
        "relative_volume_threshold": 1.5,
        "pullback_atr": 0.25,
        "pullback_bars": 4,
        "stop_atr_multiple": 1.5,
        "reward_risk": 2.0,
    }
    built = build_stage44_signals(
        bars, lookback=parameters["donchian_lookback"],
        relative_volume_threshold=parameters["relative_volume_threshold"],
        pullback_atr=parameters["pullback_atr"],
        pullback_bars=parameters["pullback_bars"],
    )
    mask = built["signals"]["breakout_pullback_relvol"]
    atrs = built["atr_by_base"]
    warmup_end = len(bars) // 2
    remaining = len(bars) - warmup_end
    block = remaining // folds
    if block < 100:
        raise ValueError("Each walk-forward fold must contain at least 100 bars")
    reports = []
    for fold in range(folds):
        start = warmup_end + fold * block
        end = len(bars) if fold == folds - 1 else warmup_end + (fold + 1) * block
        # Run only within this fold; the last position is closed at fold end.
        window_bars = bars[:end]
        result = run_breakout_backtest(
            window_bars, mask[:end], atrs[:end], starting_equity,
            notional_usd, fee_rate, slippage_bps, start_index=start,
        )
        first_fill = bars[start + 1].get("t")
        entries = [x for x in result["trades"] if x.get("entry_time")]
        costs = []
        for bps in (0, 5, 10, 20):
            sensitivity = run_breakout_backtest(
                window_bars, mask[:end], atrs[:end], starting_equity,
                notional_usd, fee_rate, bps, start_index=start,
            )
            sensitivity_entries = [x for x in sensitivity["trades"] if x.get("entry_time")]
            costs.append({
                "slippage_bps_per_side": bps,
                "metrics": sensitivity["metrics"],
                "entries_inside_fold": all(
                    x["entry_time"] >= first_fill for x in sensitivity_entries
                ),
            })
        reports.append({
            "fold": fold + 1,
            "start_index": start,
            "end_index_exclusive": end,
            "start_time": bars[start].get("t"),
            "first_possible_fill": first_fill,
            "end_time": bars[end - 1].get("t"),
            "signal_count": sum(mask[start:end]),
            "metrics": result["metrics"],
            "entries_inside_fold": all(x["entry_time"] >= first_fill for x in entries),
            "cost_sensitivity": costs,
        })
    return {
        "parameters": parameters,
        "folds": reports,
        "summary": {
            "folds": len(reports),
            "positive_net_pnl_folds": sum(x["metrics"]["net_pnl_usd"] > 0 for x in reports),
            "total_trades": sum(x["metrics"]["trades"] for x in reports),
            "total_net_pnl_usd": round(sum(x["metrics"]["net_pnl_usd"] for x in reports), 4),
            "all_entries_inside_fold": all(x["entries_inside_fold"] for x in reports),
            "positive_fold_count_is_not_a_profitability_certificate": True,
        },
        "selection_used_fold_results": False,
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
    }
