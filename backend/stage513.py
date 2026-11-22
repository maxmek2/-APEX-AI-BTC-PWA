"""Stage 5.13: temporal stability and sample adequacy audit.

Uses frozen Stage 5.7 candidate and Stage 4.4 baseline on training data only.
Reports three chronological cohorts, trade-count adequacy and loss clustering.
No parameter search, cohort-based selection, strategy changes or promotion.
"""
from __future__ import annotations

from datetime import datetime
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


def _time(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _pf(values):
    gains = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    return round(gains / losses, 4) if losses else ("infinite" if gains else None)


def _summarize(trades):
    values = [float(x.get("net_pnl_usd") or 0) for x in trades]
    streak = longest = 0
    for value in values:
        streak = streak + 1 if value < 0 else 0
        longest = max(longest, streak)
    return {
        "trades": len(values),
        "wins": sum(x > 0 for x in values),
        "losses": sum(x < 0 for x in values),
        "win_rate_percent": round(sum(x > 0 for x in values) / len(values) * 100, 2) if values else 0,
        "net_pnl_usd": round(sum(values), 4),
        "average_net_per_trade_usd": round(sum(values) / len(values), 5) if values else 0,
        "net_profit_factor": _pf(values),
        "longest_losing_streak": longest,
        "minimum_30_trade_sample_met": len(values) >= 30,
    }


def _cohorts(trades, training_bars):
    start = _time(training_bars[0].get("t"))
    end = _time(training_bars[-1].get("t"))
    if start is None or end is None:
        raise ValueError("Training bars must contain parseable UTC timestamps")
    span = (end - start).total_seconds()
    buckets = [[], [], []]
    unassigned = 0
    for trade in trades:
        stamp = _time(trade.get("entry_time"))
        if stamp is None:
            unassigned += 1
            continue
        offset = (stamp - start).total_seconds()
        index = min(2, max(0, int(offset / span * 3))) if span > 0 else 0
        buckets[index].append(trade)
    reports = []
    for i, group in enumerate(buckets):
        left = start + (end - start) * (i / 3)
        right = start + (end - start) * ((i + 1) / 3)
        reports.append({
            "cohort": f"TRAINING_THIRD_{i+1}",
            "period_from": left.isoformat(),
            "period_to": right.isoformat(),
            **_summarize(group),
        })
    populated = sum(x["trades"] > 0 for x in reports)
    positive = sum(x["net_pnl_usd"] > 0 for x in reports)
    return {
        "cohorts": reports,
        "summary": {
            "populated_cohorts": populated,
            "positive_net_cohorts": positive,
            "negative_net_cohorts": sum(x["trades"] > 0 and x["net_pnl_usd"] < 0 for x in reports),
            "unassigned_trades": unassigned,
            "all_three_cohorts_have_30_trades": all(x["trades"] >= 30 for x in reports),
            "cohort_consistency": "POSITIVE_ALL" if populated == 3 and positive == 3 else ("MIXED" if positive else "NEGATIVE_OR_NO_POSITIVE_COHORT"),
        },
    }


def run_stage513_temporal_stability_audit(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.13")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.13", "status": "DATA_INTEGRITY_FAILED",
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
    c_cohorts = _cohorts(candidate_bt["trades"], train)
    b_cohorts = _cohorts(baseline_bt["trades"], train)

    c_summary, b_summary = c_cohorts["summary"], b_cohorts["summary"]
    findings = [
        "Three cohorts are fixed chronological thirds of the training interval; no cohort is used to tune or select a strategy.",
        "A 30-trade threshold is an evidence-adequacy flag, not a profitability guarantee; sparse cohorts remain descriptive.",
        "The frozen candidate and baseline are evaluated with the same training interval and transaction-cost assumptions.",
        "Holdout bars and outcomes are not read or scored by this stage.",
    ]
    if not c_summary["all_three_cohorts_have_30_trades"]:
        findings.insert(0, "Candidate cohort sample counts are below the 30-trade adequacy threshold; temporal conclusions are low-confidence.")
    if c_summary["positive_net_cohorts"] < 3:
        findings.insert(0, "Candidate net results are not consistently positive across all training thirds; do not promote it on aggregate P&L alone.")

    return {
        "stage": "5.13",
        "status": "TRAINING_TEMPORAL_STABILITY_AUDIT_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train[0].get("t"), "to": train[-1].get("t")},
        "candidate": {
            "name": "Frozen Stage 5.7 candidate",
            "overall_metrics": candidate_bt["metrics"],
            **c_cohorts,
        },
        "baseline": {
            "name": "Frozen Stage 4.4 baseline",
            "overall_metrics": baseline_bt["metrics"],
            **b_cohorts,
        },
        "findings": findings,
        "holdout": {"status": "SEALED_NOT_ACCESSED"},
        "limitations": [
            "Chronological cohorts are in-sample diagnostics and do not replace a single untouched holdout evaluation.",
            "The 30-trade threshold is a reporting flag; fewer observations can produce unstable estimates.",
            "Fees and slippage are assumptions, not verified broker fills.",
            "No parameter optimization, strategy promotion, broker writes, order submission or automated execution is performed.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
