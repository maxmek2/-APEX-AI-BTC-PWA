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
- In the PWA Settings, enter the same token in **Paper API access token**. The optional **Remember on this device** setting stores it in that browser's local storage; turn it off on shared devices. The token is not committed to frontend JavaScript. Never enter Alpaca API credentials in the PWA.
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


## Stage 4 — Rolling out-of-sample robustness research

- `GET /api/backtest/stage4-4?timeframe=5Min&limit=10000` compares fixed relative-volume and post-breakout pullback variants on a chronological training/untouched holdout split, with completed-hour diagnostics and 0/5/10/20 bps cost sensitivity. Long-only, read-only, `RESEARCH_ONLY_NOT_CERTIFIED`; no orders are submitted.
- `GET /api/backtest/stage4-3?timeframe=5Min&limit=10000` compares a 15m Donchian-20 close breakout, breakout plus volume above the prior-20 median, and breakout+volume with a fully completed 1h EMA50/EMA200 bullish trend. Entry is the next 5m open; stop is 1.5x 15m ATR14 and target is 2R. It reports chronological training/untouched holdout metrics and 0/5/10/20 bps slippage sensitivity. Requires at least 3,000 5m bars to establish the 1h EMA200 context. Long-only, read-only, and returns `RESEARCH_ONLY_NOT_CERTIFIED`; no orders are submitted.\n- `GET /api/backtest/rolling-oos?timeframe=5Min&limit=1000&windows=4` runs the unchanged EMA9/EMA21 + ATR14 rules over sequential, non-overlapping out-of-sample windows.
- The first 30% of the sample is reserved for indicator/history warm-up; entries are blocked until each later window begins. Each window starts flat, so its metrics are a segmented comparison rather than one continuous portfolio curve.
- Default modelling assumptions are 0.25% estimated fee per side and 5 bps adverse slippage per side. These are assumptions, not measured fills or a verified broker fee schedule.
- The endpoint reports each window separately and explicitly returns `RESEARCH_ONLY_NOT_CERTIFIED`. Positive windows do not prove future profitability or complete Stage 4.
- The route is read-only. It makes historical market-data reads only and never submits orders or calls an Alpaca write endpoint.
- This is an additional diagnostic, not a replacement for controlled Paper lifecycle tests, realistic fee verification, intrabar data, or independent review.


## Stage 4.1 — Training-only parameter search and cost sensitivity

- `GET /api/backtest/optimize?timeframe=5Min&limit=1000` evaluates a small, fixed 18-configuration grid (EMA 9/21, 12/26, 20/50; ATR stop 1.5x/2.0x; reward/risk 1.5/2.0/2.5).
- Parameter selection uses training-period net PnL only. The later chronological holdout is evaluated once using the selected parameters and is never used to rank or select candidates.
- The selected configuration is stress-tested on the untouched holdout at 0, 5, 10 and 20 bps adverse slippage per side; fee assumptions remain explicit.
- The endpoint reports all training candidates, selected training metrics, untouched holdout metrics, boundary checks, and limitations. It returns `RESEARCH_ONLY_NOT_CERTIFIED`.
- The candidate grid is intentionally small, but training selection can still overfit. The holdout is not independent future validation and cannot certify profitability.
- Drawdown in the underlying backtest is closed-trade drawdown; intratrade mark-to-market drawdown is not yet modelled.
- The endpoint is read-only: historical data GET requests only, no Paper or live order submissions.


## Stage 4.3 — Breakout momentum research

- `GET /api/backtest/stage4-3?timeframe=5Min&limit=10000` compares three predeclared long-only variants: 15m Donchian-20 close breakout; breakout plus 15m volume above the prior-20 median; and breakout+volume with completed 1h EMA50 > EMA200 and close > EMA50.
- Breakout and volume thresholds use only the 20 completed 15m candles before the signal candle. Signals are evaluated only at a completed 15m close and simulated at the next 5m open.
- Stop is 1.5x completed 15m ATR14 and target is 2R. The report includes chronological training and untouched holdout metrics plus slippage sensitivity at 0, 5, 10 and 20 bps per side.
- Requires at least 3,000 5m bars to provide warm-up for the 1h EMA200 context. Incomplete 15m/1h aggregation buckets are discarded.
- BTC crypto volume is venue-reported, not consolidated global volume. Fee/slippage assumptions, OHLC stop-first handling, fixed notional and closed-trade drawdown remain limitations.
- Long-only spot-compatible research; no short orders, Paper orders, or live orders. Returns `RESEARCH_ONLY_NOT_CERTIFIED`.

## Stage 4.2 — Multi-timeframe and entry-filter research

