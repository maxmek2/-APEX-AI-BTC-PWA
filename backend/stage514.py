"""Stage 5.14: deterministic research-only strategy decision gate.

Replays the frozen Stage 5.7 candidate and Stage 4.4 baseline on training
bars only, then applies explicit evidence gates. No holdout is read.
"""
from __future__ import annotations

try:
    from .stage43 import run_breakout_backtest
    from .stage44 import build_stage44_signals
    from .stage55 import audit_bar_integrity
    from .stage57 import build_stage57_candidate_signals
    from .stage512 import _build_entry_features, _analyse_entry_quality
    from .stage513 import _cohorts, _summarize
except ImportError:
    from stage43 import run_breakout_backtest
    from stage44 import build_stage44_signals
    from stage55 import audit_bar_integrity
    from stage57 import build_stage57_candidate_signals
    from stage512 import _build_entry_features, _analyse_entry_quality
    from stage513 import _cohorts, _summarize


def _profit_factor_pass(metrics):
    pf = metrics.get("net_profit_factor")
    return pf == "infinite" or (isinstance(pf, (int, float)) and pf > 1.0)


def _evaluate(name, metrics, cohorts, entry_diag):
    cohort_rows = cohorts["cohorts"]
    gates = {
        "minimum_30_training_trades": int(metrics.get("trades", 0)) >= 30,
        "positive_training_net_pnl": float(metrics.get("net_pnl_usd", 0)) > 0,
        "training_net_profit_factor_above_1": _profit_factor_pass(metrics),
        "all_three_chronological_cohorts_positive": (
            len(cohort_rows) == 3
            and all(int(x["trades"]) > 0 and float(x["net_pnl_usd"]) > 0 for x in cohort_rows)
        ),
        "all_three_cohorts_have_30_trades": (
            len(cohort_rows) == 3 and all(int(x["trades"]) >= 30 for x in cohort_rows)
        ),
    }
    return {
        "name": name,
        "overall_metrics": metrics,
        "cohort_summary": cohorts["summary"],
        "cohorts": cohort_rows,
        "entry_quality_summary": entry_diag["summary"],
        "entry_quality_groups": entry_diag["entry_quality_attribution"],
        "gates": gates,
        "gates_passed": sum(gates.values()),
        "gates_total": len(gates),
        "decision": "RESEARCH_GO" if all(gates.values()) else "NO_GO",
    }


def run_stage514_strategy_decision_gate(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.14")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0 or slippage_bps >= 10000:
        raise ValueError("Invalid capital or transaction cost settings")

    audit = audit_bar_integrity(bars)
    if not audit["structural_integrity_passed"]:
        return {
            "stage": "5.14", "status": "DATA_INTEGRITY_FAILED",
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
    c_entry = _analyse_entry_quality(c_bt["trades"], train, c_features)
    b_entry = _analyse_entry_quality(b_bt["trades"], train, b_features)
    c_cohorts = _cohorts(c_bt["trades"], train)
    b_cohorts = _cohorts(b_bt["trades"], train)

    candidate_report = _evaluate(
        "Frozen Stage 5.7 hourly trend-gated candidate",
        c_bt["metrics"], c_cohorts, c_entry,
    )
    baseline_report = _evaluate(
        "Frozen Stage 4.4 pullback + relative volume baseline",
        b_bt["metrics"], b_cohorts, b_entry,
    )
    overall = "RESEARCH_GO" if candidate_report["decision"] == "RESEARCH_GO" else "NO_GO"
    failed = [key for key, passed in candidate_report["gates"].items() if not passed]
    findings = [
        "Decision gates are explicit screening criteria, not a guarantee of profitability or a broker-readiness assessment.",
        "All metrics are recomputed from the same chronological training slice and frozen cost assumptions.",
        "Entry-quality and false-breakout observations are descriptive diagnostics; they do not alter the historical trades.",
        "A NO_GO decision means do not promote the candidate and do not use holdout outcomes to rescue it.",
        "A RESEARCH_GO result would only permit a separately approved, one-time untouched holdout evaluation; it would not enable trading.",
    ]
    if failed:
        findings.insert(0, "Candidate failed evidence gates: " + ", ".join(failed) + ".")
    return {
        "stage": "5.14",
        "status": "TRAINING_STRATEGY_DECISION_" + overall,
        "decision": overall,
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train[0].get("t"), "to": train[-1].get("t")},
        "decision_rules": {
            "minimum_total_training_trades": 30,
            "overall_net_pnl_must_be_positive": True,
            "overall_net_profit_factor_must_exceed": 1.0,
            "all_three_chronological_cohorts_must_be_positive": True,
            "minimum_trades_per_cohort": 30,
            "note": "Conservative research screening thresholds fixed before this run; not universal profitability guarantees.",
        },
        "candidate": candidate_report,
        "baseline": baseline_report,
        "failed_candidate_gates": failed,
        "findings": findings,
        "holdout": {"status": "SEALED_NOT_ACCESSED"},
        "limitations": [
            "All gates use in-sample training data and do not establish out-of-sample profitability.",
            "Thirty trades per chronological third is a conservative sample-adequacy flag; it is not a statistical confidence guarantee.",
            "Fees and slippage are assumptions, not verified broker fills.",
            "OHLC backtests cannot prove intrabar path, queue position or live execution quality.",
            "No parameter optimization, strategy changes, strategy promotion, broker writes, order submission or automated execution occurs.",
        ],
        "market_data_api_read": False,
        "holdout_accessed": False,
        "broker_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
