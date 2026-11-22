"""Stage 4.3: causal BTC 15m Donchian breakout + volume + completed 1h trend research.

Long-only spot-compatible research simulator. No broker/order dependencies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median


def _stamp(bar: dict) -> datetime:
    value = datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def aggregate_complete_5m(bars: list[dict], group_minutes: int) -> list[dict]:
    """Aggregate aligned 5m bars, retaining only full contiguous HTF buckets."""
    if group_minutes not in (15, 60):
        raise ValueError("group_minutes must be 15 or 60")
    count_needed = group_minutes // 5
    seconds = group_minutes * 60
    grouped: dict[int, list[dict]] = {}
    for bar in bars:
        stamp = _stamp(bar)
        bucket = int(stamp.timestamp()) // seconds
        grouped.setdefault(bucket, []).append(bar)
    result = []
    for bucket, items in sorted(grouped.items()):
        items = sorted(items, key=lambda x: x["t"])
        if len(items) != count_needed:
            continue
        times = [int(_stamp(x).timestamp()) for x in items]
        if times != [times[0] + 300 * i for i in range(count_needed)]:
            continue
        result.append({
            "bucket": bucket,
            "t": items[0]["t"],
            "o": float(items[0]["o"]),
            "h": max(float(x["h"]) for x in items),
            "l": min(float(x["l"]) for x in items),
            "c": float(items[-1]["c"]),
            "v": sum(float(x.get("v", 0) or 0) for x in items),
        })
    return result


def ema_values(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    value = sum(values[:period]) / period
    out[period - 1] = value
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        value = alpha * values[i] + (1 - alpha) * value
        out[i] = value
    return out


def atr_values(bars: list[dict], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return out
    ranges = []
    for i in range(1, len(bars)):
        high, low = float(bars[i]["h"]), float(bars[i]["l"])
        prev = float(bars[i - 1]["c"])
        ranges.append(max(high - low, abs(high - prev), abs(low - prev)))
    value = sum(ranges[:period]) / period
    out[period] = value
    for i in range(period + 1, len(bars)):
        value = (value * (period - 1) + ranges[i - 1]) / period
        out[i] = value
    return out


def build_breakout_signals(bars: list[dict], lookback: int = 20) -> dict:
    """Signals only on a 15m close; uses completed 15m and 1h candles."""
    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    m15 = aggregate_complete_5m(bars, 15)
    h1 = aggregate_complete_5m(bars, 60)
    m15_atr = atr_values(m15, 14)
    h1_close = [x["c"] for x in h1]
    h1_fast, h1_slow = ema_values(h1_close, 50), ema_values(h1_close, 200)
    h1_bull: dict[int, bool] = {}
    for i, item in enumerate(h1):
        h1_bull[item["bucket"]] = (
            h1_fast[i] is not None and h1_slow[i] is not None
            and h1_fast[i] > h1_slow[i] and h1_close[i] > h1_fast[i]
        )
    m15_by_bucket = {item["bucket"]: i for i, item in enumerate(m15)}
    h1_by_bucket = {item["bucket"]: i for i, item in enumerate(h1)}
    signals = {
        "breakout_only": [False] * len(bars),
        "breakout_volume": [False] * len(bars),
        "breakout_volume_1h": [False] * len(bars),
    }
    atr_by_base = [None] * len(bars)
    diagnostics = {"complete_15m_bars": len(m15), "complete_1h_bars": len(h1)}
    for i, bar in enumerate(bars):
        close_ts = int(_stamp(bar).timestamp()) + 300
        # Only evaluate at the close of a fully completed 15m bucket.
        if close_ts % 900 != 0:
            continue
        bucket15 = close_ts // 900 - 1
        pos15 = m15_by_bucket.get(bucket15)
        if pos15 is None or pos15 < max(lookback, 14):
            continue
        current = m15[pos15]
        previous = m15[pos15 - lookback:pos15]
        breakout = current["c"] > max(x["h"] for x in previous)
        vol_threshold = median(x["v"] for x in previous)
        volume_ok = current["v"] > vol_threshold
        atr_value = m15_atr[pos15]
        if atr_value is None or atr_value <= 0:
            continue
        # Map ATR to the final 5m candle of the completed 15m signal.
        atr_by_base[i] = atr_value
        signals["breakout_only"][i] = breakout
        signals["breakout_volume"][i] = breakout and volume_ok
        # Use the latest fully completed hourly bucket, never the live hour.
        bucket1h = close_ts // 3600 - 1
        pos1h = h1_by_bucket.get(bucket1h)
        if pos1h is None:
            earlier = [b for b in h1_by_bucket if b <= bucket1h]
            pos1h = h1_by_bucket[max(earlier)] if earlier else None
        trend_ok = pos1h is not None and h1_bull.get(h1[pos1h]["bucket"], False)
        signals["breakout_volume_1h"][i] = breakout and volume_ok and trend_ok
    diagnostics["signal_checks"] = sum(
        1 for i, bar in enumerate(bars)
        if (int(_stamp(bar).timestamp()) + 300) % 900 == 0
    )
    return {"signals": signals, "atr_by_base": atr_by_base, "diagnostics": diagnostics}


def run_breakout_backtest(
    bars: list[dict], signal_mask: list[bool], atr_by_base: list[float | None],
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    stop_atr_multiple: float = 1.5, reward_risk: float = 2.0,
) -> dict:
    """Long-only next-5m-open fill, conservative stop-first OHLC exits."""
    if len(signal_mask) != len(bars) or len(atr_by_base) != len(bars):
        raise ValueError("Signal and ATR arrays must match bars")
    if len(bars) < 50 or min(starting_equity, notional_usd, stop_atr_multiple, reward_risk) <= 0:
        raise ValueError("Invalid backtest input")
    if fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid transaction costs")
    slip = slippage_bps / 10000
    position, trades = None, []

    def close(candle: dict, raw_exit: float, reason: str):
        nonlocal position
        executed = raw_exit * (1 - slip)
        entry, qty = position["entry"], position["qty"]
        gross = (executed - entry) * qty
        fees = (entry + executed) * qty * fee_rate
        slip_cost = (entry - position["reference_entry"]) * qty + (raw_exit - executed) * qty
        trades.append({
            "entry_time": position["entry_time"], "exit_time": candle.get("t"),
            "entry_price": round(entry, 4), "exit_price": round(executed, 4),
            "exit_reason": reason, "gross_pnl_usd": round(gross, 4),
            "estimated_fees_usd": round(fees, 4),
            "estimated_slippage_usd": round(slip_cost, 4),
            "net_pnl_usd": round(gross - fees, 4),
        })
        position = None

    for i in range(len(bars) - 1):
        candle = bars[i]
        if position is not None:
            op, hi, lo = float(candle["o"]), float(candle["h"]), float(candle["l"])
            stop, target = position["stop"], position["target"]
            if op <= stop:
                close(candle, op, "STOP_LOSS_GAP")
            elif lo <= stop:
                close(candle, stop, "STOP_LOSS")
            elif op >= target:
                close(candle, op, "TAKE_PROFIT_GAP")
            elif hi >= target:
                close(candle, target, "TAKE_PROFIT")
            continue
        a = atr_by_base[i]
        if not signal_mask[i] or a is None or a <= 0:
            continue
        reference = float(bars[i + 1]["o"])
        if reference <= 0:
            continue
        entry = reference * (1 + slip)
        position = {
            "entry": entry, "reference_entry": reference,
            "qty": notional_usd / entry, "entry_time": bars[i + 1].get("t"),
            "stop": entry - stop_atr_multiple * a,
            "target": entry + stop_atr_multiple * reward_risk * a,
        }
        # The next-open fill candle is also checked for post-fill stop/target.
        op, hi, lo = float(bars[i + 1]["o"]), float(bars[i + 1]["h"]), float(bars[i + 1]["l"])
        if op <= position["stop"]:
            close(bars[i + 1], op, "STOP_LOSS_GAP")
        elif lo <= position["stop"]:
            close(bars[i + 1], position["stop"], "STOP_LOSS")
        elif op >= position["target"]:
            close(bars[i + 1], op, "TAKE_PROFIT_GAP")
        elif hi >= position["target"]:
            close(bars[i + 1], position["target"], "TAKE_PROFIT")

    if position is not None:
        close(bars[-1], float(bars[-1]["c"]), "END_OF_DATA")
    net = [x["net_pnl_usd"] for x in trades]
    gross = [x["gross_pnl_usd"] for x in trades]
    fees = sum(x["estimated_fees_usd"] for x in trades)
    slippage = sum(x["estimated_slippage_usd"] for x in trades)
    winners = sum(x > 0 for x in net)
    losers = sum(x < 0 for x in net)
    gross_profit = sum(x for x in gross if x > 0)
    gross_loss = -sum(x for x in gross if x < 0)
    net_profit = sum(x for x in net if x > 0)
    net_loss = -sum(x for x in net if x < 0)
    equity = peak = starting_equity
    drawdown = 0.0
    for value in net:
        equity += value
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(drawdown, (peak - equity) / peak * 100)
    def pf(profit, loss):
        return round(profit / loss, 4) if loss else ("infinite" if profit else None)
    metrics = {
        "starting_equity_usd": round(starting_equity, 2),
        "ending_equity_usd": round(equity, 2),
        "net_pnl_usd": round(sum(net), 4),
        "gross_pnl_usd": round(sum(gross), 4),
        "estimated_fees_usd": round(fees, 4),
        "estimated_slippage_usd": round(slippage, 4),
        "trades": len(trades), "wins": winners, "losses": losers,
        "win_rate_percent": round(winners / len(trades) * 100, 2) if trades else 0,
        "profit_factor": pf(gross_profit, gross_loss),
        "net_profit_factor": pf(net_profit, net_loss),
        "max_drawdown_percent": round(drawdown, 2),
        "average_net_per_trade_usd": round(sum(net) / len(net), 4) if net else 0,
    }
    return {"metrics": metrics, "trades": trades}