- `GET /api/backtest/stage4-2?timeframe=5Min&limit=2000` compares five predeclared long-only variants: baseline EMA9/EMA21, completed 15m+1h EMA trend confirmation, Wilder RSI14 50–70, ATR14/close minimum 0.04%, and the combined filters.
- Higher-timeframe candles are aggregated from complete 5m groups only. A partial 15m or 1h candle is never used for its own signal, preventing higher-timeframe intrabar look-ahead.
- Each variant is reported separately on a chronological training segment and untouched later holdout. Filter settings are fixed in advance and are not selected or tuned on holdout.
- Entry remains signal-at-5m-close and next-5m-open fill. The existing stop-first OHLC exit model, 0.25% fee-per-side default, and configurable adverse slippage remain assumptions.
- This is an EMA/RSI/ATR multi-timeframe filter experiment, not a complete ICT implementation. RSI and ATR thresholds are hypotheses and need broader validation.
- The endpoint is read-only and returns `RESEARCH_ONLY_NOT_CERTIFIED`; it never submits Paper or live orders.


## Stage 4.5 — train-only parameter research
- GET `/api/backtest/stage4-5?timeframe=5Min&limit=10000` runs a predeclared 27-combination grid for relative-volume threshold (1.2/1.5/1.8), pullback tolerance (0.15/0.25/0.40 ATR), and confirmation window (2/4/6 completed 15m bars).
- Candidate selection uses training data only and requires at least 10 trades, positive net P/L, and net profit factor above 1. If no candidate qualifies, no holdout strategy is selected or evaluated.
- At most one selected configuration is evaluated on the untouched chronological holdout, with 0/5/10/20 bps slippage sensitivity. This reduces holdout multiple-comparison bias; it does not prove future profitability.
- Stage 4.4 training boundary is corrected: the training simulation ends before the first holdout candle; holdout fills begin no earlier than the next 5m open.
- Stage 4.5 is research-only. No Alpaca order/write API is called; Auto Entry remains OFF and Exit Manager remains DISARMED.


## Stage 4.6 — extended-history walk-forward
- GET `/api/backtest/stage4-6?timeframe=5Min&limit=30000&folds=3` requests up to 30,000 BTC/USD 5m bars through paginated Alpaca history.
- Uses one frozen, predeclared baseline (relative volume 1.5, pullback tolerance 0.25 ATR, four completed 15m bars, stop 1.5 ATR, target 2R). No fold holdout is used to select parameters.
- Divides the later half of the available history into 2–5 chronological, non-overlapping folds. Each fold starts with fresh simulated equity and closes any remaining position at that fold boundary.
- Reports per-fold trade counts, net P/L, drawdown, and 0/5/10/20 bps slippage sensitivity.
- More history and multiple folds improve diagnostics but do not guarantee representativeness or future profitability. Endpoint is read-only and does not call Alpaca order/write APIs.


## Stage 4.7 — bootstrap robustness diagnostics
- GET `/api/backtest/stage4-7?timeframe=5Min&limit=30000&folds=3&simulations=2000` resamples closed-trade net P/L from the fixed-parameter walk-forward folds.
- Reports final-equity and closed-trade drawdown P05/median/P95, plus the fraction of resampled paths ending above starting equity.
- Uses a fixed seed for reproducibility. Bootstrap is not a forecast and assumes trade outcomes can be resampled; serial dependence, volatility clustering, regime changes, and unseen execution costs are not modelled.
- If no closed trades exist, the endpoint returns no bootstrap distribution rather than inventing one.
- Read-only research; no broker order/write calls.


## Stage 4.8 — read-only shadow snapshot
- GET `/api/research/shadow-snapshot?timeframe=5Min&limit=3000` fetches completed BTC/USD 5m candles and checks the frozen Stage 4.4 pullback + relative-volume setup.
- Returns the latest completed candle, most recent observed setup, signal age/freshness, and diagnostics.
- This is a one-shot snapshot, not a continuously running monitor or persistent signal log.
- It does not access Paper account controls, create positions, submit orders, or arm the Exit Manager. `paper_order_enabled`, `order_submitted`, and `alpaca_write_api_called` remain false.


## Stage 4.9 — local execution safety audit
- GET `/api/research/safety-audit` checks the configured broker host allow-list, Paper Auto Entry state, and Exit Manager armed state.
- It makes no broker API calls and changes no state. It does not verify broker positions, open orders, fills, secret quality, Render uptime, or deployment configuration.
- The endpoint always reports live trading and live orders as unsupported/disabled. A safe local configuration is not certification for Paper or live execution.


## Stage 5.0 — final readiness review
- GET `/api/research/final-readiness` consolidates the local safety audit and existing Stage 6 readiness gates.
- The endpoint is assessment-only and intentionally returns `NOT_READY` until extended-history research results, paper lifecycle evidence, protection, security/monitoring and independent authorization gates are completed.
- It makes no broker API calls, changes no execution state, and cannot enable live trading or submit orders.


## Stage 5.3 — Strategy diagnostics and training-only optimization

