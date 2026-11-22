"""Frozen RSI14 bearish-candle synthetic SHORT Martingale Grid research engine.

No broker writes, no real orders, and no claim that Alpaca BTC/USD spot can short.
The simulator is an OHLC approximation; intrabar path, funding and market depth
are unavailable. Ambiguous stop/target bars resolve stop-first.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

CONFIG = {
    "strategy": "RSI14_BEARISH_MARTINGALE_GRID", "symbol": "BTC/USD",
    "timeframe": "5Min", "direction": "SYNTHETIC_SHORT_ONLY",
    "starting_equity_usd": 100.0, "first_leg_notional_usd": 2.0,
    "grid_spacing_fraction": 0.005, "martingale_multiplier": 2.0,
    "max_legs": 2, "max_exposure_usd": 6.0, "take_profit_fraction": 0.01,
    "basket_stop_loss_usd": 5.0, "max_holding_hours": 48.0,
    "rsi_period": 14, "rsi_threshold": 55.0,
    "entry_rule": "RSI14 > 55 and latest completed candle bearish",
    "execution_mode": "SIMULATION_ONLY", "broker_orders_enabled": False,
}

def _timestamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (TypeError, ValueError):
        return None

def rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    def current() -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)
    out[period] = current()
    for i in range(period + 1, len(closes)):
        j = i - 1
        avg_gain = (avg_gain * (period - 1) + gains[j]) / period
        avg_loss = (avg_loss * (period - 1) + losses[j]) / period
        out[i] = current()
    return out

def build_signal(bars: list[dict[str, Any]]) -> dict[str, Any]:
    clean = [b for b in bars if all(k in b for k in ("o", "h", "l", "c", "t"))]
    closes = [float(b["c"]) for b in clean]
    values = rsi_series(closes, 14)
    rsi = values[-1] if values else None
    bearish = bool(clean and float(clean[-1]["c"]) < float(clean[-1]["o"]))
    eligible = rsi is not None and rsi > 55 and bearish
    last = closes[-1] if closes else None
    return {
        **CONFIG,
        "signal": "SHORT_GRID_SETUP" if eligible else ("WAIT" if len(clean) >= 16 else "INSUFFICIENT_DATA"),
        "rsi14": round(rsi, 2) if rsi is not None else None,
        "latest_completed_candle_bearish": bearish,
        "last_completed_close": last, "last_bar_time": clean[-1].get("t") if clean else None,
        "grid_level_reference": round(last * 1.005, 2) if last else None,
        "take_profit_reference": "1% below weighted-average short entry",
        "broker_orders_enabled": False,
        "note": "Synthetic SHORT research signal only; Alpaca BTC/USD spot does not execute short positions.",
    }

def _basket_net_at_exit(basket: dict, raw_exit: float, fee_rate: float, slip: float) -> tuple[float, float, float]:
    exit_price = raw_exit * (1.0 + slip)
    qty = sum(x["qty"] for x in basket["legs"])
    gross = sum(x["qty"] * (x["entry"] - exit_price) for x in basket["legs"])
    fees = basket["entry_fees"] + exit_price * qty * fee_rate
    return gross - fees, gross, fees

def _floating_net(basket: dict, mark: float, fee_rate: float, slip: float) -> float:
    return _basket_net_at_exit(basket, mark, fee_rate, slip)[0]

def _stop_price(basket: dict, stop_loss: float, fee_rate: float, slip: float) -> float:
    low = max(1e-8, min(x["entry"] for x in basket["legs"]) * 0.5)
    high = max(x["entry"] for x in basket["legs"]) * 10.0
    for _ in range(80):
        mid = (low + high) / 2
        if _floating_net(basket, mid, fee_rate, slip) <= -stop_loss:
            high = mid
        else:
            low = mid
    return high

def run_backtest(bars: list[dict[str, Any]], starting_equity: float = 100.0,
                 fee_rate: float = 0.0002, slippage_bps: float = 10.0,
                 start_index: int = 30) -> dict[str, Any]:
    """Fixed-parameter replay. Signal at close; first fill at next M5 open."""
    if len(bars) < 40:
        raise ValueError("At least 40 candles are required")
    if starting_equity <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid equity, fee, or slippage")
    if start_index < 16 or start_index >= len(bars) - 1:
        raise ValueError("start_index must leave a next-bar fill candle")
    clean = [dict(b) for b in bars]
    for b in clean:
        for key in ("o", "h", "l", "c"):
            b[key] = float(b[key])
        if min(b["o"], b["h"], b["l"], b["c"]) <= 0 or b["h"] < max(b["o"], b["c"], b["l"]) or b["l"] > min(b["o"], b["c"], b["h"]):
            raise ValueError("Invalid OHLC candle")
    rsi = rsi_series([b["c"] for b in clean], 14)
    slip = slippage_bps / 10000.0
    realized = 0.0
    basket: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    peak = starting_equity
    max_dd = max_float_loss = max_exposure = 0.0
    signals = 0

    def close_basket(bar: dict, raw_exit: float, reason: str) -> None:
        nonlocal basket, realized
        assert basket is not None
        net, gross, fees = _basket_net_at_exit(basket, raw_exit, fee_rate, slip)
        qty = sum(x["qty"] for x in basket["legs"])
        avg = sum(x["entry"] * x["qty"] for x in basket["legs"]) / qty
        trades.append({
            "entry_time": basket["entry_time"], "exit_time": bar.get("t"),
            "legs": len(basket["legs"]), "entry_prices": [round(x["entry"], 2) for x in basket["legs"]],
            "entry_notionals_usd": [round(x["notional"], 2) for x in basket["legs"]],
            "weighted_average_entry": round(avg, 2), "exit_price": round(raw_exit * (1 + slip), 2),
            "exit_reason": reason, "gross_pnl_usd": round(gross, 4),
            "fees_usd": round(fees, 4), "net_pnl_usd": round(net, 4),
        })
        realized += net
        basket = None

    for i in range(start_index, len(clean)):
        bar = clean[i]
        if basket is None and i > 0 and rsi[i - 1] is not None:
            previous = clean[i - 1]
            if rsi[i - 1] > 55 and previous["c"] < previous["o"]:
                signals += 1
                entry = bar["o"] * (1 - slip)
                notional = 2.0
                qty = notional / entry
                basket = {
                    "entry_time": bar.get("t"), "opened_at": _timestamp(bar.get("t")),
                    "legs": [{"entry": entry, "qty": qty, "notional": notional}],
                    "entry_fees": entry * qty * fee_rate,
                }
        if basket is not None:
            if len(basket["legs"]) < 2:
                grid = basket["legs"][0]["entry"] * 1.005
                if bar["h"] >= grid:
                    add_price = max(bar["o"], grid) * (1 - slip)
                    add_notional = min(4.0, 6.0 - sum(x["notional"] for x in basket["legs"]))
                    add_qty = add_notional / add_price
                    basket["legs"].append({"entry": add_price, "qty": add_qty, "notional": add_notional})
                    basket["entry_fees"] += add_price * add_qty * fee_rate
            exposure = sum(x["notional"] for x in basket["legs"])
            max_exposure = max(max_exposure, exposure)
            stop = _stop_price(basket, 5.0, fee_rate, slip)
            qty = sum(x["qty"] for x in basket["legs"])
            average = sum(x["entry"] * x["qty"] for x in basket["legs"]) / qty
            target = average * 0.99
            # Conservative OHLC ordering: stop first if both stop and target touched.
            if bar["h"] >= stop:
                close_basket(bar, max(bar["o"], stop), "BASKET_STOP_LOSS")
            elif bar["l"] <= target:
                close_basket(bar, min(bar["o"], target), "TAKE_PROFIT")
            else:
                opened = basket["opened_at"]
                now = _timestamp(bar.get("t"))
                if opened and now and (now - opened).total_seconds() >= 48 * 3600:
                    close_basket(bar, bar["c"], "MAX_HOLD")
        if basket is None:
            equity = starting_equity + realized
        else:
            floating = _floating_net(basket, bar["c"], fee_rate, slip)
            max_float_loss = max(max_float_loss, max(0.0, -floating))
            equity = starting_equity + realized + floating
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)

    floating = _floating_net(basket, clean[-1]["c"], fee_rate, slip) if basket else 0.0
    open_basket = None
    if basket:
        qty = sum(x["qty"] for x in basket["legs"])
        avg = sum(x["entry"] * x["qty"] for x in basket["legs"]) / qty
        open_basket = {
            "entry_time": basket["entry_time"], "legs": len(basket["legs"]),
            "entry_prices": [round(x["entry"], 2) for x in basket["legs"]],
            "exposure_usd": round(sum(x["notional"] for x in basket["legs"]), 2),
            "weighted_average_entry": round(avg, 2), "last_mark": round(clean[-1]["c"], 2),
            "unrealized_net_pnl_usd": round(floating, 4),
        }
    metrics = {
        "starting_equity_usd": round(starting_equity, 2),
        "realized_net_pnl_usd": round(realized, 4),
        "ending_equity_marked_usd": round(starting_equity + realized + floating, 4),
        "unrealized_net_pnl_usd": round(floating, 4),
        "closed_baskets": len(trades), "wins": sum(t["net_pnl_usd"] > 0 for t in trades),
        "losses": sum(t["net_pnl_usd"] < 0 for t in trades),
        "win_rate_percent": round(sum(t["net_pnl_usd"] > 0 for t in trades) / len(trades) * 100, 2) if trades else 0.0,
        "max_mark_to_market_drawdown_percent": round(max_dd, 4),
        "max_floating_loss_usd": round(max_float_loss, 4), "max_exposure_usd": round(max_exposure, 2),
        "signals": signals, "estimated_fee_per_side_percent": fee_rate * 100,
        "slippage_bps_per_side": slippage_bps,
    }
    return {
        "status": "SIMULATION_COMPLETE_RESEARCH_ONLY", "strategy": CONFIG,
        "metrics": metrics, "trades": trades[-100:], "open_basket": open_basket,
        "assumptions": [
            "Completed M5 close signal; next M5 open entry.",
            "Synthetic SHORT only; no Alpaca order or position API calls.",
            "Add $4 leg at +0.5% adverse move; max 2 legs / $6 notional.",
            "Stop aims at -$5 net including estimated fees/slippage; TP is 1% below weighted average.",
            "Maximum basket age 48 hours; stop-first OHLC handling.",
            "No funding, spread, borrowing, liquidation, true intrabar path or market-depth model.",
            "Open basket is marked to market, not silently liquidated at sample end.",
        ],
        "order_submitted": False, "alpaca_write_api_called": False,
        "automated_execution": False,
    }
