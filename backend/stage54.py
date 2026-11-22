"""Stage 5.4: chronological regime robustness and strategy suitability gates.

No parameter optimization. Market regimes are derived from completed bars only.
Each segment/fold uses fixed Stage 4.4 baseline parameters and read-only OHLC
simulation. Results are diagnostics, not a profitability certificate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

try:
    from .stage43 import aggregate_complete_5m, atr_values, ema_values, run_breakout_backtest, _stamp
    from .stage44 import build_stage44_signals
    from .stage48 import build_stage48_diagnostics
except ImportError:
    from stage43 import aggregate_complete_5m, atr_values, ema_values, run_breakout_backtest, _stamp
    from stage44 import build_stage44_signals
    from stage48 import build_stage48_diagnostics


def _round(value, digits=4):
    return round(float(value), digits)


def _quantile(values, p):
    ordered = sorted(values)
    if not ordered:
        return None
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def build_market_regimes(bars: list[dict]) -> dict:
    """Assign each base bar the latest fully closed 1h trend and 15m ATR regime."""
    m15 = aggregate_complete_5m(bars, 15)
    h1 = aggregate_complete_5m(bars, 60)
    atr15 = atr_values(m15, 14)
    hclose = [x["c"] for x in h1]
    fast, slow = ema_values(hclose, 20), ema_values(hclose, 50)
    hkeys = [x["bucket"] for x in h1]
    states = []
    for i, candle in enumerate(h1):
        if fast[i] is None or slow[i] is None:
            states.append("TREND_UNAVAILABLE")
        elif hclose[i] > fast[i] and fast[i] > slow[i]:
            states.append("BULL_TREND")
        elif hclose[i] < fast[i] and fast[i] < slow[i]:
            states.append("BEAR_TREND")
        else:
            states.append("MIXED_TREND")

    valid_atr = [float(x) / float(m15[i]["c"]) for i, x in enumerate(atr15)
                 if x is not None and float(x) > 0 and float(m15[i]["c"]) > 0]
    lo_cut = _quantile(valid_atr, 1/3)
    hi_cut = _quantile(valid_atr, 2/3)
    by15 = {x["bucket"]: i for i, x in enumerate(m15)}
    regime_by_base = [None] * len(bars)
    trend_by_base = [None] * len(bars)
    atr_pct_by_base = [None] * len(bars)
    cursor = 0
    for i, bar in enumerate(bars):
        close_ts = int(_stamp(bar).timestamp()) + 300
        # Regime for a decision at this 5m close; HTF inputs are completed only.
        b15 = close_ts // 900 - 1
        p15 = by15.get(b15)
        b1h = close_ts // 3600 - 1
        while cursor + 1 < len(hkeys) and hkeys[cursor + 1] <= b1h:
            cursor += 1
        hpos = cursor if hkeys and hkeys[cursor] <= b1h else None
        trend = states[hpos] if hpos is not None else "TREND_UNAVAILABLE"
        atrpct = None
        vol = "VOL_UNAVAILABLE"
        if p15 is not None and atr15[p15] is not None and float(m15[p15]["c"]) > 0:
            atrpct = float(atr15[p15]) / float(m15[p15]["c"])
            if lo_cut is not None and hi_cut is not None:
                vol = "LOW_VOLATILITY" if atrpct <= lo_cut else (
                    "MID_VOLATILITY" if atrpct <= hi_cut else "HIGH_VOLATILITY"
                )
        regime_by_base[i] = trend + "|" + vol
        trend_by_base[i] = trend
        atr_pct_by_base[i] = atrpct
    return {
        "regime_by_base": regime_by_base,
        "trend_by_base": trend_by_base,
        "atr_pct_by_base": atr_pct_by_base,
        "volatility_thresholds": {
            "method": "ATR14/close terciles over complete 15m bars in this historical sample; descriptive, not predictive",
            "low_high": _round(lo_cut * 100, 6) if lo_cut is not None else None,
            "high_high": _round(hi_cut * 100, 6) if hi_cut is not None else None,
        },
        "complete_15m_bars": len(m15),
        "complete_1h_bars": len(h1),
    }


def _summarize(trades: list[dict], starting_equity: float, notional_usd: float) -> dict:
    pnls = [float(t.get("net_pnl_usd") or 0) for t in trades]
    winners = [x for x in pnls if x > 0]
    losers = [-x for x in pnls if x < 0]
    pos, neg = sum(winners), sum(losers)
    eq = peak = starting_equity
    dd = 0.0
    for pnl in pnls:
        eq += pnl
        peak = max(peak, eq)
        if peak > 0:
            dd = max(dd, (peak - eq) / peak * 100)
    pf = _round(pos / neg) if neg else ("infinite" if pos else None)
    fees = sum(float(t.get("estimated_fees_usd") or 0) for t in trades)
    slip = sum(float(t.get("estimated_slippage_usd") or 0) for t in trades)
    return {
        "trades": len(trades), "wins": len(winners), "losses": len(losers),
        "win_rate_percent": _round(len(winners) / len(trades) * 100) if trades else 0,
        "net_pnl_usd": _round(sum(pnls)), "net_profit_factor": pf,
        "max_closed_trade_drawdown_percent": _round(dd),
        "fees_usd": _round(fees), "estimated_slippage_usd": _round(slip),
        "ending_equity_usd": _round(eq),
        "average_net_per_trade_usd": _round(sum(pnls) / len(pnls)) if pnls else 0,
    }


def _regime_trades(trades: list[dict], bars: list[dict], regimes: list[str]) -> dict:
    by_time = {str(bar.get("t")): i for i, bar in enumerate(bars) if bar.get("t")}
    groups = {}
    for trade in trades:
        idx = by_time.get(str(trade.get("entry_time")))
        signal_idx = idx - 1 if idx is not None else None
        key = regimes[signal_idx] if signal_idx is not None and signal_idx >= 0 else "UNCLASSIFIED"
        groups.setdefault(key, []).append(trade)
    return {key: _summarize(group, 100.0, 10.0) for key, group in sorted(groups.items())}


def _segment_gate(metrics: dict, minimum_trades: int, max_drawdown: float) -> bool:
    pf = metrics.get("net_profit_factor")
    pf_ok = pf == "infinite" or (isinstance(pf, (int, float)) and pf > 1)
    return (
        metrics["trades"] >= minimum_trades
        and metrics["net_pnl_usd"] > 0
        and pf_ok
        and metrics["max_closed_trade_drawdown_percent"] <= max_drawdown
    )


def run_stage54_report(
    bars: list[dict], starting_equity: float = 100.0,
    notional_usd: float = 10.0, fee_rate: float = 0.0025,
    slippage_bps: float = 5.0, folds: int = 4,
    minimum_trades_per_fold: int = 10, max_drawdown_percent: float = 5.0,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.4 regime and fold diagnostics")
    if folds < 3 or folds > 6:
        raise ValueError("folds must be between 3 and 6")
    if minimum_trades_per_fold < 3 or minimum_trades_per_fold > 100:
        raise ValueError("minimum_trades_per_fold must be between 3 and 100")
    if not 0 < max_drawdown_percent <= 50:
        raise ValueError("max_drawdown_percent must be within (0, 50]")

    built = build_stage44_signals(
        bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    mask = built["signals"]["breakout_pullback_relvol"]
    atrs = built["atr_by_base"]
    regime = build_market_regimes(bars)
    split = int(len(bars) * 0.60)
    first_holdout_fill = bars[split + 1].get("t")
    train_result = run_breakout_backtest(
        bars[:split], mask[:split], atrs[:split],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    hold_result = run_breakout_backtest(
        bars, mask, atrs, starting_equity, notional_usd,
        fee_rate, slippage_bps, start_index=split,
    )
    hold_trades = hold_result["trades"]
    boundary_ok = all(
        t.get("entry_time") and t["entry_time"] >= first_holdout_fill
        for t in hold_trades
    )

    # Regime attribution calculated after simulation; regime labels use only
    # completed higher-timeframe candles and are attached at signal time.
    train_regimes = regime["regime_by_base"][:split]
    hold_regimes = regime["regime_by_base"]
    train_regime_metrics = _regime_trades(train_result["trades"], bars[:split], train_regimes)
    hold_regime_metrics = _regime_trades(hold_trades, bars, hold_regimes)

    # Later, non-overlapping chronological folds are all fixed-parameter tests.
    # Each fold starts flat. No fold is used to tune or choose parameters.
    hold_start = split + 1
    hold_len = len(bars) - hold_start
    fold_reports = []
    for k in range(folds):
        start = hold_start + (hold_len * k) // folds
        end = hold_start + (hold_len * (k + 1)) // folds
        if end - start < 100:
            continue
        # Backtest may only fill after the segment begins; previous indicator
        # values are retained as warmup, but signals before the fold are masked.
        fold_mask = [False] * len(bars)
        for i in range(start, end):
            fold_mask[i] = bool(mask[i])
        result = run_breakout_backtest(
            bars, fold_mask, atrs, starting_equity, notional_usd,
            fee_rate, slippage_bps, start_index=start,
        )
        trades = result["trades"]
        valid = all(t.get("entry_time") and t["entry_time"] >= bars[start + 1].get("t") for t in trades)
        fold_reports.append({
            "fold": k + 1, "from": bars[start].get("t"), "to": bars[end - 1].get("t"),
            "metrics": _summarize(trades, starting_equity, notional_usd),
            "entries_after_fold_start": valid,
            "regime_attribution": _regime_trades(trades, bars, regime["regime_by_base"]),
        })

    min_hold_trades = minimum_trades_per_fold * folds
    train_metrics = train_result["metrics"]
    hold_metrics = hold_result["metrics"]
    # Multiple fold count and trade count are evidence minimums, not certification.
    passed_folds = sum(
        f["entries_after_fold_start"] and _segment_gate(
            f["metrics"], minimum_trades_per_fold, max_drawdown_percent
        ) for f in fold_reports
    )
    adequate_sample = (
        len(fold_reports) == folds
        and all(f["metrics"]["trades"] >= minimum_trades_per_fold for f in fold_reports)
    )
    all_folds_positive = all(f["metrics"]["net_pnl_usd"] > 0 for f in fold_reports) if fold_reports else False
    folds_gate = adequate_sample and all_folds_positive and passed_folds == folds
    train_pass = _segment_gate(train_metrics, min_hold_trades, max_drawdown_percent * 2)
    hold_pass = (
        boundary_ok
        and _segment_gate(hold_metrics, min_hold_trades, max_drawdown_percent)
    )
    result_status = "NOT_ROBUST_RESEARCH_ONLY"
    if train_pass and hold_pass and folds_gate:
        result_status = "HISTORICAL_GATES_PASSED_NOT_CERTIFIED"
    elif not adequate_sample:
        result_status = "INSUFFICIENT_OUT_OF_SAMPLE_SAMPLE"
    return {
        "stage": "5.4",
        "status": result_status,
        "symbol": "BTC/USD",
        "timeframe": "5Min",
        "bars_used": len(bars),
        "period": {"from": bars[0].get("t"), "to": bars[-1].get("t")},
        "split": {
            "method": "chronological 60/40; fixed strategy, no optimization",
            "training_bars": split,
            "holdout_bars": len(bars) - split,
            "first_possible_holdout_fill": first_holdout_fill,
            "holdout_entries_after_split": boundary_ok,
        },
        "frozen_strategy": {
            "donchian_lookback": 20, "relative_volume_threshold": 1.5,
            "pullback_atr": 0.25, "pullback_bars": 4,
            "stop_atr_multiple": 1.5, "reward_risk": 2.0,
            "selection_or_optimization": False,
        },
        "assumptions": {
            "starting_equity_usd": starting_equity,
            "fixed_notional_usd": notional_usd,
            "fee_per_side_percent": fee_rate * 100,
            "slippage_bps_per_side": slippage_bps,
            "entry": "Completed 15m signal; next 5m open.",
            "higher_timeframe": "Latest fully completed hourly EMA20/EMA50 trend; no live-hour use.",
            "folds": "Non-overlapping chronological holdout folds; each starts flat; no fold selection.",
        },
        "training": {
            "metrics": train_metrics,
            "diagnostics": build_stage48_diagnostics(
                bars[:split], train_result["trades"], mask[:split], atrs[:split]
            ),
            "regime_attribution": train_regime_metrics,
            "gate_passed": train_pass,
        },
        "holdout": {
            "metrics": hold_metrics,
            "diagnostics": build_stage48_diagnostics(
                bars, hold_trades, mask, atrs
            ),
            "regime_attribution": hold_regime_metrics,
            "gate_passed": hold_pass,
        },
        "walk_forward_folds": fold_reports,
        "fold_summary": {
            "fold_count": len(fold_reports),
            "required_trades_per_fold": minimum_trades_per_fold,
            "passing_folds": passed_folds,
            "adequate_sample": adequate_sample,
            "all_folds_positive": all_folds_positive,
            "gate_passed": folds_gate,
        },
        "market_regime": {
            "trend_definitions": "Bull: completed H1 close>EMA20>EMA50; bear: close<EMA20<EMA50; otherwise mixed; unavailable during warm-up.",
            "volatility_thresholds": regime["volatility_thresholds"],
            "complete_15m_bars": regime["complete_15m_bars"],
            "complete_1h_bars": regime["complete_1h_bars"],
            "trade_attribution_is_descriptive_not_a_filter": True,
        },
        "decision_gates": {
            "training_gate": train_pass,
            "holdout_gate": hold_pass,
            "walk_forward_gate": folds_gate,
            "all_gates_passed": train_pass and hold_pass and folds_gate,
            "minimum_holdout_trades": min_hold_trades,
            "minimum_trades_each_fold": minimum_trades_per_fold,
            "max_holdout_closed_trade_drawdown_percent": max_drawdown_percent,
        },
        "limitations": [
            "One historical train/holdout split and a small number of sequential folds do not prove future profitability.",
            "The same frozen Stage 4.4 strategy is evaluated; Stage 5.4 does not create or select new entry rules.",
            "Regime attribution is descriptive and must not be used to cherry-pick or suppress losses without a new independent test.",
            "ATR terciles are computed from this sample; they are descriptive context, not forward-looking thresholds.",
            "Fees and slippage are assumptions; Alpaca crypto volume is venue-specific, not consolidated market volume.",
            "OHLC simulation assumes conservative stop-first order when stop and target are both touched; intrabar path and gaps/liquidity are imperfectly represented.",
            "Drawdown is closed-trade only; intratrade mark-to-market drawdown is not modeled.",
            "No order, account, or position API is called. This is not broker fill history.",
        ],
        "market_data_api_read": True,
        "broker_api_called": False,
        "alpaca_write_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
