# APEX AI BTC PWA

Mobile-first BTC/USD scalping dashboard with secure Alpaca Paper monitoring and explicitly gated Paper execution.

## Current build: 1.0
- iPhone-friendly installable PWA shell.
- Alpaca paper account equity and buying power endpoint.
- Latest BTC/USD trade endpoint.
- Historical crypto bars endpoint returns the newest requested candles in chronological order (oldest to newest), with latest candle timestamp and close included.
- Experimental EMA(9)/EMA(21) trend filter and ATR(14) volatility diagnostic.
- Read-only historical backtest endpoint for a long-only EMA/ATR strategy; fetches paginated history up to 10,000 bars and reports page/history coverage diagnostics.
- Paper execution safety status and risk-bounded BTC trade preview endpoints (preview only; no entry order is submitted).
- Server-side BTC protective exit manager with explicit arm/disarm endpoints; starts DISARMED, manages only an existing BTC paper position, and never opens a position.
- Paper Auto Entry is OFF by default and requires explicit authenticated enable; live trading is not implemented.

## Safety
- Use Alpaca PAPER credentials only.
- Keep credentials in backend environment variables; never commit .env.
- Do not expose credentials to frontend JavaScript.
- Signals are experimental and not backtested or financial advice.
- BTC/USD spot trading is long-only on this paper integration; SHORT_SETUP is informational only.

## Backend
1. Copy backend/.env.example to backend/.env and enter Alpaca PAPER API credentials.
2. Install: pip install -r backend/requirements.txt
3. Run: uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000
4. Configure HTTPS hosting/reverse proxy so frontend /api requests reach the backend.

## API
- GET /health
- GET /api/account
- GET /api/market/btc
- GET /api/market/bars?timeframe=5Min&limit=100 (newest candles, returned chronologically)
- GET /api/signal?timeframe=5Min
- GET /api/backtest?timeframe=5Min&limit=2000&starting_equity=100&notional_usd=10
- GET /api/paper/status
- POST /api/paper/preview (JSON: timeframe, risk_percent, max_notional_usd, stop_atr_multiple, reward_risk)
- GET /api/paper/auto-entry/dry-run (read-only eligibility preflight; no order writes)
- GET /api/paper/auto-entry
- POST /api/paper/auto-entry/enable (explicitly enables guarded Paper-only automatic entry)
- POST /api/paper/auto-entry/disable
- GET /api/paper/exit-manager
- POST /api/paper/exit-manager/simulate (pure deterministic SL/TP test; no Alpaca calls or state changes)
- POST /api/paper/lifecycle/simulate (simulated entry → position detection → protective levels → HOLD/SL/TP exit; no Alpaca calls or orders)
- POST /api/paper/exit-manager/arm (requires an existing BTC paper position)
- POST /api/paper/exit-manager/disarm

Paper Auto Entry remains OFF by default and requires explicit authenticated activation. The Exit Manager can submit a market close for an existing BTC Paper position only after explicit arming or Auto Entry position detection and only when a stop/target is crossed.


## Backtest assumptions
- Long-only entries: EMA(9) > EMA(21) and candle close > EMA(9); entry at the next candle open.
- Stop loss: 1.5 x ATR(14). Take profit: 2.0 x ATR(14).
- Default position notional: USD 10; default starting equity: USD 100.
- Estimated fee assumption: 0.25% per side. This is a modelling assumption, not a verified Alpaca fee quote.
- If a candle touches both stop and target, the simulator assumes the stop is hit first.
- Backtest output is historical simulation only and is not a forecast or proof of profitability.

## Dashboard v1.0 reference layout
- BTC/USD ticker with selected timeframe and displayed-window price change.
- Candlestick chart with EMA 9, EMA 21, and Alpaca crypto tick-volume bars.
- EMA crossover markers are setup/watch annotations only; they are not executed orders.
- Read-only paper account equity, cash, buying power, and current open positions.
- Multi-timeframe context: 5-minute, 15-minute, 1-hour, and aggregated 4-hour candles.
- Rule-alignment score and optional read-only historical backtest report.
- Daily realized P&L, win rate, and drawdown remain unavailable until verified fill-history accounting is implemented; the UI intentionally does not fabricate them.
- Pause Monitor, Stop Monitor, and View Report control dashboard monitoring/report display only. They do not pause or stop a trading bot.
- Entry automation remains OFF. The server-side exit manager is DISARMED by default.
- Exit manager polls the latest BTC trade every 5 seconds while armed; on stop/target trigger it requests liquidation of the BTCUSD position using Alpaca Paper DELETE /v2/positions/BTCUSD.
- This is a software-managed exit, not an exchange-native stop. Render sleep/restarts, network outages, market-data delays and slippage can cause missed or late exits. Do not rely on it as guaranteed protection.
- Manager state is in-memory and resets on server restart; after restart it is disarmed and must be inspected/re-armed manually.
- Alpaca crypto bracket/OCO exits are not available in this integration. Close-position endpoint reference: https://docs.alpaca.markets/us/reference/deleteopenposition-1.


