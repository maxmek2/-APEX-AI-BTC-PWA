# APEX AI BTC PWA

Mobile-first BTC/USD scalping dashboard connected to the user's Alpaca paper account.

## Safety defaults
- Paper account only.
- Automated execution is OFF.
- No order-submission endpoint in the initial build.
- Never store API credentials in frontend code or commit secrets to Git.

## Project structure
- frontend/: installable Progressive Web App.
- backend/: FastAPI service for secure Alpaca paper-account and market-data reads.

## Backend setup
1. Copy backend/.env.example to backend/.env.
2. Add Alpaca PAPER API credentials to backend/.env.
3. Install dependencies: pip install -r backend/requirements.txt
4. Run: uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000

Serve frontend over HTTPS or localhost. Configure the API reverse proxy so /api routes to the backend.
