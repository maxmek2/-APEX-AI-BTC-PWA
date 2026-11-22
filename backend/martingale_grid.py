"""Experimental RSI + bearish-candle Martingale Grid signal model.

Research/signal generation only. It never submits, modifies, or closes broker orders.
BTC/USD Alpaca spot is long-only; SHORT_SETUP is a synthetic research signal.
"""
from __future__ import annotations

from typing import Any

CONFIG = {
    "strategy": "RSI14_BEARISH_MARTINGALE_GRID",
    "symbol": "BTC/USD",
    "timeframe": "5Min",
    "direction": "SHORT_ONLY",
    "starting_equity_usd": 100.0,
    "first_leg_notional_usd": 2.0,
    "grid_spacing_fraction": 0.005,
    "martingale_multiplier": 2.0,
    "max_legs": 2,
    "max_exposure_usd": 6.0,
    "take_profit_fraction": 0.01,
    "rsi_period": 14,
    "rsi_threshold": 55.0,
    "entry_rule": "RSI14 > 55 and previous completed candle bearish",
    "execution_mode": "RESEARCH_SIGNAL_ONLY",
    "broker_orders_enabled": False,
}

def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def build_signal(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Use completed, chronological bars supplied by the caller."""
    clean = [b for b in bars if all(k in b for k in ("o", "h", "l", "c", "t"))]
    if len(clean) < CONFIG["rsi_period"] + 2:
        return {
            **CONFIG, "signal": "INSUFFICIENT_DATA",
            "bars_used": len(clean), "rsi14": None,
            "last_bar_time": clean[-1].get("t") if clean else None,
        }
    closes = [float(b["c"]) for b in clean]
    rsi = _rsi(closes, CONFIG["rsi_period"])
    previous = clean[-2]
    bearish = float(previous["c"]) < float(previous["o"])
    eligible = rsi is not None and rsi > CONFIG["rsi_threshold"] and bearish
    return {
        **CONFIG,
        "signal": "SHORT_GRID_SETUP" if eligible else "WAIT",
        "rsi14": round(rsi, 2) if rsi is not None else None,
        "previous_candle_bearish": bearish,
        "last_completed_close": closes[-1],
        "last_bar_time": clean[-1].get("t"),
        "grid_levels": [
            round(closes[-1] * (1.0 + CONFIG["grid_spacing_fraction"] * i), 2)
            for i in range(1, CONFIG["max_legs"])
        ],
        "take_profit_reference": "1% below weighted-average short entry",
        "broker_orders_enabled": False,
        "note": "Synthetic SHORT research signal only; Alpaca BTC/USD spot integration does not execute short positions.",
    }
