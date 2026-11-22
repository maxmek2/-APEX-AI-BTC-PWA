"""Stage 5.7: fixed hourly-trend gate candidate, training-only diagnostics.

Candidate hypothesis: retain the frozen Stage 4.4 pullback + relative-volume
setup, but permit entries only when the latest completed 1h candle is in a
bullish EMA50/EMA200 regime and closes above EMA50. This is a single,
predeclared filter, not a parameter search. Holdout data is never evaluated.
"""
from __future__ import annotations

try:
    from .stage43 import aggregate_complete_5m, ema_values, run_breakout_backtest, _stamp
    from .stage44 import build_stage44_signals
    from .stage55 import audit_bar_integrity
except ImportError:
    from stage43 import aggregate_complete_5m, ema_values, run_breakout_backtest, _stamp
    from stage44 import build_stage44_signals
    from stage55 import audit_bar_integrity


def build_stage57_candidate_signals(bars: list[dict]) -> dict:
    """Build a causal, completed-hour trend gate over the frozen Stage 4.4 signal."""
    baseline = build_stage44_signals(
        bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    hourly = aggregate_complete_5m(bars, 60)
    closes = [float(item["c"]) for item in hourly]
    ema50, ema200 = ema_values(closes, 50), ema_values(closes, 200)
    hourly_state = {}
    for index, item in enumerate(hourly):
        valid = ema50[index] is not None and ema200[index] is not None
        hourly_state[item["bucket"]] = bool(
            valid and ema50[index] > ema200[index] and closes[index] > ema50[index]
        )

    hour_keys = sorted(hourly_state)
    cursor = 0
    candidate = [False] * len(bars)
    gate_checks = gate_passes = 0
    baseline_mask = baseline["signals"]["breakout_pullback_relvol"]
    for index, bar in enumerate(bars):
        close_ts = int(_stamp(bar).timestamp()) + 300
        latest_completed_hour = close_ts // 3600 - 1
        while cursor + 1 < len(hour_keys) and hour_keys[cursor + 1] <= latest_completed_hour:
            cursor += 1
        has_hour = bool(hour_keys and hour_keys[cursor] <= latest_completed_hour)
        trend_ok = has_hour and hourly_state[hour_keys[cursor]]
        if baseline_mask[index]:
            gate_checks += 1
            if trend_ok:
                candidate[index] = True
                gate_passes += 1

    return {
        "signals": candidate,
        "atr_by_base": baseline["atr_by_base"],
        "diagnostics": {
            **baseline["diagnostics"],
            "baseline_pullback_relvol_signals": sum(baseline_mask),
            "candidate_signals": sum(candidate),
            "hourly_trend_gate_checks": gate_checks,
            "hourly_trend_gate_passes": gate_passes,
            "hourly_trend_gate": "latest completed 1h EMA50 > EMA200 and 1h close > EMA50",
        },
    }


def _training_gate(metrics: dict, minimum_trades: int) -> bool:
    pf = metrics.get("net_profit_factor")
    pf_ok = pf == "infinite" or (isinstance(pf, (int, float)) and pf > 1)
    return (
        int(metrics.get("trades", 0)) >= minimum_trades
        and float(metrics.get("net_pnl_usd", 0)) > 0
        and pf_ok
    )


def run_stage57_candidate_report(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60, minimum_training_trades: int = 30,
) -> dict:
    """Compare baseline and one fixed filter on training bars only."""
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.7")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if minimum_training_trades < 10 or minimum_training_trades > 500:
        raise ValueError("minimum_training_trades must be between 10 and 500")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.7", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": audit, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    training_bars = bars[:split]
    built = build_stage57_candidate_signals(training_bars)
    baseline = build_stage44_signals(
        training_bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    baseline_result = run_breakout_backtest(
        training_bars, baseline["signals"]["breakout_pullback_relvol"],
        baseline["atr_by_base"], starting_equity, notional_usd,
        fee_rate, slippage_bps,
    )
    candidate_result = run_breakout_backtest(
        training_bars, built["signals"], built["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    baseline_metrics = baseline_result["metrics"]
    candidate_metrics = candidate_result["metrics"]
    return {
        "stage": "5.7",
        "status": "TRAINING_CANDIDATE_DIAGNOSTIC_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": training_bars[0].get("t"), "to": training_bars[-1].get("t")},
        "candidate": {
            "name": "Stage 4.4 pullback + relative volume + completed 1h bullish EMA50/EMA200 gate",
            "parameters_frozen": True,
            "parameter_search": False,
            "holdout_based_selection": False,
            "diagnostics": built["diagnostics"],
            "baseline_training_metrics": baseline_metrics,
            "candidate_training_metrics": candidate_metrics,
            "training_gate_passed": _training_gate(candidate_metrics, minimum_training_trades),
            "trade_count_change": int(candidate_metrics.get("trades", 0)) - int(baseline_metrics.get("trades", 0)),
        },
        "baseline_training_metrics": baseline_metrics,
        "holdout": {
            "status": "SEALED_NOT_ACCESSED",
            "reason": "Stage 5.7 tests one predeclared candidate on training data only; no holdout signals or outcomes are calculated.",
        },
        "next_step": (
            "If the candidate is worth retaining, freeze its code and assumptions before a single untouched holdout evaluation."
            if _training_gate(candidate_metrics, minimum_training_trades)
            else "Candidate did not meet the training evidence gate; do not promote it or inspect holdout to rescue it."
        ),
        "limitations": [
            "This is one hypothesis test, not proof that the trend filter causes better outcomes.",
            "Training results are in-sample and cannot establish out-of-sample profitability.",
            "Fees and slippage are modelling assumptions, not verified broker fills.",
            "OHLC simulation cannot reconstruct intrabar liquidity or exact price path.",
            "No parameter optimization, strategy promotion, broker write call, or order submission occurs.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
