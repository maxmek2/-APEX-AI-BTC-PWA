import os
from typing import Any
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
KEY=os.getenv("ALPACA_API_KEY","")
SECRET=os.getenv("ALPACA_SECRET_KEY","")
BASE=os.getenv("ALPACA_BASE_URL","https://paper-api.alpaca.markets").rstrip("/")
DATA=os.getenv("ALPACA_DATA_URL","https://data.alpaca.markets").rstrip("/")
HEADERS={"APCA-API-KEY-ID":KEY,"APCA-API-SECRET-KEY":SECRET}

app=FastAPI(title="APEX AI BTC API",version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS","http://localhost:5500").split(","),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

async def get_json(url:str,params:dict[str,Any]|None=None):
    if not KEY or not SECRET:
        raise HTTPException(503,"Alpaca paper credentials are not configured on the server")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.get(url,headers=HEADERS,params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502,f"Alpaca API returned {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502,"Unable to reach Alpaca API") from exc

@app.get("/health")
async def health():
    return {"status":"ok","mode":"paper","automated_execution":False,"version":"0.2.0"}

@app.get("/api/account")
async def account():
    data=await get_json(f"{BASE}/v2/account")
    return {key:data.get(key) for key in (
        "status","currency","cash","equity","buying_power",
        "portfolio_value","trading_blocked"
    )} | {"mode":"paper"}

@app.get("/api/market/btc")
async def btc_market():
    data=await get_json(
        f"{DATA}/v1beta3/crypto/us/latest/trades",
        {"symbols":"BTC/USD"}
    )
    trade=data.get("trades",{}).get("BTC/USD")
    return {
        "symbol":"BTC/USD",
        "price":trade.get("p") if trade else None,
        "timestamp":trade.get("t") if trade else None
    }

@app.get("/api/market/bars")
async def btc_bars(timeframe:str=Query("5Min",pattern="^(1Min|5Min|15Min|1Hour)$"),
                   limit:int=Query(100,ge=30,le=500)):
    data=await get_json(
        f"{DATA}/v1beta3/crypto/us/bars",
        {"symbols":"BTC/USD","timeframe":timeframe,"limit":limit,"sort":"asc"}
    )
    bars=data.get("bars",{}).get("BTC/USD",[])
    return {"symbol":"BTC/USD","timeframe":timeframe,"count":len(bars),"bars":bars}

def ema(values:list[float],period:int)->float|None:
    if len(values)<period:
        return None
    alpha=2/(period+1)
    result=sum(values[:period])/period
    for value in values[period:]:
        result=alpha*value+(1-alpha)*result
    return result

def atr(bars:list[dict],period:int=14)->float|None:
    if len(bars)<period+1:
        return None
    true_ranges=[]
    for index in range(1,len(bars)):
        current=bars[index]
        previous_close=float(bars[index-1]["c"])
        high=float(current["h"]); low=float(current["l"])
        true_ranges.append(max(high-low,abs(high-previous_close),abs(low-previous_close)))
    if len(true_ranges)<period:
        return None
    value=sum(true_ranges[:period])/period
    for tr in true_ranges[period:]:
        value=(value*(period-1)+tr)/period
    return value

@app.get("/api/signal")
async def signal(timeframe:str=Query("5Min",pattern="^(1Min|5Min|15Min|1Hour)$")):
    data=await get_json(
        f"{DATA}/v1beta3/crypto/us/bars",
        {"symbols":"BTC/USD","timeframe":timeframe,"limit":100,"sort":"asc"}
    )
    bars=data.get("bars",{}).get("BTC/USD",[])
    if len(bars)<30:
        return {"signal":"INSUFFICIENT_DATA","timeframe":timeframe,
                "bars_received":len(bars),"automated_execution":False}
    closes=[float(bar["c"]) for bar in bars]
    fast=ema(closes,9); slow=ema(closes,21); volatility=atr(bars,14)
    last=closes[-1]
    if fast is None or slow is None or volatility is None or volatility<=0:
        direction="WAIT"
    elif fast>slow and last>fast:
        direction="LONG_SETUP"
    elif fast<slow and last<fast:
        direction="SHORT_SETUP"
    else:
        direction="WAIT"
    return {
        "symbol":"BTC/USD","timeframe":timeframe,"signal":direction,
        "last_close":last,"ema_9":round(fast,2),"ema_21":round(slow,2),
        "atr_14":round(volatility,2),"bars_used":len(bars),
        "last_bar_time":bars[-1].get("t"),
        "rules":"EMA9/EMA21 trend filter plus close relative to EMA9; ATR14 volatility context",
        "status":"experimental_not_backtested",
        "automated_execution":False
    }

# Read-only foundation: no order-submission endpoint is implemented.
