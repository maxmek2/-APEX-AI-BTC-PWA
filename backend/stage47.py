"""Stage 4.7: bootstrap robustness diagnostics on walk-forward closed trades.

This resamples observed fold trade outcomes; it is not a forecast and assumes
exchangeability/independence that real markets may violate.
"""
from __future__ import annotations

import random

try:
    from .stage46 import run_stage46_report
except ImportError:  # uvicorn main:app with backend as app-dir
    from stage46 import run_stage46_report


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate quantile of empty values")
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def run_stage47_report(
    bars: list[dict], starting_equity: float = 100.0,
    notional_usd: float = 10.0, fee_rate: float = 0.0025,
    slippage_bps: float = 5.0, folds: int = 3,
    simulations: int = 2000, seed: int = 47,
) -> dict:
    if simulations < 100 or simulations > 10000:
        raise ValueError("simulations must be between 100 and 10000")
    walk = run_stage46_report(
        bars, starting_equity, notional_usd, fee_rate, slippage_bps, folds
    )
    returns = [
        pnl for fold in walk["folds"]
        for pnl in fold["trade_net_pnl_usd"]
    ]
    if not returns:
        return {
            "walk_forward": walk,
            "observed_trade_count": 0,
            "bootstrap": None,
            "limitations": [
                "No closed trades were available for resampling.",
                "A zero-trade sample is not evidence of safety or profitability.",
            ],
            "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        }
    rng = random.Random(seed)
    final_equities = []
    max_drawdowns = []
    positive_paths = 0
    for _ in range(simulations):
        path = [rng.choice(returns) for _ in range(len(returns))]
        equity = starting_equity
        peak = starting_equity
        drawdown = 0.0
        for pnl in path:
            equity += pnl
            peak = max(peak, equity)
            if peak > 0:
                drawdown = max(drawdown, (peak - equity) / peak * 100)
        final_equities.append(equity)
        max_drawdowns.append(drawdown)
        positive_paths += int(equity > starting_equity)
    return {
        "walk_forward": walk,
        "observed_trade_count": len(returns),
        "bootstrap": {
            "simulations": simulations,
            "seed": seed,
            "sampling": "With replacement from pooled closed-trade net P/L across walk-forward folds.",
            "final_equity_usd": {
                "p05": round(_quantile(final_equities, 0.05), 4),
                "median": round(_quantile(final_equities, 0.50), 4),
                "p95": round(_quantile(final_equities, 0.95), 4),
            },
            "max_drawdown_percent": {
                "p05": round(_quantile(max_drawdowns, 0.05), 4),
                "median": round(_quantile(max_drawdowns, 0.50), 4),
                "p95": round(_quantile(max_drawdowns, 0.95), 4),
            },
            "positive_path_probability_percent": round(
                positive_paths / simulations * 100, 2
            ),
        },
        "limitations": [
            "Bootstrap is a resampling diagnostic, not a forecast or independent validation.",
            "Sampling with replacement ignores serial dependence, volatility clustering, regime changes and market impact.",
            "The same observed strategy and cost assumptions apply; unseen fees, gaps and execution failures are not represented.",
            "Small trade samples produce unstable distributions; report observed trade count with every result.",
        ],
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
    }
