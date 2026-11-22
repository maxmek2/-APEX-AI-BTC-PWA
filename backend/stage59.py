"""Stage 5.9: independent trade-level accounting and execution-model audit.

Replays the frozen Stage 5.7 candidate on training data only, independently
recomputes each trade's gross P&L, fees, embedded slippage and R multiples,
then reconciles trade totals to the backtest summary. No tuning or promotion.
"""
from __future__ import annotations

from collections import Counter
from statistics import median

try:
    from .stage43 import run_breakout_backtest
    from .stage55 import audit_bar_integrity
    from .stage57 import build_stage57_candidate_signals
except ImportError:
    from stage43 import run_breakout_backtest
    from stage55 import audit_bar_integrity
    from stage57 import build_stage57_candidate_signals


def _round4(value: float) -> float:
    return round(float(value), 4)


def _pf(values: list[float]):
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    return round(gains / losses, 4) if losses else ("infinite" if gains else None)


def audit_trade_ledger(
    trades: list[dict], atr_by_base: list[float | None], bars: list[dict],
    notional_usd: float, fee_rate: float, slippage_bps: float,
    stop_atr_multiple: float = 1.5, tolerance_usd: float = 0.00025,
) -> dict:
    """Recompute accounting from recorded fills; never use reported net as input."""
    time_to_index = {bar.get("t"): i for i, bar in enumerate(bars)}
    slip = slippage_bps / 10000.0
    audited = []
    discrepancies = []
    tp_net_negative = 0
    tp_gross_nonpositive = 0
    stop_gross_nonnegative = 0
    gross_values, net_values, fee_values, slip_values = [], [], [], []

    for n, trade in enumerate(trades, start=1):
        entry = float(trade["entry_price"])
        exit_price = float(trade["exit_price"])
        if entry <= 0 or exit_price <= 0:
            discrepancies.append({"trade": n, "field": "fill_price", "detail": "Non-positive fill price"})
            continue
        qty = notional_usd / entry
        recomputed_gross = (exit_price - entry) * qty
        recomputed_fees = (entry + exit_price) * qty * fee_rate
        recomputed_net = recomputed_gross - recomputed_fees
        reference_entry = entry / (1 + slip)
        raw_exit = exit_price / (1 - slip) if slip < 1 else exit_price
        recomputed_slippage = (entry - reference_entry) * qty + (raw_exit - exit_price) * qty

        entry_index = time_to_index.get(trade.get("entry_time"))
        signal_index = entry_index - 1 if entry_index is not None and entry_index > 0 else None
        atr = atr_by_base[signal_index] if signal_index is not None else None
        initial_risk = (
            qty * float(atr) * stop_atr_multiple
            if atr is not None and float(atr) > 0 else None
        )
        gross_r = recomputed_gross / initial_risk if initial_risk else None
        net_r = recomputed_net / initial_risk if initial_risk else None

        checks = {
            "gross_pnl_usd": (recomputed_gross, float(trade.get("gross_pnl_usd") or 0)),
            "estimated_fees_usd": (recomputed_fees, float(trade.get("estimated_fees_usd") or 0)),
            "net_pnl_usd": (recomputed_net, float(trade.get("net_pnl_usd") or 0)),
            "estimated_slippage_usd": (recomputed_slippage, float(trade.get("estimated_slippage_usd") or 0)),
        }
        for field, (expected, reported) in checks.items():
            if abs(expected - reported) > tolerance_usd:
                discrepancies.append({
                    "trade": n, "field": field,
                    "recomputed": round(expected, 6), "reported": round(reported, 6),
                    "difference": round(reported - expected, 6),
                })

        reason = str(trade.get("exit_reason") or "UNKNOWN")
        if reason.startswith("TAKE_PROFIT"):
            if recomputed_net < 0:
                tp_net_negative += 1
            if recomputed_gross <= 0:
                tp_gross_nonpositive += 1
                discrepancies.append({
                    "trade": n, "field": "take_profit_gross_sign",
                    "detail": "Take-profit exit has non-positive gross P&L",
                    "gross_pnl_usd": round(recomputed_gross, 6),
                })
        if reason.startswith("STOP_LOSS") and recomputed_gross >= 0:
            stop_gross_nonnegative += 1
            discrepancies.append({
                "trade": n, "field": "stop_loss_gross_sign",
                "detail": "Stop-loss exit has non-negative gross P&L",
                "gross_pnl_usd": round(recomputed_gross, 6),
            })

        gross_values.append(recomputed_gross)
        fee_values.append(recomputed_fees)
        slip_values.append(recomputed_slippage)
        net_values.append(recomputed_net)
        audited.append({
            "entry_time": trade.get("entry_time"),
            "exit_time": trade.get("exit_time"),
            "exit_reason": reason,
            "entry_price": entry,
            "exit_price": exit_price,
            "quantity_btc": round(qty, 10),
            "reported_gross_pnl_usd": trade.get("gross_pnl_usd"),
            "recomputed_gross_pnl_usd": _round4(recomputed_gross),
            "recomputed_fees_usd": _round4(recomputed_fees),
            "reported_fees_usd": trade.get("estimated_fees_usd"),
            "recomputed_net_pnl_usd": _round4(recomputed_net),
            "reported_net_pnl_usd": trade.get("net_pnl_usd"),
            "recomputed_embedded_slippage_usd": _round4(recomputed_slippage),
            "reported_slippage_usd": trade.get("estimated_slippage_usd"),
            "initial_risk_usd": round(initial_risk, 6) if initial_risk else None,
            "gross_r_multiple": round(gross_r, 4) if gross_r is not None else None,
            "net_r_multiple": round(net_r, 4) if net_r is not None else None,
            "net_negative_after_fees": recomputed_gross > 0 and recomputed_net < 0,
        })

    summary = {
        "trades_audited": len(audited),
        "reported_trade_count": len(trades),
        "gross_pnl_recomputed_usd": _round4(sum(gross_values)),
        "fees_recomputed_usd": _round4(sum(fee_values)),
        "net_pnl_recomputed_usd": _round4(sum(net_values)),
        "embedded_slippage_recomputed_usd": _round4(sum(slip_values)),
        "gross_profit_factor": _pf(gross_values),
        "net_profit_factor": _pf(net_values),
        "take_profit_net_negative_count": tp_net_negative,
        "take_profit_gross_nonpositive_count": tp_gross_nonpositive,
        "stop_loss_gross_nonnegative_count": stop_gross_nonnegative,
        "gross_r_median": round(median([x["gross_r_multiple"] for x in audited if x["gross_r_multiple"] is not None]), 4) if any(x["gross_r_multiple"] is not None for x in audited) else None,
        "net_r_median": round(median([x["net_r_multiple"] for x in audited if x["net_r_multiple"] is not None]), 4) if any(x["net_r_multiple"] is not None for x in audited) else None,
    }
    return {
        "status": "PASS" if not discrepancies and len(audited) == len(trades) else "FAIL",
        "summary": summary,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies[:100],
        "trade_ledger": audited[-50:],
        "interpretation": (
            "Some take-profit trades can be net-negative when positive gross gains are smaller than estimated round-trip fees."
            if tp_net_negative and tp_gross_nonpositive == 0
            else "Review the trade-level discrepancies before drawing conclusions."
            if discrepancies else
            "Trade-level accounting reconciles within the configured rounding tolerance."
        ),
    }


