"""Stage 5.14 decision-gate regression tests."""
from datetime import datetime, timedelta, timezone

from backend.stage514 import _evaluate, run_stage514_strategy_decision_gate


def sample_bars(count=12000):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(count):
        phase = (i // 900) % 4
        drift = 0.7 if phase == 0 else -0.55 if phase == 1 else 0.03 if phase == 2 else 0.12
        close = 50000 + i * drift + ((i % 19) - 9) * (2.5 if phase in (0, 1) else 0.8)
        out.append({
            "t": (start + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
            "o": close - 0.5, "h": close + 2.5, "l": close - 2.5,
            "c": close, "v": 100 + (i % 11) * 4,
        })
    return out


def test_stage514_requires_all_predeclared_evidence_gates():
    metrics = {"trades": 90, "net_pnl_usd": 1.0, "net_profit_factor": 1.2}
    cohorts = {
        "cohorts": [
            {"trades": 30, "net_pnl_usd": 0.2},
            {"trades": 30, "net_pnl_usd": 0.3},
            {"trades": 30, "net_pnl_usd": 0.5},
        ],
        "summary": {"populated_cohorts": 3, "positive_net_cohorts": 3},
    }
    entry = {"summary": {"false_breakout_share_percent": 10}, "entry_quality_attribution": {}}
    result = _evaluate("test", metrics, cohorts, entry)
    assert result["decision"] == "RESEARCH_GO"
    assert result["gates_passed"] == result["gates_total"] == 5


def test_stage514_blocks_negative_or_under_sampled_candidate():
    metrics = {"trades": 43, "net_pnl_usd": -2.38, "net_profit_factor": 0.2058}
    cohorts = {
        "cohorts": [
            {"trades": 14, "net_pnl_usd": -0.89},
            {"trades": 9, "net_pnl_usd": -0.53},
            {"trades": 20, "net_pnl_usd": -0.96},
        ],
        "summary": {"populated_cohorts": 3, "positive_net_cohorts": 0},
    }
    entry = {"summary": {"false_breakout_share_percent": 39.53}, "entry_quality_attribution": {}}
    result = _evaluate("test", metrics, cohorts, entry)
    assert result["decision"] == "NO_GO"
    assert result["gates_passed"] == 0
    assert result["gates"]["minimum_30_training_trades"] is True
    assert result["gates"]["positive_training_net_pnl"] is False
    assert result["gates"]["all_three_cohorts_have_30_trades"] is False


def test_stage514_full_report_keeps_holdout_sealed_and_execution_off():
    report = run_stage514_strategy_decision_gate(sample_bars(), requested_bars=12000)
    assert report["stage"] == "5.14"
    assert report["status"].startswith("TRAINING_STRATEGY_DECISION_")
    assert report["training_bars"] == 7200
    assert report["holdout"]["status"] == "SEALED_NOT_ACCESSED"
    assert report["holdout_accessed"] is False
    assert report["broker_api_called"] is False
    assert report["order_submitted"] is False
    assert report["automated_execution"] is False


def test_stage514_rejects_short_history():
    import pytest
    with pytest.raises(ValueError, match="5000 bars"):
        run_stage514_strategy_decision_gate(sample_bars(3000), requested_bars=3000)
