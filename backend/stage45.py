"""Stage 4.5: train-only parameter selection for pullback + relative volume.

A fixed parameter grid is evaluated on the training segment only. Exactly one
training-qualified configuration is then evaluated on the untouched holdout.
Read-only research; no broker or order dependencies.
"""
from __future__ import annotations

from itertools import product
from .stage44 import build_stage44_signals
from .stage43 import run_breakout_backtest


def run_stage45_report(
    bars: list[dict], train_fraction: float = 0.60,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
) -> dict:
    if not 0.50 < train_fraction < 0.80:
        raise ValueError("train_fraction must be between 0.50 and 0.80")
    split = int(len(bars) * train_fraction)
    if split < 1000 or len(bars) - split < 100:
        raise ValueError("Insufficient chronological training or holdout data")

    # Predeclared grid; no values are chosen after inspecting holdout results.
    grid = list(product((1.2, 1.5, 1.8), (0.15, 0.25, 0.40), (2, 4, 6)))
    candidates = []
    built_by_key = {}
    for volume_threshold, pullback_atr, pullback_bars in grid:
        key = (volume_threshold, pullback_atr, pullback_bars)
        built = build_stage44_signals(
            bars, lookback=20, relative_volume_threshold=volume_threshold,
            pullback_atr=pullback_atr, pullback_bars=pullback_bars,
        )
        mask = built["signals"]["breakout_pullback_relvol"]
        atrs = built["atr_by_base"]
        # Strict boundary: training data ends before the first holdout candle.
        train = run_breakout_backtest(
            bars[:split], mask[:split], atrs[:split],
            starting_equity, notional_usd, fee_rate, slippage_bps,
        )
        metrics = train["metrics"]
        candidates.append({
            "parameters": {
                "relative_volume_threshold": volume_threshold,
                "pullback_atr": pullback_atr,
                "pullback_bars": pullback_bars,
                "donchian_lookback": 20,
                "stop_atr_multiple": 1.5,
                "reward_risk": 2.0,
            },
            "training_metrics": metrics,
            "training_signals": sum(mask[:split]),
        })
        built_by_key[key] = built

    # Require at least 10 completed training trades, positive net P/L and PF > 1.
    qualified = [
        item for item in candidates
        if item["training_metrics"]["trades"] >= 10
        and item["training_metrics"]["net_pnl_usd"] > 0
        and isinstance(item["training_metrics"]["net_profit_factor"], (int, float))
        and item["training_metrics"]["net_profit_factor"] > 1.0
    ]
    # Deterministic selection using training metrics only.
    qualified.sort(key=lambda x: (
        x["training_metrics"]["net_pnl_usd"],
        x["training_metrics"]["net_profit_factor"],
        x["training_metrics"]["trades"],
    ), reverse=True)

    holdout = None
    selected = qualified[0] if qualified else None
    first_holdout_fill = bars[split + 1].get("t")
    if selected:
        p = selected["parameters"]
        key = (p["relative_volume_threshold"], p["pullback_atr"], p["pullback_bars"])
        built = built_by_key[key]
        mask, atrs = built["signals"]["breakout_pullback_relvol"], built["atr_by_base"]
        sensitivity = []
        for bps in (0, 5, 10, 20):
            result = run_breakout_backtest(
                bars, mask, atrs, starting_equity, notional_usd,
                fee_rate, bps, start_index=split,
            )
            entries = [x for x in result["trades"] if x.get("entry_time")]
            sensitivity.append({
                "slippage_bps_per_side": bps,
                "metrics": result["metrics"],
                "entries_after_split": all(x["entry_time"] >= first_holdout_fill for x in entries),
            })
        holdout = next(x for x in sensitivity if x["slippage_bps_per_side"] == slippage_bps) if slippage_bps in (0, 5, 10, 20) else None
        if holdout is None:
            result = run_breakout_backtest(
                bars, mask, atrs, starting_equity, notional_usd,
                fee_rate, slippage_bps, start_index=split,
            )
            entries = [x for x in result["trades"] if x.get("entry_time")]
            holdout = {
                "slippage_bps_per_side": slippage_bps,
                "metrics": result["metrics"],
                "entries_after_split": all(x["entry_time"] >= first_holdout_fill for x in entries),
            }
        holdout["cost_sensitivity"] = sensitivity
        holdout["holdout_signals"] = sum(mask[split:])

    return {
        "split_index": split,
        "first_possible_holdout_fill": first_holdout_fill,
        "grid_size": len(grid),
        "selection_rule": "Training only: >=10 trades, net P/L > 0, net profit factor > 1; rank by net P/L, then PF, then trade count.",
        "qualified_candidates": len(qualified),
        "selected_parameters": selected["parameters"] if selected else None,
        "selected_training_metrics": selected["training_metrics"] if selected else None,
        "holdout": holdout,
        "top_training_candidates": candidates[:0] + sorted(
            candidates,
            key=lambda x: (x["training_metrics"]["net_pnl_usd"],
                           x["training_metrics"]["trades"]),
            reverse=True,
        )[:10],
        "all_candidates_training_only": candidates,
        "diagnostics": {
            "selection_used_holdout": False,
            "holdout_evaluated_once": bool(selected),
            "holdout_entries_after_split": bool(holdout is None or holdout["entries_after_split"]),
            "read_only": True,
        },
    }
