"""Stage 5.3: causal strategy diagnostics and training-only optimization.

Research-only. Candidate parameters are selected on the chronological training
segment. At most one training-qualified candidate is evaluated on holdout.
No broker, account, order, or position APIs are used.
"""
from __future__ import annotations

from itertools import product

try:
    from .stage43 import run_breakout_backtest
    from .stage44 import build_stage44_signals
    from .stage48 import build_stage48_diagnostics
except ImportError:  # uvicorn main:app with backend as app-dir
    from stage43 import run_breakout_backtest
    from stage44 import build_stage44_signals
    from stage48 import build_stage48_diagnostics


def _pf_ok(value) -> bool:
    return value == "infinite" or (isinstance(value, (int, float)) and value > 1.0)


def _candidate_metrics_ok(metrics: dict, minimum_trades: int, max_drawdown_percent: float) -> bool:
    return (
        int(metrics.get("trades", 0)) >= minimum_trades
        and float(metrics.get("net_pnl_usd", 0)) > 0
        and _pf_ok(metrics.get("net_profit_factor"))
        and float(metrics.get("max_drawdown_percent", 1000)) <= max_drawdown_percent
    )


def run_stage53_report(
    bars: list[dict],
    train_fraction: float = 0.60,
    starting_equity: float = 100.0,
    notional_usd: float = 10.0,
    fee_rate: float = 0.0025,
    slippage_bps: float = 5.0,
    minimum_training_trades: int = 30,
    max_training_drawdown_percent: float = 5.0,
) -> dict:
    if not 0.50 <= train_fraction <= 0.80:
        raise ValueError("train_fraction must be between 0.50 and 0.80")
    if len(bars) < 3000:
        raise ValueError("At least 3000 bars are required")
    if minimum_training_trades < 10 or minimum_training_trades > 500:
        raise ValueError("minimum_training_trades must be between 10 and 500")
    if not 0 < max_training_drawdown_percent <= 50:
        raise ValueError("max_training_drawdown_percent must be within (0, 50]")

    split = int(len(bars) * train_fraction)
    if split < 1000 or len(bars) - split < 100:
        raise ValueError("Insufficient chronological training or holdout data")
    first_holdout_fill = bars[split + 1].get("t")

    # Predeclared, bounded grid: 72 combinations. All ranking and qualification
    # use training metrics only; holdout is never used to choose parameters.
    grid = list(product(
        (1.2, 1.5, 1.8),
        (0.15, 0.25, 0.40),
        (2, 4),
        (1.0, 1.5, 2.0),
        (1.5, 2.0),
    ))
    candidates = []
    selected_cache = {}
    for volume_threshold, pullback_atr, pullback_bars, stop_atr, reward_risk in grid:
        built = build_stage44_signals(
            bars, lookback=20,
            relative_volume_threshold=volume_threshold,
            pullback_atr=pullback_atr,
            pullback_bars=pullback_bars,
        )
        mask = built["signals"]["breakout_pullback_relvol"]
        atrs = built["atr_by_base"]
        train = run_breakout_backtest(
            bars[:split + 1], mask[:split + 1], atrs[:split + 1],
            starting_equity, notional_usd, fee_rate, slippage_bps,
            stop_atr_multiple=stop_atr, reward_risk=reward_risk,
        )
        metrics = train["metrics"]
        parameters = {
            "donchian_lookback": 20,
            "relative_volume_threshold": volume_threshold,
            "pullback_atr": pullback_atr,
            "pullback_bars": pullback_bars,
            "stop_atr_multiple": stop_atr,
            "reward_risk": reward_risk,
        }
        key = (volume_threshold, pullback_atr, pullback_bars, stop_atr, reward_risk)
        candidates.append({
            "parameters": parameters,
            "training_metrics": metrics,
            "training_signal_count": sum(mask[:split + 1]),
            "training_gate_passed": _candidate_metrics_ok(
                metrics, minimum_training_trades, max_training_drawdown_percent
            ),
        })
        selected_cache[key] = (mask, atrs)

    # Stable deterministic ranking using training-only evidence.
    candidates.sort(key=lambda item: (
        item["training_gate_passed"],
        float(item["training_metrics"].get("net_pnl_usd", 0)),
        (float(item["training_metrics"]["net_profit_factor"])
         if isinstance(item["training_metrics"].get("net_profit_factor"), (int, float))
         else 1e9 if item["training_metrics"].get("net_profit_factor") == "infinite" else -1),
        -float(item["training_metrics"].get("max_drawdown_percent", 1000)),
        int(item["training_metrics"].get("trades", 0)),
    ), reverse=True)

    qualified = [item for item in candidates if item["training_gate_passed"]]
    selected = qualified[0] if qualified else None
    holdout = None
    holdout_diagnostics = None
    if selected:
        p = selected["parameters"]
        key = (
            p["relative_volume_threshold"], p["pullback_atr"],
            p["pullback_bars"], p["stop_atr_multiple"], p["reward_risk"],
        )
        mask, atrs = selected_cache[key]
        result = run_breakout_backtest(
            bars, mask, atrs, starting_equity, notional_usd,
            fee_rate, slippage_bps,
            stop_atr_multiple=p["stop_atr_multiple"],
            reward_risk=p["reward_risk"],
            start_index=split,
        )
        entries = [x for x in result["trades"] if x.get("entry_time")]
        boundary_ok = all(x["entry_time"] >= first_holdout_fill for x in entries)
        holdout = {
            "metrics": result["metrics"],
            "trades": result["trades"],
            "entries_after_split": boundary_ok,
            "gate_passed": (
                boundary_ok and _candidate_metrics_ok(
                    result["metrics"], minimum_training_trades,
                    max_training_drawdown_percent,
                )
            ),
            "minimum_trades_for_gate": minimum_training_trades,
            "max_drawdown_percent_for_gate": max_training_drawdown_percent,
        }
        holdout_diagnostics = build_stage48_diagnostics(
            bars[split + 1:], result["trades"], mask[split + 1:], atrs[split + 1:]
        )

    # Descriptive baseline diagnostics are split by time; never used for tuning.
    baseline = build_stage44_signals(
        bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    baseline_mask = baseline["signals"]["breakout_pullback_relvol"]
    baseline_atrs = baseline["atr_by_base"]
    baseline_train = run_breakout_backtest(
        bars[:split + 1], baseline_mask[:split + 1], baseline_atrs[:split + 1],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    baseline_holdout = run_breakout_backtest(
        bars, baseline_mask, baseline_atrs, starting_equity,
        notional_usd, fee_rate, slippage_bps, start_index=split,
    )
    train_diagnostics = build_stage48_diagnostics(
        bars[:split + 1], baseline_train["trades"],
        baseline_mask[:split + 1], baseline_atrs[:split + 1],
    )
    baseline_holdout_trades = baseline_holdout["trades"]
    holdout_diag = build_stage48_diagnostics(
        bars[split + 1:], baseline_holdout_trades,
        baseline_mask[split + 1:], baseline_atrs[split + 1:],
    )

    return {
        "stage": "5.3",
        "status": "TRAIN_ONLY_OPTIMIZATION_AND_TRADE_DIAGNOSTICS",
        "result": (
            "CANDIDATE_FOUND_HOLDOUT_PENDING" if selected
            else "NO_TRAINING_QUALIFIED_CANDIDATE"
        ),
        "bars_used": len(bars),
        "split": {
            "method": "chronological",
            "train_fraction": train_fraction,
            "training_bars": split + 1,
            "holdout_bars": len(bars) - split - 1,
            "training_to": bars[split].get("t"),
            "first_possible_holdout_fill": first_holdout_fill,
            "holdout_to": bars[-1].get("t"),
        },
        "assumptions": {
            "starting_equity_usd": starting_equity,
            "fixed_notional_usd": notional_usd,
            "fee_per_side_percent": fee_rate * 100,
            "slippage_bps_per_side": slippage_bps,
            "fill": "Signal on completed 15m close; next 5m open; long-only.",
            "exit_model": "ATR stop and reward/risk target; conservative stop-first OHLC.",
        },
        "optimization": {
            "grid_size": len(grid),
            "qualified_training_candidates": len(qualified),
            "minimum_training_trades": minimum_training_trades,
            "max_training_drawdown_percent": max_training_drawdown_percent,
            "selection_used_holdout": False,
            "holdout_evaluated_once": bool(selected),
            "selected_parameters": selected["parameters"] if selected else None,
            "selected_training_metrics": selected["training_metrics"] if selected else None,
            "holdout": holdout,
            "top_training_candidates": candidates[:10],
            "selection_rule": (
                "Training only: minimum trade count, positive net P&L, net PF > 1, "
                "and max closed-trade drawdown within limit; deterministic ranking."
            ),
        },
        "baseline_diagnostics": {
            "parameters": {
                "donchian_lookback": 20, "relative_volume_threshold": 1.5,
                "pullback_atr": 0.25, "pullback_bars": 4,
                "stop_atr_multiple": 1.5, "reward_risk": 2.0,
            },
            "training_metrics": baseline_train["metrics"],
            "holdout_metrics": baseline_holdout["metrics"],
            "training": train_diagnostics,
            "holdout": holdout_diag,
            "signal_diagnostics": baseline["diagnostics"],
        },
        "selected_holdout_diagnostics": holdout_diagnostics,
        "limitations": [
            "Parameter selection and ranking use training data only; holdout is evaluated once only if a candidate passes all training gates.",
            "The grid is a bounded experiment, not exhaustive optimization; results can overfit the training period.",
            "A small or zero-trade holdout is inconclusive, not evidence of safety or profitability.",
            "Volatility buckets are descriptive terciles within each segment, not optimized filters.",
            "Fees and slippage are assumptions, not verified broker fills; OHLC exits use conservative stop-first handling.",
            "Closed-trade drawdown excludes intratrade mark-to-market losses and gap/liquidity risks.",
        ],
        "broker_api_called": False,
        "market_data_api_read": False,
        "order_submitted": False,
        "alpaca_write_api_called": False,
        "automated_execution": False,
    }
