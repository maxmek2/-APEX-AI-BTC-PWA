"""Stage 5.8: training-only entry, exit, session and realized-risk diagnostics.

Diagnoses the frozen Stage 5.7 hourly-trend-gated candidate. It does not tune,
select, promote, or evaluate holdout outcomes. All labels are descriptive.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

try:
    from .stage43 import _stamp, run_breakout_backtest
    from .stage44 import build_stage44_signals
    from .stage54 import build_market_regimes
    from .stage55 import audit_bar_integrity
    from .stage57 import build_stage57_candidate_signals
except ImportError:
    from stage43 import _stamp, run_breakout_backtest
    from stage44 import build_stage44_signals
    from stage54 import build_market_regimes
    from stage55 import audit_bar_integrity
    from stage57 import build_stage57_candidate_signals


def _parse_time(value: str) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _session(value: str) -> str:
    hour = _parse_time(value).astimezone(timezone.utc).hour
    if 0 <= hour < 7:
        return "ASIA_00_07_UTC"
    if 7 <= hour < 13:
        return "EUROPE_07_13_UTC"
    if 13 <= hour < 21:
        return "US_13_21_UTC"
    return "LATE_21_24_UTC"


def _profit_factor(values: list[float]):
    profits = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    return round(profits / losses, 4) if losses else ("infinite" if profits else None)


def _summary(trades: list[dict]) -> dict:
    net = [float(t.get("net_pnl_usd") or 0) for t in trades]
    gross = [float(t.get("gross_pnl_usd") or 0) for t in trades]
    fees = sum(float(t.get("estimated_fees_usd") or 0) for t in trades)
    slip = sum(float(t.get("estimated_slippage_usd") or 0) for t in trades)
    wins = sum(x > 0 for x in net)
    return {
        "trades": len(trades),
        "wins": wins,
        "losses": sum(x < 0 for x in net),
        "win_rate_percent": round(wins / len(trades) * 100, 2) if trades else 0.0,
        "gross_pnl_usd": round(sum(gross), 4),
        "fees_usd": round(fees, 4),
        "estimated_slippage_usd": round(slip, 4),
        "net_pnl_usd": round(sum(net), 4),
        "net_profit_factor": _profit_factor(net),
        "average_net_per_trade_usd": round(sum(net) / len(net), 4) if net else 0.0,
    }


def _group(trades: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for trade in trades:
        groups.setdefault(str(trade.get(key) or "UNAVAILABLE"), []).append(trade)
    return {name: _summary(items) for name, items in sorted(groups.items())}


def _longest_losing_streak(trades: list[dict]) -> int:
    longest = current = 0
    for trade in trades:
        if float(trade.get("net_pnl_usd") or 0) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _duration_minutes(trade: dict) -> float | None:
    try:
        return max(0.0, (_parse_time(trade["exit_time"]) - _parse_time(trade["entry_time"])).total_seconds() / 60)
    except (KeyError, TypeError, ValueError):
        return None


def _failure_findings(trades: list[dict], metrics: dict, sessions: dict, reasons: dict) -> list[str]:
    findings = []
    if not trades:
        return ["No closed candidate trades were available for training attribution."]
    stop_count = sum(v["trades"] for k, v in reasons.items() if "STOP_LOSS" in k)
    stop_share = stop_count / len(trades)
    if stop_share >= 0.5:
        findings.append(f"Stop-loss exits account for {stop_share * 100:.1f}% of closed trades; this identifies a dominant exit outcome, not its cause.")
    if float(metrics.get("gross_pnl_usd") or 0) <= 0:
        findings.append("Candidate gross P&L is non-positive before fees; entry/exit edge needs review before cost changes can help.")
    if float(metrics.get("net_pnl_usd") or 0) < float(metrics.get("gross_pnl_usd") or 0):
        findings.append("Estimated fees reduce P&L further; slippage is already embedded in executed prices and is not subtracted twice.")
    losing_sessions = [k for k, v in sessions.items() if v["trades"] >= 5 and v["net_pnl_usd"] < 0]
    if losing_sessions:
        findings.append("Negative net results appear in sessions with at least five trades: " + ", ".join(losing_sessions) + ". Treat these as descriptive samples, not session effects.")
    if _longest_losing_streak(trades) >= 5:
        findings.append("A losing streak of at least five trades occurred; sequence risk remains material.")
    if not findings:
        findings.append("No single dominant failure signature was established; keep the candidate unvalidated.")
    return findings


def run_stage58_execution_diagnostics(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.8")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.8", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": audit, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    train_bars = bars[:split]
    built = build_stage57_candidate_signals(train_bars)
    candidate_result = run_breakout_backtest(
        train_bars, built["signals"], built["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    baseline = build_stage44_signals(
        train_bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    baseline_result = run_breakout_backtest(
        train_bars, baseline["signals"]["breakout_pullback_relvol"],
        baseline["atr_by_base"], starting_equity, notional_usd,
        fee_rate, slippage_bps,
    )

    regimes = build_market_regimes(train_bars)["regime_by_base"]
    time_to_index = {bar.get("t"): i for i, bar in enumerate(train_bars)}
    durations = []
    enriched = []
    gap_values = []
    realized_r = []
    duration_groups = {"0_15_MIN": [], "15_60_MIN": [], "60_240_MIN": [], "OVER_240_MIN": []}
    reason_groups: dict[str, list[dict]] = {}
    session_groups: dict[str, list[dict]] = {}
    regime_groups: dict[str, list[dict]] = {}
    gap_groups: dict[str, list[dict]] = {}

    for trade in candidate_result["trades"]:
        entry_index = time_to_index.get(trade.get("entry_time"))
        if entry_index is None or entry_index <= 0:
            signal_index = None
        else:
            signal_index = entry_index - 1

        atr = built["atr_by_base"][signal_index] if signal_index is not None else None
        risk_distance = float(atr) * 1.5 if atr is not None and float(atr) > 0 else None
        entry_price = float(trade.get("entry_price") or 0)
        exit_price = float(trade.get("exit_price") or 0)
        risk_usd = (notional_usd / entry_price * risk_distance) if risk_distance and entry_price > 0 else None
        r_multiple = (float(trade.get("net_pnl_usd") or 0) / risk_usd) if risk_usd and risk_usd > 0 else None
        if r_multiple is not None:
            realized_r.append(r_multiple)

        duration = _duration_minutes(trade)
        if duration is not None:
            durations.append(duration)
            bucket = "0_15_MIN" if duration < 15 else "15_60_MIN" if duration < 60 else "60_240_MIN" if duration < 240 else "OVER_240_MIN"
        else:
            bucket = "UNAVAILABLE"
        enriched_trade = {
            **trade,
            "entry_session_utc": _session(trade["entry_time"]),
            "entry_regime": regimes[signal_index] if signal_index is not None else "REGIME_UNAVAILABLE",
            "holding_minutes": round(duration, 2) if duration is not None else None,
            "holding_bucket": bucket,
            "risk_distance_usd_per_btc": round(risk_distance, 6) if risk_distance is not None else None,
            "estimated_initial_risk_usd": round(risk_usd, 6) if risk_usd is not None else None,
            "realized_net_r_multiple": round(r_multiple, 4) if r_multiple is not None else None,
        }

        # Next-bar open gap versus signal-bar close, normalized by ATR.
        if signal_index is not None and atr and float(atr) > 0:
            signal_close = float(train_bars[signal_index]["c"])
            next_open = float(train_bars[entry_index]["o"])
            gap_atr = (next_open - signal_close) / float(atr)
            gap_values.append(gap_atr)
            gap_label = "ADVERSE_GAP_UP" if gap_atr > 0.10 else "FAVORABLE_GAP_DOWN" if gap_atr < -0.10 else "SMALL_GAP"
        else:
            gap_atr = None
            gap_label = "UNAVAILABLE"
        enriched_trade["entry_gap_atr"] = round(gap_atr, 4) if gap_atr is not None else None
        enriched_trade["entry_gap_class"] = gap_label

        enriched.append(enriched_trade)
        reason_groups.setdefault(str(trade.get("exit_reason") or "UNKNOWN"), []).append(enriched_trade)
        session_groups.setdefault(enriched_trade["entry_session_utc"], []).append(enriched_trade)
        regime_groups.setdefault(enriched_trade["entry_regime"], []).append(enriched_trade)
        gap_groups.setdefault(gap_label, []).append(enriched_trade)
        duration_groups.setdefault(bucket, []).append(enriched_trade)

    metrics = candidate_result["metrics"]
    reasons = {k: _summary(v) for k, v in sorted(reason_groups.items())}
    sessions = {k: _summary(v) for k, v in sorted(session_groups.items())}
    regimes_summary = {k: _summary(v) for k, v in sorted(regime_groups.items())}
    gaps = {k: _summary(v) for k, v in sorted(gap_groups.items())}
    durations_summary = {k: _summary(v) for k, v in sorted(duration_groups.items()) if v}
    all_r = sorted(realized_r)
    findings = _failure_findings(enriched, metrics, sessions, reasons)

    return {
        "stage": "5.8",
        "status": "TRAINING_EXECUTION_DIAGNOSTIC_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train_bars[0].get("t"), "to": train_bars[-1].get("t")},
        "candidate": {
            "name": "Stage 5.7 fixed hourly trend-gated Stage 4.4 pullback + relative volume",
            "parameters_frozen": True, "parameter_search": False,
            "baseline_training_metrics": baseline_result["metrics"],
            "candidate_training_metrics": metrics,
        },
        "training": {
            "metrics": metrics,
            "exit_reason_attribution": reasons,
            "entry_session_attribution_utc": sessions,
            "entry_regime_attribution": regimes_summary,
            "holding_duration_attribution": durations_summary,
            "entry_gap_attribution": gaps,
            "risk_diagnostics": {
                "realized_net_r_median": round(median(realized_r), 4) if realized_r else None,
                "realized_net_r_min": round(min(realized_r), 4) if realized_r else None,
                "realized_net_r_max": round(max(realized_r), 4) if realized_r else None,
                "trades_with_r_multiple": len(realized_r),
                "average_holding_minutes": round(sum(durations) / len(durations), 2) if durations else None,
                "median_holding_minutes": round(median(durations), 2) if durations else None,
                "longest_losing_streak": _longest_losing_streak(enriched),
                "stop_loss_share_percent": round(sum(v["trades"] for k, v in reasons.items() if "STOP_LOSS" in k) / len(enriched) * 100, 2) if enriched else 0,
                "average_entry_gap_atr": round(sum(gap_values) / len(gap_values), 4) if gap_values else None,
            },
            "findings": findings,
            "trade_ledger": enriched[-50:],
        },
        "holdout": {
            "status": "SEALED_NOT_ACCESSED",
            "reason": "Stage 5.8 computes candidate signals, trades, sessions and attribution on the chronological training slice only.",
        },
        "limitations": [
            "Session and regime groups are descriptive; small samples are not reliable evidence of a session or regime effect.",
            "Realized R uses the configured 1.5 ATR initial stop distance and estimated notional; it is a model-derived risk multiple, not account risk or broker fill data.",
            "Next-bar opening gap is measured against the signal-bar close; positive gaps are adverse for a long entry.",
            "Fees and slippage are assumptions; slippage is embedded in executed prices and is not subtracted twice.",
            "OHLC simulation cannot reconstruct intrabar liquidity or exact price path; stop-first handling is conservative when stop and target are both touched.",
            "No parameter optimization, strategy promotion, broker API call, order submission, or automated execution occurs.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