## Lifecycle simulation
- The lifecycle simulator is entirely in-memory and accepts an entry price, ATR(14), and a sequence of simulated prices.
- It calculates a long-only stop at 1.5 × ATR and target at 3.0 × ATR from entry (2R).
- It does not create a broker position, call Alpaca, or change Exit Manager state.


## Paper automatic-entry safeguards
- Auto Entry is OFF by default and resets OFF after a backend restart.
- Maximum five submitted entries per UTC day; only one open BTC position and one open BTC order are allowed at a time.
- Entries require a new 5-minute LONG_SETUP, a 15-minute cooldown, valid quote/ATR, and risk sizing.
- Per-entry risk budget is 1% of equity; order notional is capped at the lowest of USD 10, 10% of equity, and ATR-based risk sizing.
- Auto Entry disables itself if equity falls 2% or more below the UTC-day starting equity. This is a hard 2% daily-loss guard.
- When a BTC position is detected while Auto Entry is enabled, the server automatically arms the existing software-polled exit manager.
- This is an experimental Paper-only controller. Market orders and server-polled exits can be affected by latency, fills, outages and slippage. It is not suitable for live trading without further verification.


## Stage 4 safety hardening (2026-11-22)
- Auto Entry rejects M5 signal bars older than 10 minutes or more than 30 seconds in the future.
- Auto Entry rejects missing/stale Alpaca quotes; quote timestamps must be within 30 seconds.
- The read-only dry-run reports separate freshness checks for the signal candle and quote. An old LONG_SETUP is not eligible.
- Exit Manager validates protective levels against the actual average entry before evaluating a close.
- Exit Manager disarms before submitting a close request to reduce duplicate close requests after timeouts; inspect Alpaca positions/orders after any close-request failure.
- On backend startup, an existing BTC position is detected and the Exit Manager status reports RESTART_RECOVERY_REQUIRED. It does not pretend the position is protected and does not auto-close it.
- These changes do not make software-polled exits exchange-native or guaranteed. Render downtime/restarts, network/API outages, gaps and slippage remain material risks.
- Auto Entry and Exit Manager must remain OFF/DISARMED during verification. ENTRY_ELIGIBLE is only a read-only preflight, not proof that an order was safely filled or protected.
- Stage 4 is not certified complete until automated tests, controlled Paper order/fill/partial-fill/rejection/restart recovery tests, and deployed smoke tests pass. No live trading is supported or authorized by this project.


## Paper API access protection (Stage 4)

- Every `/api/paper/*` route plus the private `/api/account` and `/api/positions` reads requires `Authorization: Bearer <token>`.
- Set a long, random `APEX_API_TOKEN` environment variable on the Render backend service before using Paper status or preview features. If it is missing, Paper routes fail closed with HTTP 503; an invalid/missing browser token returns HTTP 401.
- In the PWA Settings, enter the same token in **Paper API access token**. It is held in browser session storage and is not committed to frontend JavaScript. Never enter Alpaca API credentials in the PWA.
- Keep Auto Entry OFF and Exit Manager DISARMED. This token protects access; it does not authorize or activate execution by itself.
- The API token is a shared bearer secret. Rotate it in Render and update the PWA session entry if it is exposed. For production-grade multi-user access, replace the shared token with a proper login/session system and rate limiting.

## Remaining Stage 4 verification gates

- Runtime controller context is now snapshotted to SQLite every five seconds. Configure a Render persistent disk mounted at `/var/data`; without it, the database may be lost on redeploy/restart. Every restart still forces Auto Entry OFF and Exit Manager DISARMED. Broker positions and open orders must be reconciled manually.
- Partial-fill handling is fail-closed when an open BTC order is detected alongside a position; automated cancel/replace and complete order lifecycle reconciliation are not implemented.
- Exit Manager now rejects stale/future latest-trade timestamps and checks whether the position remains after a close request. A remaining position is flagged for inspection; it is not automatically retried.
- Automated tests now cover deterministic exit decisions, API token access, and SQLite state restoration with execution forced off. They still do not simulate Alpaca fills, rejections, partial closes, network timeouts, or actual deployed behavior.
- No order was submitted by these code changes. Paper execution remains unverified and must stay disabled.


## Persistent runtime state and restart recovery

