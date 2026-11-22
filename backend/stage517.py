"""Stage 5.17: fixed logarithmic-return momentum research backtest.

Uses log returns and a volatility-normalized momentum score. One predeclared
rule only; training slice only; holdout sealed. Long-only OHLC simulator,
next-5m-open entries, fixed 1.5 ATR stop / 2R target and conservative stop-first
same-candle resolution. No broker/order dependencies.
"""
from __future__ import annotations

from math import log, sqrt
from statistics import mean, pstdev

try:
    from .stage43 import aggregate_complete_5m, atr_values, run_breakout_backtest, _stamp
    from .stage55 import audit_bar_integrity
except ImportError:
    from stage43 import aggregate_complete_5m, atr_values, run_breakout_backtest, _stamp
    from stage55 import audit_bar_integrity


MOMENTUM_BARS = 12
VOLATILITY_WINDOW = 48
TREND_WINDOW = 48
MIN_MOMENTUM_Z = 0.5
STOP_ATR = 1.5
REWARD_RISK = 2.0


def _log_return(current: float, previous: float) -> float | None:
    if current <= 0 or previous <= 0:
        return None
    return log(current / previous)


def build_stage517_log_signals(bars: list[dict]) -> dict:
    """Build causal 15m-close signals from completed 5m close observations."""
    if len(bars) < 200:
        raise ValueError("At least 200 bars are required")
    closes = [float(x["c"]) for x in bars]
    if any(x <= 0 for x in closes):
        raise ValueError("All close prices must be positive for logarithms")

    one_bar = [None] * len(closes)
    for i in range(1, len(closes)):
        one_bar[i] = _log_return(closes[i], closes[i - 1])

    # ATR comes from completed 15m candles and is mapped only to their final 5m bar.
    m15 = aggregate_complete_5m(bars, 15)
    atr15 = atr_values(m15, 14)
    atr_by_base = [None] * len(bars)
    by_bucket = {x["bucket"]: i for i, x in enumerate(m15)}
    for i, bar in enumerate(bars):
        close_ts = int(_stamp(bar).timestamp()) + 300
        if close_ts % 900 != 0:
            continue
        p = by_bucket.get(close_ts // 900 - 1)
        if p is not None:
            atr_by_base[i] = atr15[p]

    signals = [False] * len(bars)
    diagnostics = {
        "signal_checks": 0, "valid_log_observations": 0,
        "positive_log_trend_checks": 0, "momentum_threshold_passes": 0,
        "signals": 0, "momentum_bars": MOMENTUM_BARS,
        "volatility_window": VOLATILITY_WINDOW, "trend_window": TREND_WINDOW,
        "minimum_momentum_z": MIN_MOMENTUM_Z,
        "signal_rule": "15m close; 12x5m cumulative log return / (48-bar log-return population stdev * sqrt(12)) >= 0.5; 48-bar log-price trend positive",
    }

    for i in range(len(bars)):
        close_ts = int(_stamp(bars[i]).timestamp()) + 300
        if close_ts % 900 != 0:
            continue
        diagnostics["signal_checks"] += 1
        start_vol = i - VOLATILITY_WINDOW + 1
        start_mom = i - MOMENTUM_BARS
        start_trend = i - TREND_WINDOW
        if start_vol < 1 or start_mom < 0 or start_trend < 0 or atr_by_base[i] is None or atr_by_base[i] <= 0:
            continue
        returns = [x for x in one_bar[start_vol:i + 1] if x is not None]
        if len(returns) != VOLATILITY_WINDOW:
            continue
        sigma = pstdev(returns)
        momentum = _log_return(closes[i], closes[start_mom])
        trend = _log_return(closes[i], closes[start_trend])
        if momentum is None or trend is None or sigma <= 0:
            continue
        diagnostics["valid_log_observations"] += 1
        if trend > 0:
            diagnostics["positive_log_trend_checks"] += 1
        z_score = momentum / (sigma * sqrt(MOMENTUM_BARS))
        if z_score >= MIN_MOMENTUM_Z:
            diagnostics["momentum_threshold_passes"] += 1
        if trend > 0 and z_score >= MIN_MOMENTUM_Z:
            signals[i] = True
            diagnostics["signals"] += 1

    return {"signals": signals, "atr_by_base": atr_by_base, "diagnostics": diagnostics}


def run_stage517_log_backtest(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.17")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.17", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": audit, "holdout_accessed": False,
            "broker_api_called": False, "order_submitted": False,
            "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    train = bars[:split]
    built = build_stage517_log_signals(train)
    result = run_breakout_backtest(
        train, built["signals"], built["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
        stop_atr_multiple=STOP_ATR, reward_risk=REWARD_RISK,
    )
    return {
        "stage": "5.17",
        "status": "TRAINING_LOG_RETURN_BACKTEST_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train[0].get("t"), "to": train[-1].get("t")},
        "strategy": {
            "name": "Log-return volatility-normalized momentum",
            "parameters_frozen": True, "parameter_search": False,
            "momentum_bars": MOMENTUM_BARS,
            "volatility_window": VOLATILITY_WINDOW,
            "trend_window": TREND_WINDOW,
            "minimum_momentum_z": MIN_MOMENTUM_Z,
            "stop_atr_multiple": STOP_ATR, "reward_risk": REWARD_RISK,
            "diagnostics": built["diagnostics"],
        },
        "metrics": result["metrics"],
        "trade_ledger": result["trades"][-50:],
        "holdout": {"status": "SEALED_NOT_ACCESSED"},
        "limitations": [
            "This is one predeclared logarithmic-return hypothesis, not an optimized strategy.",
            "All reported performance is in-sample training performance, not evidence of future profitability.",
            "Fees and slippage are fixed estimates and are not broker-verified.",
            "OHLC bars cannot establish intrabar order; the simulator uses conservative stop-first resolution.",
            "Long-only spot-compatible research; no broker write calls or automated execution.",
        ],
        "market_data_api_read": False, "holdout_accessed": False,
        "broker_api_called": False, "order_submitted": False,
        "automated_execution": False,
    }
