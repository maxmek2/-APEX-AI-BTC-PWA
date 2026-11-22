"""Stage 5.12: entry timing and false-breakout diagnostics.

Fixed Stage 5.7 candidate and Stage 4.4 baseline; training slice only.
All entry features are built from completed bars available at signal time.
Post-entry movement is reported separately as an outcome, never used as a
pre-entry feature. No optimization, filtering, or strategy promotion.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

try:
    from .stage43 import (
        run_breakout_backtest, _stamp, aggregate_complete_5m, atr_values,
    )
    from .stage44 import build_stage44_signals
    from .stage55 import audit_bar_integrity
    from .stage57 import build_stage57_candidate_signals
except ImportError:
    from stage43 import run_breakout_backtest, _stamp, aggregate_complete_5m, atr_values
    from stage44 import build_stage44_signals
    from stage55 import audit_bar_integrity
    from stage57 import build_stage57_candidate_signals


def _pf(values: list[float]):
    wins = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    return round(wins / losses, 4) if losses else ("infinite" if wins else None)


def _build_entry_features(bars: list[dict], atr_base: list[float | None],
                          lookback: int = 20, pullback_bars: int = 4,
                          pullback_atr: float = 0.25) -> list[dict | None]:
    """Reconstruct Stage 4.4 pullback confirmation and causal setup features."""
    m15 = aggregate_complete_5m(bars, 15)
    atr15 = atr_values(m15, 14)
    by_bucket = {x["bucket"]: i for i, x in enumerate(m15)}
    pending: list[dict] = []
    features: list[dict | None] = [None] * len(bars)

    for i, bar in enumerate(bars):
        close_ts = int(_stamp(bar).timestamp()) + 300
        if close_ts % 900:
            continue
        bucket = close_ts // 900 - 1
        p = by_bucket.get(bucket)
        if p is None or p < max(lookback, 14) or atr15[p] is None or atr15[p] <= 0:
            continue
        cur = m15[p]
        prior = m15[p-lookback:p]
        level = max(float(x["h"]) for x in prior)
        atr = float(atr15[p])
        vol_median = median(float(x["v"]) for x in prior)
        breakout_ratio = float(cur["v"]) / vol_median if vol_median > 0 else None
        breakout = float(cur["c"]) > level

        survivors = []
        confirmed = None
        for setup in pending:
            if p > setup["expires"]:
                continue
            touched = float(cur["l"]) <= setup["level"] + pullback_atr * setup["atr"]
            reclaimed = float(cur["c"]) >= setup["level"]
            if p > setup["origin"] and touched and reclaimed:
                confirmed = setup
                continue
            survivors.append(setup)
        pending = survivors

        if confirmed is not None:
            signal_atr = float(atr_base[i]) if atr_base[i] and atr_base[i] > 0 else atr
            original = confirmed["bar"]
            entry_close = float(cur["c"])
            entry_open = float(cur["o"])
            features[i] = {
                "breakout_level": round(float(confirmed["level"]), 8),
                "breakout_age_15m_bars": int(p-confirmed["origin"]),
                "breakout_displacement_atr": round((float(original["c"])-float(confirmed["level"])) / float(confirmed["atr"]), 6),
                "breakout_volume_ratio": round(float(confirmed["volume_ratio"]), 6) if confirmed["volume_ratio"] is not None else None,
                "pullback_reclaim_distance_atr": round((entry_close-float(confirmed["level"])) / signal_atr, 6),
                "entry_candle_body_atr": round((entry_close-entry_open) / signal_atr, 6),
                "entry_volume_ratio": round(float(cur["v"])/vol_median, 6) if vol_median > 0 else None,
                "signal_close": round(entry_close, 8),
                "signal_atr": round(signal_atr, 8),
            }

        if breakout and breakout_ratio is not None:
            pending.append({
                "level": level, "atr": atr, "origin": p,
                "expires": p + pullback_bars,
                "volume_ratio": breakout_ratio, "bar": cur,
            })
    return features


def _analyse_entry_quality(trades: list[dict], bars: list[dict],
                           features: list[dict | None]) -> dict:
    idx = {x.get("t"): i for i, x in enumerate(bars)}
    rows = []
    regime: dict[str, list[dict]] = defaultdict(list)
    false_breakout = 0
    post_entry_adverse = 0
    for trade in trades:
        entry_i = idx.get(trade.get("entry_time"))
        if entry_i is None:
            continue
        signal_i = entry_i - 1
        feature = features[signal_i] if 0 <= signal_i < len(features) else None
        if feature is None:
            feature = {}
        entry = float(trade["entry_price"])
        level = feature.get("breakout_level")
        atr = feature.get("signal_atr")
        horizons = {}
        for n in (1, 3, 6, 12):
            future = bars[entry_i:entry_i+n]
            if len(future) == n:
                last_close = float(future[-1]["c"])
                horizons[str(n)] = {
                    "close_change_atr": round((last_close-entry)/atr, 6) if atr else None,
                    "closed_below_breakout_level": bool(level is not None and last_close < float(level)),
                    "min_low_change_atr": round((min(float(x["l"]) for x in future)-entry)/atr, 6) if atr else None,
                }
            else:
                horizons[str(n)] = None
        failed = any(v and v["closed_below_breakout_level"] for v in (horizons["3"], horizons["6"]))
        if failed:
            false_breakout += 1
        if horizons["3"] and horizons["3"]["close_change_atr"] is not None and horizons["3"]["close_change_atr"] < 0:
            post_entry_adverse += 1
        item = {
            "entry_time": trade.get("entry_time"),
            "exit_reason": trade.get("exit_reason"),
            "net_pnl_usd": float(trade.get("net_pnl_usd") or 0),
            "gross_pnl_usd": float(trade.get("gross_pnl_usd") or 0),
            "entry_price": entry,
            **feature,
            "post_entry_outcome": horizons,
            "false_breakout_within_3_or_6_bars": bool(failed),
        }
        if feature.get("breakout_volume_ratio") is None:
            group = "FEATURE_UNAVAILABLE"
        elif feature["breakout_volume_ratio"] < 1.5:
            group = "BREAKOUT_VOLUME_BELOW_1_5"
        elif feature.get("breakout_displacement_atr", 0) < 0.15:
            group = "WEAK_BREAKOUT_DISPLACEMENT"
        elif feature.get("pullback_reclaim_distance_atr", 0) > 0.5:
            group = "LATE_RECLAIM_DISTANCE"
        else:
            group = "STANDARD_SETUP"
        item["entry_quality_group"] = group
        regime[group].append(item)
        rows.append(item)

    def summarize(items):
        pnl = [x["net_pnl_usd"] for x in items]
        return {
            "trades": len(items),
            "stop_loss_trades": sum(str(x["exit_reason"]).startswith("STOP_LOSS") for x in items),
            "false_breakout_count": sum(x["false_breakout_within_3_or_6_bars"] for x in items),
            "net_pnl_usd": round(sum(pnl), 4),
            "win_rate_percent": round(sum(x > 0 for x in pnl)/len(pnl)*100, 2) if pnl else 0,
            "net_profit_factor": _pf(pnl),
        }
    return {
        "summary": {
            **summarize(rows),
            "feature_unavailable_trades": sum(x["entry_quality_group"] == "FEATURE_UNAVAILABLE" for x in rows),
            "false_breakout_share_percent": round(false_breakout/len(rows)*100, 2) if rows else 0,
            "negative_3bar_close_change_trades": post_entry_adverse,
        },
        "entry_quality_attribution": {k: summarize(v) for k, v in sorted(regime.items())},
        "trade_ledger": rows[-50:],
    }


def run_stage512_entry_quality_diagnostics(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.12")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.12", "status": "DATA_INTEGRITY_FAILED",
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
        baseline["atr_by_base"], starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    candidate_features = _build_entry_features(train, candidate["atr_by_base"])
    baseline_features = _build_entry_features(train, baseline["atr_by_base"])
    c_report = _analyse_entry_quality(candidate_bt["trades"], train, candidate_features)
    b_report = _analyse_entry_quality(baseline_bt["trades"], train, baseline_features)

    cs = c_report["summary"]
    findings = [
        "Breakout level, breakout displacement and volume are reconstructed from completed pre-entry 15-minute bars only.",
        "Post-entry close and low movement are outcome diagnostics; they are not used to create or filter historical entries.",
        "False-breakout label means a completed 5-minute close fell below the prior breakout level within three or six bars; it is descriptive, not causal.",
        "Fixed Stage 5.7 candidate and Stage 4.4 baseline remain unchanged; no entry filter or parameter is tested or promoted.",
    ]
    if cs["false_breakout_share_percent"] > 0:
        findings.insert(0, "Some candidate trades closed below the recorded breakout level shortly after entry; inspect the ledger and group counts before designing a separate hypothesis test.")
    return {
        "stage": "5.12",
        "status": "TRAINING_ENTRY_QUALITY_DIAGNOSTIC_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train[0].get("t"), "to": train[-1].get("t")},
        "candidate": {
            "name": "Frozen Stage 5.7 hourly trend-gated Stage 4.4 pullback + relative volume",
            "metrics": candidate_bt["metrics"], "diagnostics": c_report,
        },
        "baseline": {
            "name": "Frozen Stage 4.4 pullback + relative volume",
            "metrics": baseline_bt["metrics"], "diagnostics": b_report,
        },
        "findings": findings,
        "holdout": {"status": "SEALED_NOT_ACCESSED"},
        "limitations": [
            "Feature reconstruction follows the frozen Stage 4.4 breakout/pullback setup and may be unavailable for trades without a matching setup record.",
            "False-breakout windows are right-censored near the end of training history and marked unavailable.",
            "This is a long-only OHLC simulation; it cannot prove intrabar order or causal stop-out reasons.",
            "Fees and slippage remain assumptions, not verified broker fills.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
