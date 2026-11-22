"""Stage 4.8: trade-level failure and cost attribution.

Descriptive diagnostics for the frozen Stage 4.4 pullback + relative-volume
baseline. No parameter selection, broker access, or order execution.
"""
from __future__ import annotations

from datetime import datetime
from statistics import median


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed
    except (TypeError, ValueError):
        return None


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def build_stage48_diagnostics(
    bars: list[dict],
    trades: list[dict],
    signal_mask: list[bool],
    atr_by_base: list[float | None],
) -> dict:
    """Summarize realized trades by exit reason, cost drag and signal volatility."""
    if not (len(bars) == len(signal_mask) == len(atr_by_base)):
        raise ValueError("Bars, signal mask and ATR arrays must have equal lengths")

    index_by_time = {
        str(bar.get("t")): index for index, bar in enumerate(bars) if bar.get("t")
    }
    signal_atr_pct = []
    for index, active in enumerate(signal_mask):
        atr_value = atr_by_base[index]
        close = float(bars[index].get("c") or 0)
        if active and atr_value is not None and float(atr_value) > 0 and close > 0:
            signal_atr_pct.append(float(atr_value) / close)

    ordered = sorted(signal_atr_pct)
    q1 = ordered[(len(ordered) - 1) // 3] if ordered else None
    q2 = ordered[(2 * (len(ordered) - 1)) // 3] if ordered else None

    exit_groups: dict[str, dict] = {}
    volatility_groups: dict[str, dict] = {}
    detail = []
    gross_positive_net_negative = 0
    hold_minutes = []

    for trade in trades:
        gross = float(trade.get("gross_pnl_usd") or 0)
        fees = float(trade.get("estimated_fees_usd") or 0)
        slippage = float(trade.get("estimated_slippage_usd") or 0)
        net = float(trade.get("net_pnl_usd") or 0)
        reason = str(trade.get("exit_reason") or "UNKNOWN")
        group = exit_groups.setdefault(reason, {
            "trades": 0, "wins": 0, "net_pnl_usd": 0.0,
            "gross_pnl_usd": 0.0, "fees_usd": 0.0, "slippage_usd": 0.0,
        })
        group["trades"] += 1
        group["wins"] += int(net > 0)
        group["net_pnl_usd"] += net
        group["gross_pnl_usd"] += gross
        group["fees_usd"] += fees
        group["slippage_usd"] += slippage
        gross_positive_net_negative += int(gross > 0 and net <= 0)

        entry_time = trade.get("entry_time")
        signal_index = index_by_time.get(str(entry_time))
        # The signal is the candle immediately before the next-open fill.
        signal_index = signal_index - 1 if signal_index is not None else None
        atr_pct = None
        regime = "UNCLASSIFIED"
        if signal_index is not None and signal_index >= 0:
            atr_value = atr_by_base[signal_index]
            close = float(bars[signal_index].get("c") or 0)
            if atr_value is not None and float(atr_value) > 0 and close > 0:
                atr_pct = float(atr_value) / close
                if q1 is not None and q2 is not None:
                    regime = "LOW_VOLATILITY" if atr_pct <= q1 else (
                        "MID_VOLATILITY" if atr_pct <= q2 else "HIGH_VOLATILITY"
                    )
        regime_group = volatility_groups.setdefault(regime, {
            "trades": 0, "wins": 0, "net_pnl_usd": 0.0,
            "gross_pnl_usd": 0.0, "fees_usd": 0.0, "slippage_usd": 0.0,
        })
        regime_group["trades"] += 1
        regime_group["wins"] += int(net > 0)
        regime_group["net_pnl_usd"] += net
        regime_group["gross_pnl_usd"] += gross
        regime_group["fees_usd"] += fees
        regime_group["slippage_usd"] += slippage

        entry_dt, exit_dt = _parse_time(entry_time), _parse_time(trade.get("exit_time"))
        duration = None
        if entry_dt and exit_dt:
            duration = max(0.0, (exit_dt - entry_dt).total_seconds() / 60)
            hold_minutes.append(duration)
        detail.append({
            "entry_time": entry_time, "exit_time": trade.get("exit_time"),
            "exit_reason": reason, "gross_pnl_usd": _round(gross),
            "fees_usd": _round(fees), "slippage_usd": _round(slippage),
            "net_pnl_usd": _round(net), "atr_percent_at_signal": _round(atr_pct * 100, 5) if atr_pct is not None else None,
            "volatility_regime": regime, "holding_minutes": _round(duration, 2) if duration is not None else None,
        })

    def finalize(groups: dict[str, dict]) -> dict:
        result = {}
        for name, item in groups.items():
            result[name] = {
                "trades": item["trades"], "wins": item["wins"],
                "win_rate_percent": _round(item["wins"] / item["trades"] * 100) if item["trades"] else 0,
                "net_pnl_usd": _round(item["net_pnl_usd"]),
                "gross_pnl_usd": _round(item["gross_pnl_usd"]),
                "fees_usd": _round(item["fees_usd"]),
                "slippage_usd": _round(item["slippage_usd"]),
            }
        return result

    gross_total = sum(float(x.get("gross_pnl_usd") or 0) for x in trades)
    fees_total = sum(float(x.get("estimated_fees_usd") or 0) for x in trades)
    slippage_total = sum(float(x.get("estimated_slippage_usd") or 0) for x in trades)
    net_total = sum(float(x.get("net_pnl_usd") or 0) for x in trades)
    return {
        "trade_count": len(trades),
        "signal_count": sum(bool(x) for x in signal_mask),
        "signal_rate_per_1000_bars": _round(sum(bool(x) for x in signal_mask) / len(bars) * 1000) if bars else 0,
        "cost_attribution": {
            "gross_pnl_usd": _round(gross_total),
            "fees_usd": _round(fees_total),
            "slippage_usd": _round(slippage_total),
            "net_pnl_usd": _round(net_total),
            "total_transaction_cost_usd": _round(fees_total + slippage_total),
            "gross_positive_but_net_nonpositive_trades": gross_positive_net_negative,
            "costs_exceeded_gross_profit": fees_total + slippage_total > max(gross_total, 0),
        },
        "exit_reason_breakdown": finalize(exit_groups),
        "volatility_regime_breakdown": finalize(volatility_groups),
        "volatility_thresholds": {
            "method": "Terciles of ATR14/close on eligible completed 15m signal bars; descriptive only.",
            "low_to_mid_atr_percent": _round(q1 * 100, 5) if q1 is not None else None,
            "mid_to_high_atr_percent": _round(q2 * 100, 5) if q2 is not None else None,
        },
        "holding_time_minutes": {
            "mean": _round(sum(hold_minutes) / len(hold_minutes), 2) if hold_minutes else None,
            "median": _round(median(hold_minutes), 2) if hold_minutes else None,
        },
        "trades": detail,
        "limitations": [
            "Volatility buckets are descriptive terciles from this same sample, not optimized filters or independent evidence.",
            "Exit reason counts reflect conservative OHLC stop-first simulation; intrabar path is unknown.",
            "Fees and slippage are assumptions, not verified broker fills or fee quotes.",
            "Closed-trade diagnostics exclude unrealized and intratrade mark-to-market drawdown.",
            "This report does not search parameters, rank strategies, or certify profitability.",
        ],
    }


def run_stage48_report(
    bars: list[dict], starting_equity: float = 100.0,
    notional_usd: float = 10.0, fee_rate: float = 0.0025,
    slippage_bps: float = 5.0,
) -> dict:
    try:
        from .stage44 import build_stage44_signals
        from .stage43 import run_breakout_backtest
    except ImportError:
        from stage44 import build_stage44_signals
        from stage43 import run_breakout_backtest

    built = build_stage44_signals(
        bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    mask = built["signals"]["breakout_pullback_relvol"]
    result = run_breakout_backtest(
        bars, mask, built["atr_by_base"], starting_equity,
        notional_usd, fee_rate, slippage_bps,
    )
    return {
        "parameters": {
            "donchian_lookback": 20, "relative_volume_threshold": 1.5,
            "pullback_atr": 0.25, "pullback_bars": 4,
            "stop_atr_multiple": 1.5, "reward_risk": 2.0,
        },
        "backtest_metrics": result["metrics"],
        "signal_diagnostics": built["diagnostics"],
        "diagnostics": build_stage48_diagnostics(
            bars, result["trades"], mask, built["atr_by_base"]
        ),
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        "parameter_selection_performed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "alpaca_write_api_called": False,
    }
