# APEX AI BTC PWA

Mobile-first BTC/USD scalping research dashboard with a secure, read-only Alpaca paper-account backend.

## Current build: 0.8
- iPhone-friendly installable PWA shell.
- Alpaca paper account equity and buying power endpoint.
- Latest BTC/USD trade endpoint.
- Historical crypto bars endpoint returns the newest requested candles in chronological order (oldest to newest), with latest candle timestamp and close included.
- Experimental EMA(9)/EMA(21) trend filter and ATR(14) volatility diagnostic.
- Read-only historical backtest endpoint for a long-only EMA/ATR strategy.
- Paper execution safety status and risk-bounded BTC trade preview endpoints (preview only; no entry order is submitted).\n- Server-side BTC protective exit manager with explicit arm/disarm endpoints; starts DISARMED, manages only an existing BTC paper position, and never opens a position.\n- Automated execution and order submission remain OFF.

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
- GET /api/backtest?timeframe=5Min&limit=2000&starting_equity=100&notional_usd=10\n- GET /api/paper/status\n- POST /api/paper/preview (JSON: timeframe, risk_percent, max_notional_usd, stop_atr_multiple, reward_risk)\n- GET /api/paper/exit-manager\n- POST /api/paper/exit-manager/simulate (pure deterministic SL/TP test; no Alpaca calls or state changes)\n- POST /api/paper/lifecycle/simulate (simulated entry → position detection → protective levels → HOLD/SL/TP exit; no Alpaca calls or orders)\n- POST /api/paper/exit-manager/arm (requires an existing BTC paper position)\n- POST /api/paper/exit-manager/disarm

Entry execution remains disabled. The exit manager can submit a market close for an existing BTC paper position only after explicit arming and only when a stop/target is crossed.


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
- Entry automation remains OFF. The server-side exit manager is DISARMED by default.\n- Exit manager polls the latest BTC trade every 5 seconds while armed; on stop/target trigger it requests liquidation of the BTCUSD position using Alpaca Paper DELETE /v2/positions/BTCUSD.\n- This is a software-managed exit, not an exchange-native stop. Render sleep/restarts, network outages, market-data delays and slippage can cause missed or late exits. Do not rely on it as guaranteed protection.\n- Manager state is in-memory and resets on server restart; after restart it is disarmed and must be inspected/re-armed manually.\n- Alpaca crypto bracket/OCO exits are not available in this integration. Close-position endpoint reference: https://docs.alpaca.markets/us/reference/deleteopenposition-1.
\n\n## Lifecycle simulation\n- The lifecycle simulator is entirely in-memory and accepts an entry price, ATR(14), and a sequence of simulated prices.\n- It calculates a long-only stop at 1.5 × ATR and target at 3.0 × ATR from entry (2R).\n- It does not create a broker position, call Alpaca, or change Exit Manager state.\n