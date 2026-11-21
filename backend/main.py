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


def ema_series(values:list[float],period:int)->list[float|None]:
    out: list[float | None]=[None]*len(values)
    if len(values)<period:
        return out
    value=sum(values[:period])/period
    out[period-1]=value
    alpha=2/(period+1)
    for index in range(period,len(values)):
        value=alpha*values[index]+(1-alpha)*value
        out[index]=value
    return out

def atr_series(bars:list[dict],period:int=14)->list[float|None]:
    out: list[float | None]=[None]*len(bars)
    if len(bars)<=period:
        return out
    ranges=[]
    for index in range(1,len(bars)):
        high=float(bars[index]["h"])
        low=float(bars[index]["l"])
        previous=float(bars[index-1]["c"])
        ranges.append(max(high-low,abs(high-previous),abs(low-previous)))
    value=sum(ranges[:period])/period
    out[period]=value
    for index in range(period+1,len(bars)):
        value=(value*(period-1)+ranges[index-1])/period
        out[index]=value
    return out

@app.get("/api/backtest")
async def backtest(
    timeframe:str=Query("5Min",pattern="^(5Min|15Min|1Hour)$"),
    limit:int=Query(2000,ge=100,le=5000),
    starting_equity:float=Query(100,gt=0,le=1000000),
    notional_usd:float=Query(10,gt=0,le=100000),
):
    """Read-only long-only EMA/ATR backtest. It never submits orders."""
    data=await get_json(
        f"{DATA}/v1beta3/crypto/us/bars",
        {"symbols":"BTC/USD","timeframe":timeframe,"limit":limit,"sort":"asc"}
    )
    bars=data.get("bars",{}).get("BTC/USD",[])
    if len(bars)<50:
        return {
            "symbol":"BTC/USD","timeframe":timeframe,"bars_used":len(bars),
            "status":"insufficient_data","automated_execution":False
        }

    closes=[float(item["c"]) for item in bars]
    fast=ema_series(closes,9)
    slow=ema_series(closes,21)
    volatility=atr_series(bars,14)
    fee_rate=0.0025  # Explicit estimate: 0.25% per side, not an account fee quote.
    stop_multiple=1.5
    target_multiple=2.0
    position=None
    trades=[]

    # Signal is evaluated at candle close; fill is next candle open.
    for index in range(21,len(bars)-1):
        if position is None:
            current_atr=volatility[index]
            if (fast[index] is not None and slow[index] is not None
                and current_atr is not None and current_atr>0
                and fast[index]>slow[index] and closes[index]>fast[index]):
                entry=float(bars[index+1]["o"])
                quantity=notional_usd/entry
                position={
                    "entry":entry,"quantity":quantity,
                    "stop":entry-stop_multiple*current_atr,
                    "target":entry+target_multiple*current_atr,
                    "entry_time":bars[index+1].get("t")
                }
        else:
            candle=bars[index]
            hit_stop=float(candle["l"])<=position["stop"]
            hit_target=float(candle["h"])>=position["target"]
            if hit_stop or hit_target:
                # Conservative rule if both levels occur in one candle: stop first.
                exit_price=position["stop"] if hit_stop else position["target"]
                gross=(exit_price-position["entry"])*position["quantity"]
                fees=(position["entry"]*position["quantity"]+exit_price*position["quantity"])*fee_rate
                trades.append({
                    "entry_time":position["entry_time"],"exit_time":candle.get("t"),
                    "entry_price":round(position["entry"],2),"exit_price":round(exit_price,2),
                    "exit_reason":"STOP_LOSS" if hit_stop else "TAKE_PROFIT",
                    "gross_pnl_usd":round(gross,4),"estimated_fees_usd":round(fees,4),
                    "net_pnl_usd":round(gross-fees,4)
                })
                position=None

    if position is not None:
        exit_price=closes[-1]
        gross=(exit_price-position["entry"])*position["quantity"]
        fees=(position["entry"]*position["quantity"]+exit_price*position["quantity"])*fee_rate
        trades.append({
            "entry_time":position["entry_time"],"exit_time":bars[-1].get("t"),
            "entry_price":round(position["entry"],2),"exit_price":round(exit_price,2),
            "exit_reason":"END_OF_DATA","gross_pnl_usd":round(gross,4),
            "estimated_fees_usd":round(fees,4),"net_pnl_usd":round(gross-fees,4)
        })

    net_values=[item["net_pnl_usd"] for item in trades]
    winners=[value for value in net_values if value>0]
    losers=[value for value in net_values if value<=0]
    net_total=sum(net_values)
    gross_wins=sum(winners)
    gross_losses=-sum(losers)
    equity=starting_equity
    peak=starting_equity
    max_drawdown=0.0
    for value in net_values:
        equity+=value
        peak=max(peak,equity)
        if peak>0:
            max_drawdown=max(max_drawdown,(peak-equity)/peak*100)

    return {
        "symbol":"BTC/USD","timeframe":timeframe,"bars_used":len(bars),
        "period":{"from":bars[0].get("t"),"to":bars[-1].get("t")},
        "has_more_data":bool(data.get("next_page_token")),
        "strategy":{
            "direction":"LONG_ONLY","entry":"EMA9 > EMA21 and close > EMA9; fill next candle open",
            "stop_loss":"1.5 x ATR14","take_profit":"2.0 x ATR14",
            "position_notional_usd":notional_usd,
            "estimated_fee_per_side_percent":fee_rate*100,
            "same_candle_stop_and_target":"STOP_LOSS_FIRST"
        },
        "metrics":{
            "starting_equity_usd":round(starting_equity,2),
            "ending_equity_usd":round(equity,2),
            "net_pnl_usd":round(net_total,4),
            "gross_pnl_usd":round(sum(item["gross_pnl_usd"] for item in trades),4),
            "estimated_fees_usd":round(sum(item["estimated_fees_usd"] for item in trades),4),
            "trades":len(trades),"wins":len(winners),"losses":len(losers),
            "win_rate_percent":round(len(winners)/len(trades)*100,2) if trades else 0,
            "profit_factor":round(gross_wins/gross_losses,4) if gross_losses else None,
            "max_drawdown_percent":round(max_drawdown,2),
            "average_net_per_trade_usd":round(net_total/len(trades),4) if trades else 0
        },
        "recent_trades":trades[-20:],
        "status":"historical_simulation_not_a_live_result",
        "automated_execution":False,
        "warning":"Fee rate is an estimate, not a verified Alpaca fee. OHLC candles cannot reveal intrabar order; stop is assumed first when both levels are touched. Results are not a promise of future performance."
    }


# Read-only foundation: no order-submission endpoint is implemented.