- Auto Entry and Exit Manager operational context is stored in SQLite at `APEX_STATE_DB`; default path is `/var/data/apex_state.sqlite3`.
- **Render requirement:** attach a persistent disk to the backend service and mount it at `/var/data`. Without that disk, the container filesystem may be ephemeral and saved state can be lost on redeploy/restart.
- The service snapshots state every five seconds. A sudden crash can lose the latest unsaved interval.
- On every restart, Auto Entry is forced OFF and Exit Manager is forced DISARMED, even when their prior state was enabled/armed. Restored protective levels and order references are for operator inspection only; they are not treated as active protection.
- If state restoration or persistence fails, both execution controls are forced off/disarmed and an error event is recorded.
- This local SQLite design assumes a single backend instance writing to one mounted disk. Do not scale the service to multiple instances or attach the same SQLite file to concurrent writers. A managed PostgreSQL database is the better future option for multi-instance deployment.
- The operator must still reconcile Alpaca positions and open orders after restart. Persistence is not a substitute for broker reconciliation or exchange-native protection.

## Required Render deployment configuration

1. Add `APEX_API_TOKEN` as a long random secret environment variable.
2. Attach a persistent disk to the backend and mount it at `/var/data`.
3. Optionally set `APEX_STATE_DB=/var/data/apex_state.sqlite3`.
4. Keep the frontend session token in PWA Settings; never place Alpaca credentials in frontend code.
5. After deployment, verify `/health`, authenticated Paper status, Auto Entry OFF, and Exit Manager DISARMED. Do not enable either control as part of smoke testing.



## Paper Auto Entry dashboard controls

- The dashboard includes a read-only **Run safety preflight** action plus explicit **Enable Paper Auto Entry** and **Disable** controls.
- Enable requires an authenticated dashboard token and checks the exact Alpaca Paper host, active/unblocked account, positive equity/buying power, no open BTC position/order, and a disarmed Exit Manager.
- The entry signal is calculated only from completed 5-minute candles. A fresh quote, valid ATR, cooldown, daily loss guard, position/order checks and notional/risk limits are checked again by the server loop before each entry.
- Disabling and re-enabling during the same UTC day does not reset the daily equity baseline, submitted-entry count, cooldown, or last processed candle. Re-enable is blocked after the 2% daily loss threshold or five submitted entries.
- The **Enable** button starts a Paper-only server controller; it can submit Alpaca Paper market orders when a later setup qualifies. It does not place an order immediately just by being enabled.
- Auto Entry remains OFF after server restart. A restart also forces the Exit Manager DISARMED and requires manual broker position/order reconciliation.
- The software-polled exit manager is not exchange-native protection. A position can remain unprotected during startup, network outages, Render restarts or delayed market data. Do not treat this controller as production-safe or live-trading-ready.
- The preflight endpoint is read-only and never submits orders. GitHub CI uses mocks and does not prove actual Alpaca fills or Render runtime behavior.

## Stage 5 — Paper operations validation

- `GET /api/paper/validation` is an authenticated, read-only reconciliation snapshot.
- It checks the exact Alpaca Paper host, account status/equity, Auto Entry OFF, Exit Manager DISARMED, and absence of open BTC positions/orders.
- It performs broker GET requests only. It does not submit, cancel, or close orders.
- A CLEAN snapshot is not proof of fills, partial-fill handling, protective-exit reliability, restart recovery, or strategy profitability. Those require controlled Paper evidence and operator review.

## Stage 6 — Live trading readiness assessment

- `GET /api/live/readiness` returns a read-only seven-gate assessment and a prioritized next-action list.
- It dynamically verifies that Paper Auto Entry is OFF and the Paper Exit Manager is DISARMED; all remaining technical and authorization gates remain blocked until independently evidenced.
- The endpoint reports readiness percentage, gate details, current Paper control states, and explicit no-broker-call/no-order-submitted flags.
- Live trading remains unsupported and hard-locked. There is no live broker adapter or live order route in this project.
- The report intentionally remains NOT_READY until strategy validation, controlled Paper lifecycle evidence, reliable exchange-native protection, production security/monitoring, and explicit authorization are independently satisfied.
- Stage 6 is an assessment only. It does not connect to a live broker, enable execution, or submit orders.


## Chronological out-of-sample research (Stage 4)

- `GET /api/backtest/walk-forward` evaluates the unchanged EMA9/EMA21 + ATR14 rules on a chronological training segment and a later holdout segment.
- Default holdout assumptions: 70% training / 30% test, 0.25% estimated fee per side, and 5 bps adverse slippage per side. These are explicit research assumptions, not verified broker costs.
- Indicator values use historical candles before the holdout boundary for warm-up, but holdout entries cannot occur before the first candle after the split.
- Strategy parameters are fixed; the holdout is not optimized. The report includes separate training and out-of-sample metrics and a check for test-entry boundary leakage.
- A single holdout is only an initial diagnostic. It does not certify robustness, profitability, or readiness; repeat evaluation across multiple market regimes and walk-forward windows.
- The endpoint is read-only and never submits an order.
