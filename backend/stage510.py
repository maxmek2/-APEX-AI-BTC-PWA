"""Stage 5.10: cost-aware edge and break-even diagnostics.

Tests the frozen Stage 5.7 candidate and frozen Stage 4.4 baseline on the
chronological training slice only. Quantifies the gross edge needed to cover
the configured round-trip fee, how many gross winners are erased by fees,
and where the simulated expectancy is lost. No parameter search or promotion.
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


def _pf(values: list[float]):
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    return round(gains / losses, 4) if losses else ("infinite" if gains else None)


def _round(value: float) -> float:
    return round(float(value), 6)


def _trade_cost_profile(
    trades: list[dict], atr_by_base: list[float | None], bars: list[dict],
    notional_usd: float, fee_rate: float, stop_atr_multiple: float = 1.5,
) -> dict:
    time_to_index = {bar.get("t"): i for i, bar in enumerate(bars)}
    enriched = []
    gross_values, net_values, fees_values = [], [], []
    groups: dict[str, list[dict]] = defaultdict(list)
    reason_groups: dict[str, list[dict]] = defaultdict(list)
    gross_positive = gross_negative = cost_erased = net_positive = 0
    total_fee_bps = []
    break_even_bps = []
    break_even_atr = []
    cost_r_values = []
    cost_coverage = []

    for trade in trades:
        entry = float(trade["entry_price"])
        exit_price = float(trade["exit_price"])
        if entry <= 0 or exit_price <= 0:
            continue
        qty = notional_usd / entry
        gross = (exit_price - entry) * qty
        fees = (entry + exit_price) * qty * fee_rate
        net = gross - fees
        gross_values.append(gross)
        net_values.append(net)
        fees_values.append(fees)

        entry_index = time_to_index.get(trade.get("entry_time"))
        signal_index = entry_index - 1 if entry_index is not None and entry_index > 0 else None
        atr = atr_by_base[signal_index] if signal_index is not None else None
        risk_usd = qty * float(atr) * stop_atr_multiple if atr is not None and float(atr) > 0 else None

        fee_bps = fees / notional_usd * 10000
        required_move_bps = fees / (qty * entry) * 10000 if qty > 0 and entry > 0 else None
        required_move_atr = fees / (qty * float(atr)) if atr is not None and float(atr) > 0 else None
        fee_r = fees / risk_usd if risk_usd else None
        coverage = gross / fees if gross > 0 and fees > 0 else None

        if gross > 0:
            gross_positive += 1
            if net <= 0:
                cost_erased += 1
        elif gross < 0:
            gross_negative += 1
        if net > 0:
            net_positive += 1

        total_fee_bps.append(fee_bps)
        if required_move_bps is not None:
            break_even_bps.append(required_move_bps)
        if required_move_atr is not None:
            break_even_atr.append(required_move_atr)
        if fee_r is not None:
            cost_r_values.append(fee_r)
        if coverage is not None:
            cost_coverage.append(coverage)

        outcome = "GROSS_LOSS" if gross < 0 else ("GROSS_WIN_ERASED_BY_FEES" if net <= 0 else "NET_WIN")
        item = {
            "entry_time": trade.get("entry_time"),
            "exit_time": trade.get("exit_time"),
            "exit_reason": str(trade.get("exit_reason") or "UNKNOWN"),
            "entry_price": entry,
            "exit_price": exit_price,
            "gross_pnl_usd": round(gross, 4),
            "fees_usd": round(fees, 4),
            "net_pnl_usd": round(net, 4),
            "gross_r_multiple": round(gross / risk_usd, 4) if risk_usd else None,
            "net_r_multiple": round(net / risk_usd, 4) if risk_usd else None,
            "fee_cost_r": round(fee_r, 4) if fee_r is not None else None,
            "fee_cost_bps_of_notional": round(fee_bps, 4),
            "break_even_price_move_bps": round(required_move_bps, 4) if required_move_bps is not None else None,
            "break_even_price_move_atr": round(required_move_atr, 4) if required_move_atr is not None else None,
            "gross_to_fee_coverage": round(coverage, 4) if coverage is not None else None,
            "gross_outcome_class": outcome,
        }
        enriched.append(item)
        groups[outcome].append(item)
        reason_groups[item["exit_reason"]].append(item)

    def summarize(items: list[dict]) -> dict:
        gross = [x["gross_pnl_usd"] for x in items]
        fees = [x["fees_usd"] for x in items]
        net = [x["net_pnl_usd"] for x in items]
        wins = sum(x > 0 for x in net)
        return {
            "trades": len(items),
            "gross_positive_trades": sum(x > 0 for x in gross),
            "net_winning_trades": wins,
            "net_win_rate_percent": round(wins / len(items) * 100, 2) if items else 0,
            "gross_pnl_usd": round(sum(gross), 4),
            "fees_usd": round(sum(fees), 4),
            "net_pnl_usd": round(sum(net), 4),
            "gross_profit_factor": _pf(gross),
            "net_profit_factor": _pf(net),
            "average_net_per_trade_usd": round(sum(net) / len(net), 4) if net else 0,
        }

    total_gross = sum(gross_values)
    total_fees = sum(fees_values)
    total_net = sum(net_values)
    cost_erased_share = cost_erased / gross_positive * 100 if gross_positive else 0
    return {
        "summary": {
            **summarize(enriched),
            "gross_losing_trades": gross_negative,
            "gross_winning_trades": gross_positive,
            "gross_winners_erased_by_fees": cost_erased,
            "gross_winners_erased_share_percent": round(cost_erased_share, 2),
            "gross_positive_but_net_negative_trades": sum(
                1 for x in enriched if x["gross_pnl_usd"] > 0 and x["net_pnl_usd"] < 0
            ),
            "fee_to_gross_positive_pnl_percent": round(
                total_fees / sum(x for x in gross_values if x > 0) * 100, 2
            ) if sum(x for x in gross_values if x > 0) > 0 else None,
            "gross_expectancy_usd_per_trade": round(total_gross / len(trades), 4) if trades else 0,
            "net_expectancy_usd_per_trade": round(total_net / len(trades), 4) if trades else 0,
            "average_fee_bps_of_notional": round(sum(total_fee_bps) / len(total_fee_bps), 4) if total_fee_bps else None,
            "median_break_even_price_move_bps": round(median(break_even_bps), 4) if break_even_bps else None,
            "median_break_even_price_move_atr": round(median(break_even_atr), 4) if break_even_atr else None,
            "median_fee_cost_r": round(median(cost_r_values), 4) if cost_r_values else None,
            "median_gross_to_fee_coverage": round(median(cost_coverage), 4) if cost_coverage else None,
            "estimated_slippage_is_embedded_in_fills": True,
        },
        "gross_outcome_attribution": {k: summarize(v) for k, v in sorted(groups.items())},
        "exit_reason_attribution": {k: summarize(v) for k, v in sorted(reason_groups.items())},
        "trade_ledger": enriched[-50:],
    }


def _diagnosis(candidate: dict, baseline: dict) -> list[str]:
    s = candidate["summary"]
    b = baseline["summary"]
    notes = []
    if s["gross_expectancy_usd_per_trade"] <= 0:
        notes.append("Candidate gross expectancy is non-positive before fees; transaction-cost reduction alone cannot create a positive edge.")
    elif s["net_expectancy_usd_per_trade"] <= 0:
        notes.append("Candidate gross expectancy is positive but net expectancy is non-positive after configured fees; compare the required break-even move with realized gross movement.")
    if s["gross_winners_erased_share_percent"] > 0:
        notes.append(f"Fees erase {s['gross_winners_erased_share_percent']:.1f}% of gross-winning trades in this training sample.")
    if s["median_fee_cost_r"] is not None:
        notes.append(f"Median round-trip fee burden is {s['median_fee_cost_r']:.3f}R using the fixed 1.5 ATR initial-stop model.")
    if s["net_pnl_usd"] <= b["net_pnl_usd"]:
        notes.append("Candidate net P&L does not exceed the frozen Stage 4.4 baseline in this sample.")
    else:
        notes.append("Candidate net P&L exceeds the frozen Stage 4.4 baseline in this sample, but both remain in-sample and require independent validation.")
    notes.append("These are accounting and sample diagnostics, not causal proof or evidence of future profitability.")
    return notes


def run_stage510_cost_edge_diagnostics(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.10")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    integrity = audit_bar_integrity(bars)
    if not integrity["structural_integrity_passed"]:
        return {
            "stage": "5.10", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": integrity, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    training_bars = bars[:split]
    built = build_stage57_candidate_signals(training_bars)
    baseline_signals = build_stage44_signals(
        training_bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    baseline_result = run_breakout_backtest(
        training_bars, baseline_signals["signals"]["breakout_pullback_relvol"],
        baseline_signals["atr_by_base"], starting_equity, notional_usd,
        fee_rate, slippage_bps,
    )
    candidate_result = run_breakout_backtest(
        training_bars, built["signals"], built["atr_by_base"],
        starting_equity, notional_usd, fee_rate, slippage_bps,
    )
    candidate_profile = _trade_cost_profile(
        candidate_result["trades"], built["atr_by_base"], training_bars,
        notional_usd, fee_rate,
    )
    baseline_profile = _trade_cost_profile(
        baseline_result["trades"], baseline_signals["atr_by_base"], training_bars,
        notional_usd, fee_rate,
    )
    return {
        "stage": "5.10",
        "status": "TRAINING_COST_EDGE_DIAGNOSTIC_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": training_bars[0].get("t"), "to": training_bars[-1].get("t")},
        "assumptions": {
            "starting_equity_usd": starting_equity,
            "fixed_notional_usd": notional_usd,
            "fee_rate_per_side": fee_rate,
            "slippage_bps_per_side": slippage_bps,
            "stop_atr_multiple": 1.5,
            "reward_risk": 2.0,
            "slippage_treatment": "Embedded in simulated entry and exit fills; never subtracted again from net P&L.",
            "strategy_parameters_frozen": True,
        },
        "candidate": {
            "name": "Frozen Stage 5.7 hourly trend-gated Stage 4.4 pullback + relative volume",
            "metrics": candidate_result["metrics"],
            "cost_edge": candidate_profile,
        },
        "baseline": {
            "name": "Frozen Stage 4.4 pullback + relative volume",
            "metrics": baseline_result["metrics"],
            "cost_edge": baseline_profile,
        },
        "candidate_vs_baseline_net_pnl_usd": round(
            candidate_result["metrics"]["net_pnl_usd"] - baseline_result["metrics"]["net_pnl_usd"], 4
        ),
        "diagnosis": _diagnosis(candidate_profile, baseline_profile),
        "holdout": {
            "status": "SEALED_NOT_ACCESSED",
            "reason": "Signals, trades and cost attribution are computed only on the chronological training slice.",
        },
        "limitations": [
            "Break-even price move is the gross movement from executed entry needed to cover estimated round-trip fees; execution slippage is already embedded in the fills.",
            "Fee and slippage inputs are modelling assumptions, not verified broker fee schedules or actual fills.",
            "R cost uses the fixed 1.5 ATR stop and configured notional; it is not account-level risk.",
            "Attribution is descriptive and cannot prove that costs, a session or a signal feature caused an outcome.",
            "No parameter search, optimization, strategy selection or promotion; no broker API calls, order submission or automated execution.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
