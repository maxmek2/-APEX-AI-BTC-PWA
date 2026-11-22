"""Stage 5.6: training-only trade failure attribution.

This stage diagnoses the frozen Stage 4.4 baseline. It does not optimize,
select, or promote parameters and does not evaluate the untouched holdout.
"""
from __future__ import annotations

from datetime import datetime

try:
    from .stage43 import run_breakout_backtest
    from .stage44 import build_stage44_signals
    from .stage54 import build_market_regimes
    from .stage55 import audit_bar_integrity
except ImportError:
    from stage43 import run_breakout_backtest
    from stage44 import build_stage44_signals
    from stage54 import build_market_regimes
    from stage55 import audit_bar_integrity


def _duration_minutes(trade: dict) -> float | None:
    try:
        entry = datetime.fromisoformat(str(trade["entry_time"]).replace("Z", "+00:00"))
        exit_ = datetime.fromisoformat(str(trade["exit_time"]).replace("Z", "+00:00"))
        return max(0.0, (exit_ - entry).total_seconds() / 60)
    except (KeyError, TypeError, ValueError):
        return None


def _group_summary(trades: list[dict]) -> dict:
    net = [float(t.get("net_pnl_usd") or 0) for t in trades]
    gross = [float(t.get("gross_pnl_usd") or 0) for t in trades]
    fees = sum(float(t.get("estimated_fees_usd") or 0) for t in trades)
    winners = [x for x in net if x > 0]
    losers = [-x for x in net if x < 0]
    loss_total = sum(losers)
    profit_total = sum(winners)
    return {
        "trades": len(trades),
        "wins": len(winners),
        "losses": len(losers),
        "win_rate_percent": round(len(winners) / len(trades) * 100, 2) if trades else 0.0,
        "gross_pnl_usd": round(sum(gross), 4),
        "fees_usd": round(fees, 4),
        "net_pnl_usd": round(sum(net), 4),
        "net_profit_factor": round(profit_total / loss_total, 4) if loss_total else ("infinite" if profit_total else None),
        "average_net_per_trade_usd": round(sum(net) / len(net), 4) if net else 0.0,
    }


def _longest_losing_streak(trades: list[dict]) -> int:
    longest = current = 0
    for trade in trades:
        if float(trade.get("net_pnl_usd") or 0) < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _failure_hypotheses(trades: list[dict], gross: float, fees: float,
                        by_reason: dict[str, list[dict]]) -> list[str]:
    hypotheses = []
    if not trades:
        return ["No closed training trades: the current entry condition is too sparse for outcome attribution."]
    if gross <= 0:
        hypotheses.append("Training gross P&L is non-positive before fees; entry/exit behavior itself needs review.")
    # Only compare fees with gross profit when gross P&L is actually positive.
    # If gross is negative, saying fees consume positive gross profit is misleading.
    elif fees >= gross:
        hypotheses.append("Estimated fees consume all positive gross P&L; turnover or trade edge may not cover costs.")
    stop_trades = sum(len(v) for k, v in by_reason.items() if "STOP_LOSS" in k)
    if stop_trades / len(trades) >= 0.5:
        hypotheses.append("At least half of closed trades exit by stop loss; inspect entry timing, market regime and stop distance.")
    if _longest_losing_streak(trades) >= 5:
        hypotheses.append("A losing streak of five or more occurred; inspect whether losses cluster in specific regimes.")
    if not hypotheses:
        hypotheses.append("No single dominant failure signature was established; retain the strategy as unvalidated.")
    return hypotheses


