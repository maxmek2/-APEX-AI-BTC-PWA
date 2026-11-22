"""Stage 5.15: loss concentration and root-cause investigation.

Replays the frozen Stage 5.7 candidate and Stage 4.4 baseline on the
training slice only. Ranks descriptive loss contributors by entry-quality
group and exit reason. This is not causal attribution or optimization.
"""
from __future__ import annotations

from collections import defaultdict

try:
    from .stage43 import run_breakout_backtest
    from .stage44 import build_stage44_signals
    from .stage55 import audit_bar_integrity
    from .stage57 import build_stage57_candidate_signals
    from .stage512 import _build_entry_features
except ImportError:
    from stage43 import run_breakout_backtest
    from stage44 import build_stage44_signals
    from stage55 import audit_bar_integrity
    from stage57 import build_stage57_candidate_signals
    from stage512 import _build_entry_features


def _profit_factor(values):
    gains = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    return round(gains / losses, 4) if losses else ("infinite" if gains else None)


def _group_for(feature):
    if feature.get("breakout_volume_ratio") is None:
        return "FEATURE_UNAVAILABLE"
    if feature["breakout_volume_ratio"] < 1.5:
        return "BREAKOUT_VOLUME_BELOW_1_5"
    if feature.get("breakout_displacement_atr", 0) < 0.15:
        return "WEAK_BREAKOUT_DISPLACEMENT"
    if feature.get("pullback_reclaim_distance_atr", 0) > 0.5:
        return "LATE_RECLAIM_DISTANCE"
    return "STANDARD_SETUP"


def _summarize(items):
    net = [float(x.get("net_pnl_usd") or 0) for x in items]
    gross = [float(x.get("gross_pnl_usd") or 0) for x in items]
    fees = [float(x.get("estimated_fees_usd") or 0) for x in items]
    gross_loss = -sum(x for x in gross if x < 0)
    net_loss = -sum(x for x in net if x < 0)
    return {
        "trades": len(items),
        "stop_loss_trades": sum(str(x.get("exit_reason", "")).startswith("STOP_LOSS") for x in items),
        "take_profit_trades": sum(str(x.get("exit_reason", "")).startswith("TAKE_PROFIT") for x in items),
        "gross_pnl_usd": round(sum(gross), 4),
        "fees_usd": round(sum(fees), 4),
        "net_pnl_usd": round(sum(net), 4),
        "gross_loss_usd": round(gross_loss, 4),
        "net_loss_usd": round(net_loss, 4),
        "losing_trades": sum(x < 0 for x in net),
        "winners_erased_by_fees": sum(float(x.get("gross_pnl_usd") or 0) > 0 and float(x.get("net_pnl_usd") or 0) <= 0 for x in items),
        "win_rate_percent": round(sum(x > 0 for x in net) / len(net) * 100, 2) if net else 0,
        "net_profit_factor": _profit_factor(net),
        "average_net_per_trade_usd": round(sum(net) / len(net), 5) if net else 0,
    }