def run_stage59_accounting_audit(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.9")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    integrity = audit_bar_integrity(bars)
    if not integrity["structural_integrity_passed"]:
        return {
            "stage": "5.9", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": integrity, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    training_bars = bars[:split]
    candidate = build_stage57_candidate_signals(training_bars)
    result = run_breakout_backtest(
        training_bars, candidate["signals"], candidate["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    audit = audit_trade_ledger(
        result["trades"], candidate["atr_by_base"], training_bars,
        notional_usd, fee_rate, slippage_bps,
    )
    metrics = result["metrics"]
    totals_match = (
        abs(audit["summary"]["gross_pnl_recomputed_usd"] - float(metrics["gross_pnl_usd"])) <= 0.01
        and abs(audit["summary"]["fees_recomputed_usd"] - float(metrics["estimated_fees_usd"])) <= 0.01
        and abs(audit["summary"]["net_pnl_recomputed_usd"] - float(metrics["net_pnl_usd"])) <= 0.01
        and abs(audit["summary"]["embedded_slippage_recomputed_usd"] - float(metrics["estimated_slippage_usd"])) <= 0.01
    )
    return {
        "stage": "5.9",
        "status": "TRAINING_ACCOUNTING_AUDIT_COMPLETE",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": training_bars[0].get("t"), "to": training_bars[-1].get("t")},
        "candidate": "Frozen Stage 5.7 hourly trend-gated Stage 4.4 baseline",
        "reported_backtest_metrics": metrics,
        "accounting_audit": audit,
        "aggregate_totals_match_backtest": totals_match,
        "holdout": {
            "status": "SEALED_NOT_ACCESSED",
            "reason": "Only the chronological training slice is used to generate trades and audit accounting.",
        },
        "limitations": [
            "This audits internal simulator arithmetic, not actual broker fills or exchange statements.",
            "Fees and slippage are configured assumptions; slippage is embedded in entry/exit fills and must not be deducted again from net P&L.",
            "R multiples use fixed initial stop distance and configured notional; they are model-derived, not account-level risk.",
            "No parameter search, optimization, strategy promotion, broker API call, order submission or automated execution occurs.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
