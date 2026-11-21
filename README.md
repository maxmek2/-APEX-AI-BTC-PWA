# APEX AI BTC PWA

Mobile-first BTC/USD scalping research dashboard with a secure, read-only Alpaca paper-account backend.

## Current build: 0.5
- iPhone-friendly installable PWA shell.
- Alpaca paper account equity and buying power endpoint.
- Latest BTC/USD trade endpoint.
- Historical crypto bars endpoint returns the newest requested candles in chronological order (oldest to newest), with latest candle timestamp and close included.
- Experimental EMA(9)/EMA(21) trend filter and ATR(14) volatility diagnostic.
- Read-only historical backtest endpoint for a long-only EMA/ATR strategy.
- Paper execution safety status endpoint and risk-bounded BTC trade preview endpoint (preview only; no order is submitted).\n- Automated execution and order submission remain OFF.

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
- GET /api/backtest?timeframe=5Min&limit=2000&starting_equity=100&notional_usd=10\n- GET /api/paper/status\n- POST /api/paper/preview (JSON: timeframe, risk_percent, max_notional_usd, stop_atr_multiple, reward_risk)

This build remains non-executing: it cannot place, modify, or cancel orders. The preview endpoint only calculates a proposed setup and risk-bounded notional.


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
- Automated execution remains OFF. No order-submission endpoint is implemented.\n- Alpaca crypto supports only simple order class in the current order-class matrix; bracket/OCO protective exits are not available for BTC crypto. This build therefore blocks order submission until a verified server-side exit manager is implemented. See https://docs.alpaca.markets/us/docs/orders-at-alpaca and https://docs.alpaca.markets/us/reference/getallordersforaccount.
