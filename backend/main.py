import os
from typing import Any
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
load_dotenv()
KEY=os.getenv("ALPACA_API_KEY",""); SECRET=os.getenv("ALPACA_SECRET_KEY","")
BASE=os.getenv("ALPACA_BASE_URL","https://paper-api.alpaca.markets").rstrip("/")
DATA=os.getenv("ALPACA_DATA_URL","https://data.alpaca.markets").rstrip("/")
HEADERS={"APCA-API-KEY-ID":KEY,"APCA-API-SECRET-KEY":SECRET}
app=FastAPI(title="APEX AI BTC API",version="0.1.0")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","http://localhost:5500").split(","),allow_credentials=False,allow_methods=["GET"],allow_headers=["*"])
async def get_json(url:str,params:dict[str,Any]|None=None):
 if not KEY or not SECRET: raise HTTPException(503,"Alpaca paper credentials are not configured on the server")
 try:
  async with httpx.AsyncClient(timeout=12) as client:
   r=await client.get(url,headers=HEADERS,params=params); r.raise_for_status(); return r.json()
 except httpx.HTTPStatusError as e: raise HTTPException(502,f"Alpaca API returned {e.response.status_code}") from e
 except httpx.HTTPError as e: raise HTTPException(502,"Unable to reach Alpaca API") from e
@app.get("/health")
async def health(): return {"status":"ok","mode":"paper","automated_execution":False}
@app.get("/api/account")
async def account():
 d=await get_json(f"{BASE}/v2/account")
 return {k:d.get(k) for k in ("status","currency","cash","equity","buying_power","portfolio_value","trading_blocked")} | {"mode":"paper"}
@app.get("/api/market/btc")
async def btc_market():
 d=await get_json(f"{DATA}/v1beta3/crypto/us/latest/trades",{"symbols":"BTC/USD"})
 t=d.get("trades",{}).get("BTC/USD")
 return {"symbol":"BTC/USD","price":t.get("p") if t else None,"timestamp":t.get("t") if t else None}
# Intentionally no order-submission endpoint in this initial safe build.