- `GET /api/research/stage5-3/run?timeframe=5Min&limit=10000` fetches historical BTC/USD market data and returns baseline training/holdout diagnostics plus a predeclared 108-candidate parameter grid.
- The baseline diagnostics separate training and holdout exit reasons, volatility-regime outcomes, fee/slippage attribution, win rate, holding time and closed-trade drawdown.
- Candidate parameters vary relative-volume threshold (1.2/1.5/1.8), pullback tolerance (0.15/0.25/0.40 ATR), confirmation window (2/4 bars), stop distance (1.0/1.5/2.0 ATR), and reward/risk (1.5/2.0).
- Candidate ranking and qualification use training metrics only: at least 30 trades, positive net P/L, net profit factor above 1, and closed-trade drawdown no greater than 5% by default.
- At most one candidate that passes every training gate is evaluated on the untouched holdout. If none qualifies, the holdout is not used to select or rescue a candidate.
- The Stage 4.4 pullback+relative-volume signal now applies the requested relative-volume threshold consistently to both breakout and pullback confirmations.
- The endpoint uses historical market-data GET only. It does not call Paper account/order/position endpoints, submit orders, enable Auto Entry, or change execution state. Research results do not certify future profitability.


## Stage 5.4 — market-regime and walk-forward robustness

- `GET /api/research/stage5-4/run?timeframe=5Min&limit=10000` evaluates the frozen Stage 4.4 pullback+relative-volume baseline without optimizing or selecting parameters.
- Classifies signal context using the latest fully completed 1h EMA20/EMA50 trend (bull, bear, mixed, unavailable) and completed 15m ATR14/close volatility terciles. Regime attribution is descriptive only, not a rule for cherry-picking trades.
- Reports chronological 60/40 training and untouched holdout metrics, exit/cost diagnostics, regime attribution, and 3–6 non-overlapping sequential holdout folds.
- Default assumptions: $100 simulated starting equity, $10 fixed notional, 0.25% fee per side, 5 bps adverse slippage per side, four folds, minimum 10 trades per fold, and a 5% maximum closed-trade drawdown gate.
- No fold is used to tune or choose parameters. Each fold starts flat. Boundary checks require simulated entries to occur after the fold begins.
- Historical gates are sample sufficiency and consistency checks, not certification of future profitability. Costs are assumptions, OHLC intrabar path is unknown, and intratrade mark-to-market drawdown is not modeled.
- Historical market-data GET only. Does not call Paper account/order/position endpoints, submit orders, or change execution state. Auto Entry remains OFF.


## Stage 5.5 — extended history and cost audit

- `GET /api/research/stage5-5/run?timeframe=5Min&limit=30000` fetches up to 30,000 BTC/USD M5 bars using the existing paginated Alpaca historical market-data reader.
- Audits timestamp parsing, duplicate/order violations, five-minute grid alignment, OHLC consistency, finite values, nonnegative volume, observed gaps and estimated missing intervals.
- Replays the frozen Stage 4.4 `breakout_pullback_relvol` baseline with a chronological 60/40 split and fixed $100 equity, $10 notional, 0.25% fee per side and 5 bps slippage per side.
- Reconciles every simulated trade and aggregate gross P&L, fees, slippage and net P&L. Slippage is already reflected in executed prices and gross P&L, so it is reported but not deducted a second time.
- Reports the latest 20 training and holdout trades. An audit pass confirms structural and arithmetic checks only; it does not certify profitability.
- Historical market-data GET only. No account, order, position or execution endpoint; no order submission; Auto Entry remains OFF.


## Stage 5.6 — training-only strategy failure attribution

- `GET /api/research/stage5-6/run?timeframe=5Min&limit=30000` audits historical bar structure, then truncates all strategy calculations to the chronological training segment (default 60%).
- Replays only the frozen Stage 4.4 `breakout_pullback_relvol` baseline with $100 starting equity, $10 fixed notional, 0.25% fee per side and 5 bps slippage per side.
- Attributes training outcomes by exit reason and entry regime; reports holding duration, losing streak, gross/net P&L, fee burden and a bounded training ledger.
- Holdout signals, trades, regimes and metrics are deliberately not calculated or returned. Holdout remains sealed for a later independent test after a new strategy is frozen.
- No parameter optimization, selection, promotion, account/order/position calls, order submission or execution-state changes. Auto Entry remains OFF.
- Findings are descriptive hypotheses only and do not prove causation or profitability.


## Frozen candidate — RSI Martingale Grid (research only)
- The selected candidate is RSI14 > 55 plus the previous completed 5-minute candle bearish, synthetic SHORT direction only.
- Starting simulation equity $100; first leg $2; 0.5% grid spacing; 2x notional multiplier; maximum two legs; maximum total notional exposure $6; basket take-profit reference 1% below weighted-average short entry.
- Read-only signal endpoint: GET /api/strategy/martingale-grid. It uses completed 5-minute Alpaca BTC/USD candles only.
- This endpoint reports a synthetic SHORT setup and grid reference levels. It does not create paper positions, submit broker orders, or enable Auto Entry.
- Alpaca BTC/USD spot is long-only in this integration; therefore this SHORT Martingale Grid cannot be routed to Alpaca Paper as a real short strategy. It requires a separate short-capable venue or a dedicated synthetic paper ledger before any execution work.
- This strategy is a preliminary research candidate, not certified profitable. Keep Auto Entry OFF and Exit Manager DISARMED.
