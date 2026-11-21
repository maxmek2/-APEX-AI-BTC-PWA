# APEX AI BTC PWA

Mobile-first BTC/USD scalping research dashboard with a secure, read-only Alpaca paper-account backend.

## Current build: 0.2
- iPhone-friendly installable PWA shell.
- Alpaca paper account equity and buying power endpoint.
- Latest BTC/USD trade endpoint.
- Historical 5-minute crypto bars endpoint.
- Experimental EMA(9)/EMA(21) trend filter and ATR(14) volatility diagnostic.
- Automated execution is OFF. No order-submission endpoint exists.

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
- GET /api/market/bars?timeframe=5Min&limit=100
- GET /api/signal?timeframe=5Min

This build is read-only. It cannot place, modify, or cancel orders.
