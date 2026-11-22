"""Stage 5.16: trade-path excursion and threshold-order diagnostics.

Replays frozen Stage 5.7 candidate and Stage 4.4 baseline on the training
slice only. Measures MFE/MAE, first +/-0.5R threshold bar, pre-exit versus
exit-bar excursion, and OHLC same-bar ambiguity. Candle OHLC cannot establish
intrabar ordering; this module never infers tick-level sequence or changes
historical entries/exits.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

try:
    from .stage43 import run_breakout_backtest
    from .stage44 import build_stage44_signals
    from .stage55 import audit_bar_integrity
    from .stage57 import build_stage57_candidate_signals
except ImportError:
    from stage43 import run_breakout_backtest
    from stage44 import build_stage44_signals
    from stage55 import audit_bar_integrity
    from stage57 import build_stage57_candidate_signals


def _median(values):
    clean = [float(x) for x in values if x is not None]
    return round(median(clean), 4) if clean else None


def _analyse_trade_path(trade, bars, atr_by_base, index_by_time, stop_atr_multiple=1.5):
    entry_i = index_by_time.get(trade.get("entry_time"))
    exit_i = index_by_time.get(trade.get("exit_time"))
    if entry_i is None or exit_i is None or exit_i < entry_i:
        return None
    entry = float(trade["entry_price"])
    signal_i = entry_i - 1
    atr = atr_by_base[signal_i] if 0 <= signal_i < len(atr_by_base) else None
    risk = float(atr) * stop_atr_multiple if atr is not None and atr > 0 else None
    path = bars[entry_i:exit_i + 1]
    if not path or risk is None or risk <= 0:
        return None

    highs = [float(x["h"]) for x in path]
    lows = [float(x["l"]) for x in path]
    closes = [float(x["c"]) for x in path]
    mfe = max(0.0, max(highs) - entry) / risk
    mae = max(0.0, entry - min(lows)) / risk
    exit_bar = path[-1]
    prior = path[:-1]
    prior_mfe = max(0.0, max((float(x["h"]) for x in prior), default=entry) - entry) / risk
    prior_mae = max(0.0, entry - min((float(x["l"]) for x in prior), default=entry)) / risk
    exit_mfe = max(0.0, float(exit_bar["h"]) - entry) / risk
    exit_mae = max(0.0, entry - float(exit_bar["l"])) / risk

    favourable_bar = adverse_bar = None
    same_bar_ambiguous = False
    for offset, candle in enumerate(path):
        favourable = float(candle["h"]) >= entry + 0.5 * risk
        adverse = float(candle["l"]) <= entry - 0.5 * risk
        if favourable and favourable_bar is None:
            favourable_bar = offset
        if adverse and adverse_bar is None:
            adverse_bar = offset
        if favourable and adverse and favourable_bar == offset and adverse_bar == offset:
            same_bar_ambiguous = True
            break

    if same_bar_ambiguous:
        order = "SAME_BAR_ORDER_UNKNOWN"
    elif favourable_bar is None and adverse_bar is None:
        order = "NEITHER_HALF_R_THRESHOLD"
    elif favourable_bar is None:
        order = "ADVERSE_FIRST"
    elif adverse_bar is None:
        order = "FAVORABLE_FIRST"
    elif favourable_bar < adverse_bar:
        order = "FAVORABLE_FIRST"
    elif adverse_bar < favourable_bar:
        order = "ADVERSE_FIRST"
    else:
        order = "SAME_BAR_ORDER_UNKNOWN"

    close_progress = (closes[-1] - entry) / risk
    return {
        "entry_time": trade.get("entry_time"),
        "exit_time": trade.get("exit_time"),
        "exit_reason": str(trade.get("exit_reason") or "UNKNOWN"),
        "net_pnl_usd": float(trade.get("net_pnl_usd") or 0),
        "gross_pnl_usd": float(trade.get("gross_pnl_usd") or 0),
        "bars_held_including_entry": len(path),
        "initial_risk_distance_usd_per_btc": round(risk, 6),
        "mfe_r": round(mfe, 4),
        "mae_r": round(mae, 4),
        "pre_exit_bar_mfe_r": round(prior_mfe, 4),
        "pre_exit_bar_mae_r": round(prior_mae, 4),
        "exit_bar_mfe_r": round(exit_mfe, 4),
        "exit_bar_mae_r": round(exit_mae, 4),
        "first_favourable_half_r_bar": favourable_bar,
        "first_adverse_half_r_bar": adverse_bar,
        "half_r_threshold_order": order,
        "same_bar_order_ambiguous": same_bar_ambiguous,
        "exit_close_progress_r": round(close_progress, 4),
        "fraction_closes_below_entry": round(sum(x < entry for x in closes) / len(closes), 4),
    }


def _summarize(rows):
    n = len(rows)
    orders = defaultdict(int)
    for row in rows:
        orders[row["half_r_threshold_order"]] += 1
    return {
        "trades": n,
        "median_mfe_r": _median([x["mfe_r"] for x in rows]),
        "median_mae_r": _median([x["mae_r"] for x in rows]),
        "median_pre_exit_mfe_r": _median([x["pre_exit_bar_mfe_r"] for x in rows]),
        "median_pre_exit_mae_r": _median([x["pre_exit_bar_mae_r"] for x in rows]),
        "median_exit_close_progress_r": _median([x["exit_close_progress_r"] for x in rows]),
        "median_bars_held": _median([x["bars_held_including_entry"] for x in rows]),
        "favourable_first_trades": orders["FAVORABLE_FIRST"],
        "adverse_first_trades": orders["ADVERSE_FIRST"],
        "same_bar_order_ambiguous_trades": orders["SAME_BAR_ORDER_UNKNOWN"],
        "neither_threshold_trades": orders["NEITHER_HALF_R_THRESHOLD"],
        "order_unknown_warning": "OHLC candles identify the first threshold bar, not the intrabar order; same-bar high/low touches are explicitly ambiguous.",
    }


def _analyse(trades, bars, atrs):
    index = {bar.get("t"): i for i, bar in enumerate(bars)}
    rows = []
    groups = defaultdict(list)
    unmapped = 0
    for trade in trades:
        row = _analyse_trade_path(trade, bars, atrs, index)
        if row is None:
            unmapped += 1
            continue
        rows.append(row)
        groups[row["exit_reason"]].append(row)
    return {
        "summary": {**_summarize(rows), "unmapped_trades": unmapped},
        "exit_reason_path_attribution": {
            key: _summarize(items) for key, items in sorted(groups.items())
        },
        "trade_ledger": rows[-50:],
    }


def run_stage516_trade_path_diagnostics(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.16")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.16", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": audit, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    train = bars[:split]
    candidate = build_stage57_candidate_signals(train)
    baseline = build_stage44_signals(
        train, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    candidate_bt = run_breakout_backtest(
        train, candidate["signals"], candidate["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    baseline_bt = run_breakout_backtest(
        train, baseline["signals"]["breakout_pullback_relvol"],
        baseline["atr_by_base"], starting_equity, notional_usd,
        fee_rate, slippage_bps,
    )
    c_path = _analyse(candidate_bt["trades"], train, candidate["atr_by_base"])
    b_path = _analyse(baseline_bt["trades"], train, baseline["atr_by_base"])
    return {
        "stage": "5.16",
        "status": "TRAINING_TRADE_PATH_DIAGNOSTIC_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train[0].get("t"), "to": train[-1].get("t")},
        "candidate": {
            "name": "Frozen Stage 5.7 hourly trend-gated Stage 4.4 pullback + relative volume",
            "backtest_metrics": candidate_bt["metrics"],
            "path_diagnostics": c_path,
        },
        "baseline": {
            "name": "Frozen Stage 4.4 pullback + relative volume",
            "backtest_metrics": baseline_bt["metrics"],
            "path_diagnostics": b_path,
        },
        "findings": [
            "MFE/MAE and threshold order are descriptive path measurements from 5-minute OHLC bars, not tick-level execution evidence.",
            "A same-bar touch of both +/-0.5R thresholds is ambiguous; the actual order within that candle cannot be reconstructed.",
            "Pre-exit-bar excursion is reported separately from the exit candle to avoid treating the stop/target candle as a known prior path.",
            "The simulator uses a conservative stop-first rule when stop and target are both touched in one candle; this diagnostic does not alter that rule.",
            "No stop/target changes, parameter search, entry filters, sizing changes, strategy selection or promotion are performed.",
        ],
        "holdout": {"status": "SEALED_NOT_ACCESSED"},
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
