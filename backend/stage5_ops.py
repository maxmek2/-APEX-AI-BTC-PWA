"""Stage 5.1-5.4 offline verification tools. No broker calls or order routes."""
from __future__ import annotations

import math
import os
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["Stage 5 verification"])


class TradeSample(BaseModel):
    gross_pnl_usd: float
    fees_usd: float = Field(ge=0)
    slippage_usd: float = Field(ge=0)


class ResearchRequest(BaseModel):
    training: list[TradeSample] = Field(default_factory=list, max_length=5000)
    holdout: list[TradeSample] = Field(default_factory=list, max_length=5000)
    minimum_trades: int = Field(default=30, ge=10, le=500)


def _metrics(items: list[TradeSample]) -> dict:
    net = [x.gross_pnl_usd - x.fees_usd - x.slippage_usd for x in items]
    gross_profit = sum(x for x in net if x > 0)
    gross_loss = -sum(x for x in net if x < 0)
    equity = peak = 100.0
    max_dd = 0.0
    for pnl in net:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    return {
        "trades": len(net),
        "wins": sum(x > 0 for x in net),
        "losses": sum(x < 0 for x in net),
        "win_rate_percent": round(sum(x > 0 for x in net) / len(net) * 100, 4) if net else 0.0,
        "gross_profit_usd": round(gross_profit, 4),
        "gross_loss_usd": round(gross_loss, 4),
        "net_pnl_usd": round(sum(net), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if not gross_profit else "infinite"),
        "expectancy_usd_per_trade": round(sum(net) / len(net), 4) if net else 0.0,
        "max_drawdown_percent": round(max_dd, 4),
    }


@router.post("/api/research/stage5-1/evaluate")
async def stage51_evaluate(request: ResearchRequest):
    """Evaluate precomputed, chronological train/holdout trades; does not tune parameters."""
    train = _metrics(request.training)
    holdout = _metrics(request.holdout)
    train_pass = (
        train["trades"] >= request.minimum_trades
        and train["net_pnl_usd"] > 0
        and isinstance(train["profit_factor"], (int, float))
        and train["profit_factor"] > 1
    )
    holdout_pass = (
        train_pass
        and holdout["trades"] >= request.minimum_trades
        and holdout["net_pnl_usd"] > 0
        and isinstance(holdout["profit_factor"], (int, float))
        and holdout["profit_factor"] > 1
    )
    return {
        "stage": "5.1",
        "result": "RESEARCH_GATE_PASSED" if holdout_pass else "NOT_VALIDATED",
        "training": train,
        "holdout": holdout,
        "training_gate_passed": train_pass,
        "holdout_gate_passed": holdout_pass,
        "minimum_trades_per_segment": request.minimum_trades,
        "selection_policy": "No parameter tuning; training and holdout are evaluated separately.",
        "limitations": ["Caller supplies already-computed trades; this endpoint does not fetch market data.",
                       "A passing sample is research evidence, not proof of future profitability."],
        "broker_api_called": False,
        "order_submitted": False,
    }


class LifecycleRequest(BaseModel):
    events: list[Literal["submitted", "partial_fill", "filled", "rejected", "exit_requested", "closed", "restart"]] = Field(min_length=1, max_length=50)


@router.post("/api/paper/stage5-2/lifecycle-simulate")
async def stage52_lifecycle(request: LifecycleRequest):
    state = "NOT_STARTED"
    history = []
    valid = {
        "NOT_STARTED": {"submitted"},
        "SUBMITTED": {"partial_fill", "filled", "rejected", "restart"},
        "PARTIAL_FILL": {"partial_fill", "filled", "exit_requested", "restart"},
        "FILLED": {"exit_requested", "restart"},
        "EXIT_REQUESTED": {"closed", "restart"},
        "REJECTED": set(),
        "CLOSED": set(),
        "RESTART_RECOVERY_REQUIRED": set(),
    }
    mapping = {"submitted": "SUBMITTED", "partial_fill": "PARTIAL_FILL", "filled": "FILLED",
               "rejected": "REJECTED", "exit_requested": "EXIT_REQUESTED",
               "closed": "CLOSED", "restart": "RESTART_RECOVERY_REQUIRED"}
    for event in request.events:
        if event not in valid.get(state, set()):
            return {"stage": "5.2", "result": "INVALID_SEQUENCE", "state": state,
                    "rejected_event": event, "history": history,
                    "broker_api_called": False, "order_submitted": False}
        state = mapping[event]
        history.append({"event": event, "state": state})
    return {"stage": "5.2", "result": "SIMULATION_ONLY", "state": state,
            "history": history, "restart_requires_manual_reconciliation": state == "RESTART_RECOVERY_REQUIRED",
            "broker_api_called": False, "order_submitted": False,
            "positions_changed": False}


class RiskRequest(BaseModel):
    equity_usd: float = Field(gt=0)
    proposed_notional_usd: float = Field(gt=0)
    risk_percent: float = Field(ge=0, le=100)
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    quote_age_seconds: float = Field(ge=0)
    signal_age_seconds: float = Field(ge=0)
    has_open_position: bool = False
    has_open_order: bool = False
    daily_loss_percent: float = Field(ge=0)


@router.post("/api/risk/stage5-3/preflight")
async def stage53_risk_preflight(request: RiskRequest):
    stop_distance = abs(request.entry_price - request.stop_price)
    risk_usd = request.proposed_notional_usd * stop_distance / request.entry_price
    checks = [
        ("notional_within_10pct_equity", request.proposed_notional_usd <= request.equity_usd * 0.10),
        ("risk_within_requested_budget", risk_usd <= request.equity_usd * request.risk_percent / 100),
        ("stop_is_below_entry_for_long", request.stop_price < request.entry_price),
        ("quote_fresh_within_30s", request.quote_age_seconds <= 30),
        ("signal_fresh_within_10m", request.signal_age_seconds <= 600),
        ("no_existing_position", not request.has_open_position),
        ("no_existing_order", not request.has_open_order),
        ("daily_loss_below_2pct", request.daily_loss_percent < 2.0),
    ]
    passed = all(ok for _, ok in checks)
    return {"stage": "5.3", "result": "PREFLIGHT_PASS" if passed else "BLOCKED",
            "checks": [{"check": name, "passed": ok} for name, ok in checks],
            "estimated_stop_risk_usd": round(risk_usd, 4),
            "max_notional_rule": "10% of equity",
            "daily_loss_hard_limit_percent": 2.0,
            "broker_api_called": False, "order_submitted": False}


@router.get("/api/security/stage5-4/config-audit")
async def stage54_config_audit():
    """Reports configuration presence/shape only; never returns secret values."""
    token = os.getenv("APEX_API_TOKEN", "").strip()
    base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").strip().rstrip("/")
    cors = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
    checks = [
        {"check": "dashboard_token_present", "passed": bool(token)},
        {"check": "dashboard_token_length_at_least_32", "passed": len(token) >= 32},
        {"check": "alpaca_host_is_exact_paper", "passed": base == "https://paper-api.alpaca.markets"},
        {"check": "cors_wildcard_not_enabled", "passed": "*" not in cors},
    ]
    passed = sum(x["passed"] for x in checks)
    return {"stage": "5.4", "result": "CONFIG_REVIEW_PASS" if passed == len(checks) else "REQUIRES_REVIEW",
            "checks_passed": passed, "checks_total": len(checks), "checks": checks,
            "secret_values_exposed": False,
            "limitations": ["Does not verify Render dashboard settings, secret rotation history, persistent disk, alert delivery, identity provider, or network policy."],
            "broker_api_called": False, "order_submitted": False}