def run_stage56_failure_report(
    bars: list[dict], requested_bars: int,
    starting_equity: float = 100.0, notional_usd: float = 10.0,
    fee_rate: float = 0.0025, slippage_bps: float = 5.0,
    train_fraction: float = 0.60,
) -> dict:
    if len(bars) < 5000:
        raise ValueError("At least 5000 bars are required for Stage 5.6")
    if requested_bars < 5000 or requested_bars > 30000:
        raise ValueError("requested_bars must be between 5000 and 30000")
    if not 0.5 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.5 and 0.8")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0:
        raise ValueError("Invalid capital or transaction cost settings")

    data_audit = audit_bar_integrity(bars)
    if not data_audit["structural_integrity_passed"]:
        return {
            "stage": "5.6", "status": "DATA_INTEGRITY_FAILED",
            "data_audit": data_audit, "holdout_accessed": False,
            "order_submitted": False, "alpaca_write_api_called": False,
            "automated_execution": False,
        }

    split = int(len(bars) * train_fraction)
    train_bars = bars[:split]
    built = build_stage44_signals(
        train_bars, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    mask = built["signals"]["breakout_pullback_relvol"]
    atrs = built["atr_by_base"]
    result = run_breakout_backtest(
        train_bars, mask, atrs, starting_equity, notional_usd,
        fee_rate, slippage_bps,
    )
    trades = result["trades"]
    metrics = result["metrics"]
    regimes = build_market_regimes(train_bars)["regime_by_base"]

    time_index = {bar.get("t"): index for index, bar in enumerate(train_bars)}
    by_reason: dict[str, list[dict]] = {}
    by_regime: dict[str, list[dict]] = {}
    enriched = []
    durations = []
    for trade in trades:
        reason = str(trade.get("exit_reason") or "UNKNOWN")
        by_reason.setdefault(reason, []).append(trade)
        entry_index = time_index.get(trade.get("entry_time"))
        signal_index = entry_index - 1 if entry_index is not None else None
        regime = regimes[signal_index] if signal_index is not None and signal_index >= 0 else "REGIME_UNAVAILABLE"
        by_regime.setdefault(regime, []).append(trade)
        duration = _duration_minutes(trade)
        if duration is not None:
            durations.append(duration)
        enriched.append({
            **trade,
            "entry_regime": regime,
            "holding_minutes": round(duration, 2) if duration is not None else None,
        })

    gross = float(metrics.get("gross_pnl_usd") or 0)
    fees = float(metrics.get("estimated_fees_usd") or 0)
    net = float(metrics.get("net_pnl_usd") or 0)
    fee_burden = fees / abs(gross) * 100 if gross else None
    avg_gross = gross / len(trades) if trades else 0.0
    avg_fees = fees / len(trades) if trades else 0.0
    reason_summary = {key: _group_summary(value) for key, value in sorted(by_reason.items())}
    regime_summary = {key: _group_summary(value) for key, value in sorted(by_regime.items())}

    diagnostics = {
        "signal_count": sum(bool(x) for x in mask),
        "closed_trade_count": len(trades),
        "exit_reason_attribution": reason_summary,
        "entry_regime_attribution": regime_summary,
        "longest_consecutive_losing_trades": _longest_losing_streak(trades),
        "average_holding_minutes": round(sum(durations) / len(durations), 2) if durations else None,
        "median_holding_minutes": round(sorted(durations)[len(durations)//2], 2) if durations else None,
        "gross_profit_usd": round(sum(float(t.get("gross_pnl_usd") or 0) for t in trades if float(t.get("net_pnl_usd") or 0) > 0), 4),
        "gross_loss_usd": round(sum(float(t.get("gross_pnl_usd") or 0) for t in trades if float(t.get("net_pnl_usd") or 0) < 0), 4),
        "fee_burden_percent_of_absolute_gross_pnl": round(fee_burden, 2) if fee_burden is not None else None,
        "average_gross_per_trade_usd": round(avg_gross, 4),
        "average_fee_per_trade_usd": round(avg_fees, 4),
        "average_gross_covers_average_fee": avg_gross > avg_fees,
    }

    hypotheses = _failure_hypotheses(trades, gross, fees, by_reason)
    training_pass = (
        len(trades) >= 30
        and net > 0
        and metrics.get("net_profit_factor") not in (None, "infinite")
        and float(metrics.get("net_profit_factor") or 0) > 1
    )
    return {
        "stage": "5.6",
        "status": "TRAINING_DIAGNOSIS_COMPLETE_NOT_VALIDATED",
        "symbol": "BTC/USD", "timeframe": "5Min",
        "bars_received": len(bars), "requested_bars": requested_bars,
        "training_bars": split,
        "training_period": {"from": train_bars[0].get("t"), "to": train_bars[-1].get("t")},
        "frozen_strategy": {
            "name": "Stage 4.4 breakout_pullback_relvol",
            "donchian_lookback": 20, "relative_volume_threshold": 1.5,
            "pullback_atr": 0.25, "pullback_bars": 4,
            "stop_atr_multiple": 1.5, "reward_risk": 2.0,
            "selection_or_optimization": False,
        },
        "training": {"metrics": metrics, "diagnostics": diagnostics,
                     "trade_ledger": enriched[-50:]},
        "failure_hypotheses": hypotheses,
        "training_evidence_gate_passed": training_pass,
        "holdout": {
            "status": "SEALED_NOT_ACCESSED",
            "reason": "Stage 5.6 is diagnostic only. No holdout signals, trades, regimes or metrics are calculated.",
        },
        "next_step": "If a new strategy is designed, freeze it before a single untouched holdout evaluation in a separate stage.",
        "limitations": [
            "Attribution is descriptive, not causal proof that a regime or exit reason caused losses.",
            "Training-only results are in-sample and must not be presented as out-of-sample evidence.",
            "Regime volatility terciles are descriptive thresholds computed within the training sample.",
            "Estimated fees and slippage are assumptions, not broker fills.",
            "OHLC simulation cannot reconstruct intrabar liquidity or exact price path.",
            "No strategy parameters are optimized or selected by this stage.",
        ],
        "market_data_api_read": True,
        "holdout_accessed": False,
        "broker_api_called": False,
        "alpaca_write_api_called": False,
        "order_submitted": False,
        "automated_execution": False,
    }
