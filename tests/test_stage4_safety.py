"""Offline, deterministic safety tests for the Stage 4 exit decision logic.

These tests never call Alpaca, create orders, or change application state.
"""
import pytest

from backend.main import evaluate_exit_simulation


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (98.0, "STOP_LOSS_TRIGGERED"),
        (112.0, "TAKE_PROFIT_TRIGGERED"),
        (105.0, "HOLD_POSITION"),
        (100.0, "HOLD_POSITION"),
    ],
)
def test_exit_decision_boundaries(price, expected):
    result = evaluate_exit_simulation(
        entry=100.0, stop=98.0, target=112.0, price=price
    )
    assert result["event"] == expected
    assert result["order_submitted"] is False
    assert result["manager_state_changed"] is False
    assert result["would_request_paper_close"] is (expected != "HOLD_POSITION")


@pytest.mark.parametrize(
    ("entry", "stop", "target"),
    [
        (100.0, 100.0, 110.0),
        (100.0, 101.0, 110.0),
        (100.0, 90.0, 100.0),
        (100.0, 110.0, 90.0),
    ],
)
def test_invalid_long_protective_levels_are_rejected(entry, stop, target):
    with pytest.raises(ValueError):
        evaluate_exit_simulation(
            entry=entry, stop=stop, target=target, price=100.0
        )


def test_exit_simulation_is_decision_only():
    result = evaluate_exit_simulation(
        entry=100.0, stop=98.0, target=104.0, price=104.0
    )
    assert result == {
        "event": "TAKE_PROFIT_TRIGGERED",
        "would_request_paper_close": True,
        "order_submitted": False,
        "manager_state_changed": False,
    }
