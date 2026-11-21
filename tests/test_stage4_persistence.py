"""SQLite runtime-state tests. No Alpaca calls or orders are made."""
from backend import main


def test_runtime_state_is_restored_but_execution_stays_off(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STATE_DB_PATH", str(tmp_path / "runtime.sqlite3"))

    main._auto_entry.update({
        "enabled": True,
        "last_signal_bar": "2026-11-22T00:00:00Z",
        "trades_today": 3,
    })
    main._exit_manager.update({
        "armed": True,
        "stop_price": 95000.0,
        "target_price": 98000.0,
        "last_event": "TEST_STATE",
    })
    main._persist_runtime_state()

    main._auto_entry.update({
        "enabled": True,
        "last_signal_bar": None,
        "trades_today": 0,
    })
    main._exit_manager.update({
        "armed": True,
        "stop_price": None,
        "target_price": None,
    })

    main._restore_runtime_state()

    assert main._auto_entry["enabled"] is False
    assert main._exit_manager["armed"] is False
    assert main._auto_entry["last_signal_bar"] == "2026-11-22T00:00:00Z"
    assert main._auto_entry["trades_today"] == 3
    assert main._exit_manager["stop_price"] == 95000.0
    assert main._exit_manager["target_price"] == 98000.0


def test_runtime_state_store_creates_database_and_table(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STATE_DB_PATH", str(tmp_path / "nested" / "runtime.sqlite3"))
    main._persist_runtime_state()
    assert (tmp_path / "nested" / "runtime.sqlite3").exists()