def _investigate(trades, bars, features):
    index = {x.get("t"): i for i, x in enumerate(bars)}
    by_quality = defaultdict(list)
    by_exit = defaultdict(list)
    by_quality_exit = defaultdict(list)
    ledger = []
    for trade in trades:
        entry_i = index.get(trade.get("entry_time"))
        signal_i = entry_i - 1 if entry_i is not None else None
        feature = features[signal_i] if signal_i is not None and 0 <= signal_i < len(features) else None
        feature = feature or {}
        quality = _group_for(feature)
        exit_reason = str(trade.get("exit_reason") or "UNKNOWN")
        item = {**trade, "entry_quality_group": quality}
        by_quality[quality].append(item)
        by_exit[exit_reason].append(item)
        by_quality_exit[(quality, exit_reason)].append(item)
        ledger.append({
            "entry_time": trade.get("entry_time"),
            "exit_time": trade.get("exit_time"),
            "exit_reason": exit_reason,
            "entry_quality_group": quality,
            "gross_pnl_usd": float(trade.get("gross_pnl_usd") or 0),
            "fees_usd": float(trade.get("estimated_fees_usd") or 0),
            "net_pnl_usd": float(trade.get("net_pnl_usd") or 0),
            "breakout_volume_ratio": feature.get("breakout_volume_ratio"),
            "breakout_displacement_atr": feature.get("breakout_displacement_atr"),
            "pullback_reclaim_distance_atr": feature.get("pullback_reclaim_distance_atr"),
        })

    quality_rows = []
    for key, items in sorted(by_quality.items()):
        quality_rows.append({"group": key, **_summarize(items)})
    exit_rows = []
    for key, items in sorted(by_exit.items()):
        exit_rows.append({"group": key, **_summarize(items)})
    matrix = []
    for (quality, reason), items in sorted(by_quality_exit.items()):
        matrix.append({"entry_quality_group": quality, "exit_reason": reason, **_summarize(items)})

    negative_quality = sorted(
        [x for x in quality_rows if x["net_pnl_usd"] < 0],
        key=lambda x: x["net_pnl_usd"],
    )
    total_net_loss = -sum(float(x["net_pnl_usd"]) for x in quality_rows if x["net_pnl_usd"] < 0)
    for row in negative_quality:
        row["share_of_negative_group_net_pnl_percent"] = (
            round((-row["net_pnl_usd"]) / total_net_loss * 100, 2) if total_net_loss else 0
        )
    total_gross_loss = sum(float(x["gross_loss_usd"]) for x in quality_rows)
    total_fees = sum(float(x["fees_usd"]) for x in quality_rows)
    summary = _summarize(trades)
    summary.update({
        "entry_quality_groups": len(quality_rows),
        "negative_net_quality_groups": len(negative_quality),
        "gross_loss_concentration_top_group_percent": (
            round(max((x["gross_loss_usd"] for x in quality_rows), default=0) / total_gross_loss * 100, 2)
            if total_gross_loss else 0
        ),
        "fees_as_percent_of_gross_losses": round(total_fees / total_gross_loss * 100, 2) if total_gross_loss else None,
    })
    findings = []
    if summary["stop_loss_trades"] > 0:
        findings.append(
            f"{summary['stop_loss_trades']} of {summary['trades']} trades exited by stop loss; this is an exit concentration, not proof of stop-distance causation."
        )
    if negative_quality:
        top = negative_quality[0]
        findings.append(
            f"{top['group']} is the largest negative net-P&L entry-quality group in this training sample ({top['net_pnl_usd']:.4f} USD across {top['trades']} trades)."
        )
    if summary["winners_erased_by_fees"]:
        findings.append(
            f"Estimated fees erased {summary['winners_erased_by_fees']} gross-positive trades; fee assumptions are not broker-verified."
        )
    if not findings:
        findings.append("No dominant loss concentration was identified in the available training sample.")
    findings.extend([
        "Group shares are descriptive accounting allocations; overlapping market conditions and small samples prevent causal conclusions.",
        "Entry-quality groups are reconstructed from completed pre-entry 15-minute bars and do not change historical entries.",
        "No stop, target, entry rule, sizing, parameter or strategy is changed or selected by this stage.",
    ])
    return {
        "summary": summary,
        "entry_quality_attribution": quality_rows,
        "exit_reason_attribution": exit_rows,
        "entry_quality_by_exit_reason": matrix,
        "largest_negative_groups": negative_quality[:3],
        "latest_trade_ledger": ledger[-50:],
        "findings": findings,
    }


def run_stage515_loss_concentration_investigation(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.15")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.15", "status": "DATA_INTEGRITY_FAILED",
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
    c_bt = run_breakout_backtest(
        train, candidate["signals"], candidate["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    b_bt = run_breakout_backtest(
        train, baseline["signals"]["breakout_pullback_relvol"],
        baseline["atr_by_base"], starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    c_features = _build_entry_features(train, candidate["atr_by_base"])
    b_features = _build_entry_features(train, baseline["atr_by_base"])
    c_report = _investigate(c_bt["trades"], train, c_features)
    b_report = _investigate(b_bt["trades"], train, b_features)
    return {
        "stage": "5.15",
        "status": "TRAINING_LOSS_CONCENTRATION_INVESTIGATION_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train[0].get("t"), "to": train[-1].get("t")},
        "cost_assumptions": {
            "starting_equity_usd": starting_equity,
            "notional_usd": notional_usd,
            "fee_rate": fee_rate,
            "slippage_bps": slippage_bps,
        },
        "candidate": {
            "name": "Frozen Stage 5.7 hourly trend-gated Stage 4.4 pullback + relative volume",
            "backtest_metrics": c_bt["metrics"],
            "investigation": c_report,
        },
        "baseline": {
            "name": "Frozen Stage 4.4 pullback + relative volume",
            "backtest_metrics": b_bt["metrics"],
            "investigation": b_report,
        },
        "findings": c_report["findings"],
        "holdout": {"status": "SEALED_NOT_ACCESSED"},
        "limitations": [
            "This stage ranks descriptive accounting concentrations, not causal root causes.",
            "Small or sparse groups can be unstable; no statistical significance is claimed.",
            "Fees and slippage are modelling assumptions, not verified broker fills.",
            "The frozen long-only OHLC simulator cannot establish intrabar liquidity or actual execution quality.",
            "No optimization, strategy promotion, broker API calls, order submission or automated execution occurs.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
