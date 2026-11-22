"""Stage 5.11: stop-loss root-cause and entry-quality diagnostics.

Describes frozen Stage 5.7 candidate and Stage 4.4 baseline trades using only
the chronological training slice. Entry features use pre-entry completed bars;
post-entry excursions and post-exit recovery are outcome diagnostics only.
No parameter search, tuning, or strategy promotion.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

try:
    from .stage43 import (
        run_breakout_backtest, _stamp, aggregate_complete_5m, ema_values,
    )
    from .stage44 import build_stage44_signals
    from .stage55 import audit_bar_integrity
    from .stage57 import build_stage57_candidate_signals
except ImportError:
    from stage43 import run_breakout_backtest, _stamp, aggregate_complete_5m, ema_values
    from stage44 import build_stage44_signals
    from stage55 import audit_bar_integrity
    from stage57 import build_stage57_candidate_signals


def _pf(values: list[float]):
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    return round(gains / losses, 4) if losses else ("infinite" if gains else None)


def _safe_div(a: float, b: float):
    return a / b if b else None


def _bucket(value: float | None, negative: str, neutral: str, positive: str,
            threshold: float = 0.15) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value <= -threshold:
        return negative
    if value >= threshold:
        return positive
    return neutral


def _prepare_entry_context(bars: list[dict], atrs: list[float | None]) -> list[dict]:
    hourly = aggregate_complete_5m(bars, 60)
    hourly_close = [float(x["c"]) for x in hourly]
    h_ema50, h_ema200 = ema_values(hourly_close, 50), ema_values(hourly_close, 200)
    hour_state = {}
    for i, item in enumerate(hourly):
        valid = h_ema50[i] is not None and h_ema200[i] is not None
        hour_state[item["bucket"]] = (
            "BULL" if valid and h_ema50[i] > h_ema200[i] and hourly_close[i] > h_ema50[i]
            else "BEAR" if valid and h_ema50[i] < h_ema200[i] and hourly_close[i] < h_ema50[i]
            else "MIXED"
        )

    hour_keys = sorted(hour_state)
    cursor = 0
    contexts = []
    atr_history = []
    for i, bar in enumerate(bars):
        close_ts = int(_stamp(bar).timestamp()) + 300
        latest_hour = close_ts // 3600 - 1
        while cursor + 1 < len(hour_keys) and hour_keys[cursor + 1] <= latest_hour:
            cursor += 1
        trend = hour_state[hour_keys[cursor]] if hour_keys and hour_keys[cursor] <= latest_hour else "UNAVAILABLE"
        atr = atrs[i]
        prior_atrs = [x for x in atr_history[-100:] if x is not None and x > 0]
        atr_mid = median(prior_atrs) if prior_atrs else None
        if atr is None or atr <= 0:
            vol = "UNAVAILABLE"
        elif atr_mid is None:
            vol = "UNAVAILABLE"
        elif atr < atr_mid * 0.8:
            vol = "LOW"
        elif atr > atr_mid * 1.25:
            vol = "HIGH"
        else:
            vol = "NORMAL"

        momentum = {}
        for lookback in (3, 6, 12):
            if i >= lookback and atr and atr > 0:
                momentum[lookback] = (float(bar["c"]) - float(bars[i-lookback]["c"])) / atr
            else:
                momentum[lookback] = None
        recent = bars[max(0, i-12):i]
        prior_range = (
            (max(float(x["h"]) for x in recent) - min(float(x["l"]) for x in recent)) / atr
            if recent and atr and atr > 0 else None
        )
        contexts.append({
            "hourly_trend": trend,
            "volatility": vol,
            "momentum_3_atr": round(momentum[3], 4) if momentum[3] is not None else None,
            "momentum_6_atr": round(momentum[6], 4) if momentum[6] is not None else None,
            "momentum_12_atr": round(momentum[12], 4) if momentum[12] is not None else None,
            "momentum_bucket": _bucket(momentum[3], "ADVERSE", "FLAT", "FAVORABLE"),
            "prior_12bar_range_atr": round(prior_range, 4) if prior_range is not None else None,
            "atr": float(atr) if atr is not None else None,
        })
        atr_history.append(atr)
    return contexts


def _analyse_trades(
    trades: list[dict], bars: list[dict], atrs: list[float | None],
    contexts: list[dict], stop_atr_multiple: float = 1.5,
) -> dict:
    index_by_time = {bar.get("t"): i for i, bar in enumerate(bars)}
    rows = []
    group_map: dict[str, list[dict]] = defaultdict(list)
    exit_map: dict[str, list[dict]] = defaultdict(list)
    recovery_stop_count = 0
    early_adverse_stops = 0
    stop_count = 0
    unmapped = 0

    for trade in trades:
        entry_i = index_by_time.get(trade.get("entry_time"))
        exit_i = index_by_time.get(trade.get("exit_time"))
        if entry_i is None or exit_i is None or exit_i < entry_i:
            unmapped += 1
            continue
        entry = float(trade["entry_price"])
        exit_price = float(trade["exit_price"])
        qty = 10.0 / entry
        signal_i = entry_i - 1
        ctx = contexts[signal_i] if signal_i >= 0 else {}
        atr = atrs[signal_i] if signal_i >= 0 else None
        risk_distance = float(atr) * stop_atr_multiple if atr is not None and atr > 0 else None
        path = bars[entry_i:exit_i+1]
        mfe = max((float(x["h"]) for x in path), default=entry) - entry
        mae = entry - min((float(x["l"]) for x in path), default=entry)
        mfe_r = _safe_div(mfe, risk_distance)
        mae_r = _safe_div(mae, risk_distance)
        bars_held = max(0, exit_i-entry_i)
        stop = str(trade.get("exit_reason", "")).startswith("STOP_LOSS")
        if stop:
            stop_count += 1
            if bars_held <= 3 and (mae_r or 0) >= 0.75:
                early_adverse_stops += 1
        recovery = {}
        if stop:
            for horizon in (3, 6, 12):
                future = bars[exit_i+1:exit_i+1+horizon]
                recovery[horizon] = (
                    round(max(float(x["h"]) for x in future) - entry, 4)
                    if future else None
                )
            if any(x is not None and x > 0 for x in recovery.values()):
                recovery_stop_count += 1
        reason = str(trade.get("exit_reason") or "UNKNOWN")
        item = {
            "entry_time": trade.get("entry_time"),
            "exit_time": trade.get("exit_time"),
            "exit_reason": reason,
            "net_pnl_usd": float(trade.get("net_pnl_usd") or 0),
            "gross_pnl_usd": float(trade.get("gross_pnl_usd") or 0),
            "bars_held": bars_held,
            "mfe_usd_per_btc": round(mfe, 4),
            "mae_usd_per_btc": round(mae, 4),
            "mfe_r": round(mfe_r, 4) if mfe_r is not None else None,
            "mae_r": round(mae_r, 4) if mae_r is not None else None,
            "hourly_trend_before_entry": ctx.get("hourly_trend", "UNAVAILABLE"),
            "volatility_before_entry": ctx.get("volatility", "UNAVAILABLE"),
            "momentum_bucket_before_entry": ctx.get("momentum_bucket", "UNAVAILABLE"),
            "momentum_3_atr_before_entry": ctx.get("momentum_3_atr"),
            "prior_12bar_range_atr": ctx.get("prior_12bar_range_atr"),
            "initial_stop_distance_usd_per_btc": round(risk_distance, 4) if risk_distance else None,
            "recovery_max_price_change_after_stop": recovery if stop else None,
        }
        rows.append(item)
        group_map[item["hourly_trend_before_entry"] + "_" + item["volatility_before_entry"]].append(item)
        exit_map[reason].append(item)

    def summarize(items: list[dict]) -> dict:
        nets = [x["net_pnl_usd"] for x in items]
        gross = [x["gross_pnl_usd"] for x in items]
        stops = [x for x in items if x["exit_reason"].startswith("STOP_LOSS")]
        mfe_values = [x["mfe_r"] for x in items if x["mfe_r"] is not None]
        mae_values = [x["mae_r"] for x in items if x["mae_r"] is not None]
        return {
            "trades": len(items),
            "stop_loss_trades": len(stops),
            "stop_loss_share_percent": round(len(stops)/len(items)*100, 2) if items else 0,
            "net_wins": sum(x > 0 for x in nets),
            "win_rate_percent": round(sum(x > 0 for x in nets)/len(items)*100, 2) if items else 0,
            "gross_pnl_usd": round(sum(gross), 4),
            "net_pnl_usd": round(sum(nets), 4),
            "net_profit_factor": _pf(nets),
            "median_mfe_r": round(median(mfe_values), 4) if mfe_values else None,
            "median_mae_r": round(median(mae_values), 4) if mae_values else None,
            "median_bars_held": round(median([x["bars_held"] for x in items]), 2) if items else None,
        }

    return {
        "summary": {
            **summarize(rows),
            "unmapped_trades": unmapped,
            "stop_loss_trades": stop_count,
            "stop_loss_recovered_above_entry_within_3_6_or_12_bars": recovery_stop_count,
            "early_adverse_stop_loss_within_3_bars": early_adverse_stops,
            "median_stop_loss_mae_r": round(median([x["mae_r"] for x in rows if x["exit_reason"].startswith("STOP_LOSS") and x["mae_r"] is not None]), 4) if any(x["exit_reason"].startswith("STOP_LOSS") and x["mae_r"] is not None for x in rows) else None,
        },
        "entry_regime_attribution": {k: summarize(v) for k, v in sorted(group_map.items())},
        "exit_reason_attribution": {k: summarize(v) for k, v in sorted(exit_map.items())},
        "trade_ledger": rows[-50:],
    }


def run_stage511_stop_loss_diagnostics(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.11")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    integrity = audit_bar_integrity(bars)
    if not integrity["structural_integrity_passed"]:
        return {
            "stage": "5.11", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": integrity, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    training_bars = bars[:split]
    candidate = build_stage57_candidate_signals(training_bars)
    baseline = build_stage44_signals(
        training_bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    candidate_bt = run_breakout_backtest(
        training_bars, candidate["signals"], candidate["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    baseline_bt = run_breakout_backtest(
        training_bars, baseline["signals"]["breakout_pullback_relvol"],
        baseline["atr_by_base"], starting_equity, notional_usd,
        fee_rate, slippage_bps,
    )
    contexts = _prepare_entry_context(training_bars, candidate["atr_by_base"])
    candidate_report = _analyse_trades(
        candidate_bt["trades"], training_bars, candidate["atr_by_base"], contexts,
    )
    baseline_contexts = _prepare_entry_context(training_bars, baseline["atr_by_base"])
    baseline_report = _analyse_trades(
        baseline_bt["trades"], training_bars, baseline["atr_by_base"], baseline_contexts,
    )

    cs = candidate_report["summary"]
    diagnosis = []
    if cs["stop_loss_share_percent"] >= 60:
        diagnosis.append("Stop-loss exits dominate candidate trades; investigate entry timing and signal quality before changing stop distance.")
    if cs["early_adverse_stop_loss_within_3_bars"]:
        diagnosis.append("Some stop-loss trades move materially against entry within three bars; review late entries or adverse short-term momentum.")
    if cs["stop_loss_recovered_above_entry_within_3_6_or_12_bars"]:
        diagnosis.append("Some stopped trades later traded above entry within the observation window; this is descriptive only and does not prove the stop was too tight.")
    if cs["median_stop_loss_mae_r"] is not None:
        diagnosis.append("Median adverse excursion on stop-loss trades is reported in R to compare realized adverse movement with the fixed initial stop model.")
    diagnosis.append("Hourly trend, volatility and momentum groups use only completed pre-entry bars; recovery uses post-exit bars solely as an outcome diagnostic.")
    diagnosis.append("No causal claim, parameter search, stop widening, signal filter change or strategy promotion is performed.")
    return {
        "stage": "5.11",
        "status": "TRAINING_STOP_LOSS_DIAGNOSTIC_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": training_bars[0].get("t"), "to": training_bars[-1].get("t")},
        "candidate": {
            "name": "Frozen Stage 5.7 hourly trend-gated Stage 4.4 pullback + relative volume",
            "metrics": candidate_bt["metrics"],
            "diagnostics": candidate_report,
        },
        "baseline": {
            "name": "Frozen Stage 4.4 pullback + relative volume",
            "metrics": baseline_bt["metrics"],
            "diagnostics": baseline_report,
        },
        "diagnosis": diagnosis,
        "holdout": {
            "status": "SEALED_NOT_ACCESSED",
            "reason": "Only the chronological training slice is used for signals, trades and attribution.",
        },
        "limitations": [
            "Entry context uses the last completed pre-entry 5-minute bar and latest completed hourly trend state.",
            "MFE/MAE and recovery windows describe observed paths and do not establish causal reasons for stop-outs.",
            "Recovery windows are censored near the end of the training sample; incomplete horizons are reported as unavailable.",
            "Fixed 1.5 ATR stop and 2R target remain unchanged; no stop widening or strategy tuning.",
            "This is simulator research, not broker-fill verification.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
