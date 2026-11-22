"""Stage 5.5: historical BTC bar integrity and simulated cost reconciliation.

Read-only research. No parameter search, account access, or order routing.
"""
from __future__ import annotations

import math
from datetime import timedelta

try:
    from .stage43 import run_breakout_backtest, _stamp
    from .stage44 import build_stage44_signals
except ImportError:
    from stage43 import run_breakout_backtest, _stamp
    from stage44 import build_stage44_signals


def audit_bar_integrity(bars: list[dict]) -> dict:
    timestamps = []
    malformed_timestamps = 0
    invalid_ohlc = 0
    invalid_volume = 0
    non_finite = 0
    for bar in bars:
        try:
            stamp = _stamp(bar)
            timestamps.append(int(stamp.timestamp()))
        except (KeyError, TypeError, ValueError, OverflowError):
            malformed_timestamps += 1
            continue
        try:
            o, h, l, c = (float(bar[k]) for k in ("o", "h", "l", "c"))
            v = float(bar.get("v", 0) or 0)
            if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                non_finite += 1
            elif min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or l > h:
                invalid_ohlc += 1
            if not math.isfinite(v) or v < 0:
                invalid_volume += 1
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_ohlc += 1

    duplicate_timestamps = len(timestamps) - len(set(timestamps))
    out_of_order_pairs = sum(1 for a, b in zip(timestamps, timestamps[1:]) if b <= a)
    sorted_times = sorted(set(timestamps))
    gaps = [b - a for a, b in zip(sorted_times, sorted_times[1:]) if b - a > 300]
    missing_intervals = sum(max(0, (gap // 300) - 1) for gap in gaps)
    expected_intervals = (
        ((sorted_times[-1] - sorted_times[0]) // 300 + 1) if len(sorted_times) >= 2 else len(sorted_times)
    )
    coverage = (len(sorted_times) / expected_intervals * 100) if expected_intervals else 0.0
    checks = {
        "timestamps_parse": malformed_timestamps == 0,
        "timestamps_unique": duplicate_timestamps == 0,
        "timestamps_chronological": out_of_order_pairs == 0,
        "ohlc_valid": invalid_ohlc == 0 and non_finite == 0,
        "volume_nonnegative": invalid_volume == 0,
    }
    return {
        "bars_received": len(bars),
        "unique_timestamp_count": len(set(timestamps)),
        "malformed_timestamps": malformed_timestamps,
        "duplicate_timestamps": duplicate_timestamps,
        "out_of_order_pairs": out_of_order_pairs,
        "invalid_ohlc_bars": invalid_ohlc,
        "non_finite_bars": non_finite,
        "invalid_volume_bars": invalid_volume,
        "observed_gap_count": len(gaps),
        "estimated_missing_5m_intervals": missing_intervals,
        "largest_gap_minutes": max(gaps) / 60 if gaps else 0,
        "observed_5m_coverage_percent": round(coverage, 4),
        "first_timestamp": bars[0].get("t") if bars else None,
        "last_timestamp": bars[-1].get("t") if bars else None,
        "checks": checks,
        "structural_integrity_passed": all(checks.values()),
        "coverage_is_descriptive": True,
    }


def reconcile_trade_costs(trades: list[dict], metrics: dict) -> dict:
    gross = sum(float(t.get("gross_pnl_usd") or 0) for t in trades)
    fees = sum(float(t.get("estimated_fees_usd") or 0) for t in trades)
    slippage = sum(float(t.get("estimated_slippage_usd") or 0) for t in trades)
    net = sum(float(t.get("net_pnl_usd") or 0) for t in trades)
    trade_mismatches = []
    for index, trade in enumerate(trades):
        expected = float(trade.get("gross_pnl_usd") or 0) - float(trade.get("estimated_fees_usd") or 0)
        actual = float(trade.get("net_pnl_usd") or 0)
        if abs(expected - actual) > 0.011:
            trade_mismatches.append(index)
    metric_checks = {
        "gross_pnl_matches": abs(gross - float(metrics.get("gross_pnl_usd") or 0)) <= 0.011,
        "net_pnl_matches": abs(net - float(metrics.get("net_pnl_usd") or 0)) <= 0.011,
        "fees_match": abs(fees - float(metrics.get("estimated_fees_usd") or 0)) <= 0.011,
        "slippage_matches": abs(slippage - float(metrics.get("estimated_slippage_usd") or 0)) <= 0.011,
    }
    # Slippage is already embedded in executed entry/exit prices and therefore
    # in gross P&L. Subtracting it again would double-count transaction costs.
    return {
        "trades": len(trades),
        "gross_pnl_usd": round(gross, 4),
        "estimated_fees_usd": round(fees, 4),
        "estimated_slippage_usd": round(slippage, 4),
        "net_pnl_usd": round(net, 4),
        "net_equals_gross_minus_fees": abs((gross - fees) - net) <= 0.011,
        "slippage_treatment": "Included in executed entry/exit prices and gross P&L; do not subtract again.",
        "trade_level_mismatch_indices": trade_mismatches,
        "metric_checks": metric_checks,
        "reconciliation_passed": not trade_mismatches and all(metric_checks.values()) and abs((gross-fees)-net) <= 0.011,
    }


def run_stage55_report(
    bars: list[dict], requested_bars: int, has_more_data: bool,
    data_pages_fetched: int, starting_equity: float = 100.0,
    notional_usd: float = 10.0, fee_rate: float = 0.0025,
    slippage_bps: float = 5.0, train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.5")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0:
        raise ValueError("Invalid capital or transaction cost settings")

    data_audit = audit_bar_integrity(bars)
    # Backtest only structurally valid, chronologically ordered input. The
    # endpoint reports a failed audit instead of silently sorting/repairing it.
    if not data_audit["structural_integrity_passed"]:
        return {
            "stage": "5.5", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": data_audit, "cost_reconciliation": None,
            "order_submitted": False, "alpaca_write_api_called": False,
            "automated_execution": False,
        }

    built = build_stage44_signals(bars, lookback=20, relative_volume_threshold=1.5,
                                  pullback_atr=0.25, pullback_bars=4)
    mask = built["signals"]["breakout_pullback_relvol"]
    atrs = built["atr_by_base"]
    split = int(len(bars) * train_fraction)
    first_holdout_fill = bars[split + 1].get("t")
    train = run_breakout_backtest(
        bars[:split], mask[:split], atrs[:split], starting_equity,
        notional_usd, fee_rate, slippage_bps,
    )
    holdout = run_breakout_backtest(
        bars, mask, atrs, starting_equity, notional_usd,
        fee_rate, slippage_bps, start_index=split,
    )
    train_recon = reconcile_trade_costs(train["trades"], train["metrics"])
    hold_recon = reconcile_trade_costs(holdout["trades"], holdout["metrics"])
    boundary_ok = all(
        t.get("entry_time") and t["entry_time"] >= first_holdout_fill
        for t in holdout["trades"]
    )
    integrity_ok = data_audit["structural_integrity_passed"]
    cost_ok = train_recon["reconciliation_passed"] and hold_recon["reconciliation_passed"]
    sufficient_history = len(bars) == requested_bars
    status = "AUDIT_PASS_RESEARCH_ONLY" if integrity_ok and cost_ok and boundary_ok else "AUDIT_REVIEW_REQUIRED"
    return {
        "stage": "5.5", "status": status,
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_used": len(bars), "requested_bars": requested_bars,
        "history_complete_for_request": sufficient_history,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages_fetched,
        "period": {"from": bars[0].get("t"), "to": bars[-1].get("t")},
        "data_audit": data_audit,
        "cost_assumptions": {
            "starting_equity_usd": starting_equity,
            "fixed_notional_usd": notional_usd,
            "fee_per_side_percent": fee_rate * 100,
            "slippage_bps_per_side": slippage_bps,
            "strategy": "Frozen Stage 4.4 breakout_pullback_relvol; no optimization.",
        },
        "training": {
            "bars": split, "metrics": train["metrics"],
            "cost_reconciliation": train_recon,
            "trade_ledger": train["trades"][-20:],
        },
        "holdout": {
            "bars": len(bars) - split, "metrics": holdout["metrics"],
            "entries_after_split": boundary_ok,
            "cost_reconciliation": hold_recon,
            "trade_ledger": holdout["trades"][-20:],
        },
        "audit_gates": {
            "data_integrity": integrity_ok,
            "cost_reconciliation": cost_ok,
            "holdout_boundary": boundary_ok,
            "history_complete_for_request": sufficient_history,
            "all_audit_gates_passed": integrity_ok and cost_ok and boundary_ok and sufficient_history,
        },
        "limitations": [
            "An audit pass validates input structure and arithmetic reconciliation only; it does not establish profitability.",
            "A full requested history window may still be too short or unrepresentative for strategy validation.",
            "Estimated fees and slippage are assumptions, not actual broker fills.",
            "Slippage is embedded in simulated execution prices and gross P&L; it is reported separately and not deducted twice.",
            "OHLC data cannot reconstruct the true intrabar price path or liquidity.",
            "No account, position, order, or execution endpoint is called.",
        ],
        "market_data_api_read": True,
        "broker_api_called": False,
        "alpaca_write_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
