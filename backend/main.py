import os
from datetime import datetime, timedelta, timezone
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

app=FastAPI(title="APEX AI BTC API",version="0.3.0")

# Normalize configured origins (spaces/trailing slashes can silently break CORS).
configured_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
# Explicitly allow the deployed dashboard origin; keep localhost for local development.
allowed_origins = list(dict.fromkeys([
    "https://apex-ai-btc-dashboard.onrender.com",
    "http://localhost:5500",
    *configured_origins,
]))
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Protect every Paper-control/status route with a server-side bearer token.
# No secret is embedded in the public PWA bundle. Missing server configuration fails closed.
import secrets
from starlette.responses import JSONResponse

@app.middleware("http")
async def protect_paper_api(request, call_next):
    if request.url.path.startswith("/api/paper/") and request.method != "OPTIONS":
        expected = os.getenv("APEX_API_TOKEN", "").strip()
        if not expected:
            return JSONResponse(status_code=503, content={"detail": "Paper API locked: configure APEX_API_TOKEN on the backend"})
        supplied = request.headers.get("authorization", "")
        scheme, _, token = supplied.partition(" ")
        if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, expected):
            return JSONResponse(status_code=401, content={"detail": "Valid Bearer token required"})
    return await call_next(request)

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
    return {"status":"ok","mode":"paper","automated_execution":False,"version":"0.3.0"}

@app.get("/api/account")
async def account():
    data=await get_json(f"{BASE}/v2/account")
    return {key:data.get(key) for key in (
        "status","currency","cash","equity","buying_power",
        "portfolio_value","trading_blocked"
    )} | {"mode":"paper"}

@app.get("/api/positions")
async def positions():
    """Read-only list of current Alpaca paper positions."""
    data=await get_json(f"{BASE}/v2/positions")
    return [{
        "symbol":item.get("symbol"),"qty":item.get("qty"),
        "avg_entry_price":item.get("avg_entry_price"),"market_value":item.get("market_value"),
        "unrealized_pl":item.get("unrealized_pl"),"unrealized_plpc":item.get("unrealized_plpc"),
        "side":item.get("side")
    } for item in data]


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
                   limit:int=Query(100,ge=30,le=5000)):
    """Return the newest Alpaca BTC/USD candles in chronological order."""
    params={"symbols":"BTC/USD","timeframe":timeframe,
            "limit":min(limit,10000),"sort":"desc"}
    if timeframe=="1Hour":
        params["start"]=(datetime.now(timezone.utc)-timedelta(days=180)).isoformat().replace("+00:00","Z")

    newest_first=[]
    page_token=None
    async with httpx.AsyncClient(timeout=30) as client:
        while len(newest_first)<limit:
            page_params=dict(params)
            page_params["limit"]=min(10000,limit-len(newest_first))
            if page_token:
                page_params["page_token"]=page_token
            if not KEY or not SECRET:
                raise HTTPException(503,"Alpaca paper credentials are not configured on the server")
            try:
                response=await client.get(
                    f"{DATA}/v1beta3/crypto/us/bars",
                    headers=HEADERS,params=page_params
                )
                response.raise_for_status()
                payload=response.json()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(502,f"Alpaca API returned {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise HTTPException(502,"Unable to reach Alpaca historical bars API") from exc

            page=payload.get("bars",{}).get("BTC/USD",[])
            newest_first.extend(page)
            page_token=payload.get("next_page_token")
            if not page_token or not page:
                break

    unique={bar.get("t"):bar for bar in newest_first if bar.get("t")}
    bars=[unique[key] for key in sorted(unique)]
    return {
        "symbol":"BTC/USD","timeframe":timeframe,"count":len(bars),"bars":bars,
        "first_bar_time":bars[0].get("t") if bars else None,
        "last_bar_time":bars[-1].get("t") if bars else None,
        "last_close":bars[-1].get("c") if bars else None,
        "history_start":params.get("start"),
        "history_complete":len(bars)>=limit
    }

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
        {"symbols":"BTC/USD","timeframe":timeframe,"limit":100,"sort":"desc"}
    )
    bars=data.get("bars",{}).get("BTC/USD",[])
    bars=list(reversed(bars))  # Keep candles chronological after fetching newest first.
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


def _backtest_exit_for_candle(position: dict, candle: dict) -> tuple[float, str] | None:
    """Resolve one OHLC candle after entry; conservative when path is unknowable."""
    open_price, high, low = float(candle["o"]), float(candle["h"]), float(candle["l"])
    stop, target = float(position["stop"]), float(position["target"])
    hit_stop, hit_target = low <= stop, high >= target
    if open_price <= stop:
        return open_price, "STOP_LOSS_GAP"
    if hit_stop:  # Includes ambiguous candles where both levels were touched.
        return stop, "STOP_LOSS"
    if open_price >= target:
        return open_price, "TAKE_PROFIT_GAP"
    if hit_target:
        return target, "TAKE_PROFIT"
    return None


def run_ema_atr_backtest(bars: list[dict], starting_equity: float = 100.0,
                         notional_usd: float = 10.0, fee_rate: float = 0.0025,
                         slippage_bps: float = 0.0) -> dict:
    """Deterministic long-only close-signal/next-open-fill OHLC backtest.

    Fees apply to executed notional on entry and exit. Slippage is an adverse
    percentage of price on both sides, expressed in basis points.
    """
    if len(bars) < 50:
        raise ValueError("At least 50 candles are required")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0:
        raise ValueError("Equity/notional must be positive; fee and slippage must be non-negative")
    slip = slippage_bps / 10000.0
    if slip >= 1:
        raise ValueError("Slippage must be below 10000 basis points")
    closes = [float(item["c"]) for item in bars]
    fast, slow, volatility = ema_series(closes, 9), ema_series(closes, 21), atr_series(bars, 14)
    position, trades = None, []

    def close_position(candle: dict, exit_price: float, reason: str) -> None:
        nonlocal position
        entry, quantity = float(position["entry"]), float(position["quantity"])
        executed_exit = exit_price * (1.0 - slip)
        gross = (executed_exit - entry) * quantity
        fees = (entry * quantity + executed_exit * quantity) * fee_rate
        slippage_cost = (float(position["reference_entry"]) - entry) * quantity + (exit_price - executed_exit) * quantity
        trades.append({
            "entry_time": position["entry_time"], "exit_time": candle.get("t"),
            "entry_price": round(entry, 2), "exit_price": round(executed_exit, 2),
            "exit_reason": reason, "gross_pnl_usd": round(gross, 4),
            "estimated_fees_usd": round(fees, 4),
            "estimated_slippage_usd": round(slippage_cost, 4),
            "net_pnl_usd": round(gross-fees, 4),
        })
        position = None

    # Signal is known only at candle close; fill is the following candle open.
    for i in range(21, len(bars)-1):
        if position is not None:
            hit = _backtest_exit_for_candle(position, bars[i])
            if hit:
                close_position(bars[i], hit[0], hit[1])
            continue
        a = volatility[i]
        if (fast[i] is None or slow[i] is None or a is None or a <= 0
                or not (fast[i] > slow[i] and closes[i] > fast[i])):
            continue
        entry_bar = bars[i+1]
        reference_entry = float(entry_bar["o"])
        if reference_entry <= 0:
            continue
        entry = reference_entry * (1.0 + slip)
        position = {"entry": entry, "reference_entry": reference_entry,
                    "quantity": notional_usd/entry,
                    "stop": entry-1.5*a, "target": entry+2.0*a,
                    "entry_time": entry_bar.get("t")}
        # Evaluate high/low occurring after the next-open fill on this same candle.
        hit = _backtest_exit_for_candle(position, entry_bar)
        if hit:
            close_position(entry_bar, hit[0], hit[1])

    if position is not None:
        close_position(bars[-1], float(bars[-1]["c"]), "END_OF_DATA")

    gross_values = [float(t["gross_pnl_usd"]) for t in trades]
    fee_values = [float(t["estimated_fees_usd"]) for t in trades]
    slippage_values = [float(t["estimated_slippage_usd"]) for t in trades]
    net_values = [float(t["net_pnl_usd"]) for t in trades]
    exit_breakdown = {}
    for trade in trades:
        reason = trade["exit_reason"]
        item = exit_breakdown.setdefault(reason, {"trades": 0, "net_pnl_usd": 0.0})
        item["trades"] += 1
        item["net_pnl_usd"] += float(trade["net_pnl_usd"])
    for item in exit_breakdown.values():
        item["net_pnl_usd"] = round(item["net_pnl_usd"], 4)
    gp, gl = sum(x for x in gross_values if x > 0), -sum(x for x in gross_values if x < 0)
    np_, nl = sum(x for x in net_values if x > 0), -sum(x for x in net_values if x < 0)
    wins, losses = sum(x > 0 for x in net_values), sum(x < 0 for x in net_values)
    equity = peak = starting_equity
    drawdown = 0.0
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(drawdown, (peak-equity)/peak*100)
    def pf(profit, loss):
        return round(profit/loss, 4) if loss > 0 else ("infinite" if profit > 0 else None)
    metrics = {
        "starting_equity_usd": round(starting_equity, 2),
        "ending_equity_usd": round(equity, 2),
        "net_pnl_usd": round(sum(net_values), 4),
        "gross_pnl_usd": round(sum(gross_values), 4),
        "estimated_fees_usd": round(sum(fee_values), 4),
        "estimated_slippage_usd": round(sum(slippage_values), 4),
        "exit_breakdown": exit_breakdown,
        "trades": len(trades), "wins": wins, "losses": losses,
        "breakeven_trades": sum(x == 0 for x in net_values),
        "win_rate_percent": round(wins/len(trades)*100, 2) if trades else 0,
        "profit_factor": pf(gp, gl), "gross_profit_factor": pf(gp, gl),
        "net_profit_factor": pf(np_, nl), "max_drawdown_percent": round(drawdown, 2),
        "average_net_per_trade_usd": round(sum(net_values)/len(trades), 4) if trades else 0,
    }
    return {"trades": trades, "metrics": metrics}

async def fetch_backtest_bars(timeframe: str, limit: int) -> tuple[list[dict], bool, int]:
    """Fetch up to limit BTC bars using Alpaca pagination; return oldest-to-newest bars."""
    endpoint = f"{DATA}/v1beta3/crypto/us/bars"
    # Alpaca defaults historical crypto bars to the current UTC day when
    # start/end are omitted. Request enough explicit history for the target
    # candle count, plus a one-day buffer, so 2,000 M5 bars span ~7 days.
    interval_seconds = {"1Min": 60, "5Min": 300, "15Min": 900, "1Hour": 3600}.get(timeframe)
    if interval_seconds is None:
        raise HTTPException(400, "Unsupported backtest timeframe")
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(seconds=interval_seconds * limit, days=1)
    start_time = start_dt.isoformat().replace("+00:00", "Z")
    end_time = end_dt.isoformat().replace("+00:00", "Z")

    newest_first: list[dict] = []
    page_token = None
    pages = 0
    has_more_data = False

    while len(newest_first) < limit:
        params = {
            "symbols": "BTC/USD",
            "timeframe": timeframe,
            "start": start_time,
            "end": end_time,
            "limit": min(10000, limit - len(newest_first)),
            "sort": "desc",
        }
        if page_token:
            params["page_token"] = page_token
        data = await get_json(endpoint, params)
        pages += 1
        page = data.get("bars", {}).get("BTC/USD", [])
        newest_first.extend(page)
        next_token = data.get("next_page_token")
        if not next_token or not page:
            has_more_data = False
            break
        if len(newest_first) >= limit:
            has_more_data = True
            break
        page_token = next_token

    unique = {bar.get("t"): bar for bar in newest_first if bar.get("t")}
    selected = sorted(unique.values(), key=lambda bar: bar["t"], reverse=True)[:limit]
    return list(reversed(selected)), has_more_data, pages


@app.get("/api/backtest")
async def backtest(
    timeframe:str=Query("5Min",pattern="^(1Min|5Min|15Min|1Hour)$"),
    limit:int=Query(2000,ge=100,le=10000),
    starting_equity:float=Query(100,gt=0,le=1000000),
    notional_usd:float=Query(10,gt=0,le=100000),
    fee_rate:float=Query(0.0025,ge=0,le=0.02),
    slippage_bps:float=Query(0,ge=0,le=500),
):
    """Read-only long-only EMA/ATR backtest. It never submits orders."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars)<50:
        return {
            "symbol":"BTC/USD","timeframe":timeframe,"bars_used":len(bars),
            "status":"insufficient_data","automated_execution":False
        }

    result = run_ema_atr_backtest(bars, starting_equity, notional_usd, fee_rate, slippage_bps)
    trades, metrics = result["trades"], result["metrics"]
    return {
        "symbol":"BTC/USD","timeframe":timeframe,"bars_used":len(bars),
        "period":{"from":bars[0].get("t"),"to":bars[-1].get("t")},
        "has_more_data":has_more_data,"data_pages_fetched":data_pages,
        "requested_bars":limit,"history_complete_for_request":len(bars) == limit,
        "strategy":{
            "direction":"LONG_ONLY",
            "entry":"EMA9 > EMA21 and close > EMA9; fill next candle open; evaluate entry candle range",
            "stop_loss":"1.5 x ATR14","take_profit":"2.0 x ATR14",
            "position_notional_usd":notional_usd,
            "estimated_fee_per_side_percent":fee_rate*100,
            "slippage_basis_points_per_side":slippage_bps,
            "same_candle_stop_and_target":"STOP_LOSS_FIRST",
            "gap_fill":"Stop gaps fill at candle open; target gaps fill at candle open; intrabar path otherwise unknown"
        },
        "metrics":metrics,"recent_trades":trades[-20:],
        "status":"historical_simulation_not_a_live_result","automated_execution":False,
        "warning":"Fee rate is configurable and remains an estimate, not a verified Alpaca fee. Slippage is a user-supplied adverse-price assumption, not measured market impact. OHLC candles cannot reveal intrabar order; stop is assumed first when both levels are touched. Results are historical simulations, not a promise of future performance."
    }


# Read-only foundation: no order-submission endpoint is implemented.


# Paper execution safety layer (preview only).
# Alpaca's current crypto order-class matrix supports simple orders only;
# bracket/OCO exits are not supported for crypto. Therefore this build
# deliberately refuses to submit BTC orders until reliable server-side
# protective-exit management is implemented and verified.
from pydantic import BaseModel, Field

PAPER_API_ORIGIN = "https://paper-api.alpaca.markets"

class PaperPreviewRequest(BaseModel):
    timeframe: str = Field(default="5Min", pattern="^(1Min|5Min|15Min|1Hour)$")
    risk_percent: float = Field(default=0.5, gt=0, le=1.0)
    max_notional_usd: float = Field(default=10.0, gt=0, le=10.0)
    stop_atr_multiple: float = Field(default=1.5, ge=1.0, le=3.0)
    reward_risk: float = Field(default=2.0, ge=1.0, le=3.0)

def _paper_only_configured() -> bool:
    # Exact allow-list: never permit a live host or arbitrary configured URL.
    return BASE == PAPER_API_ORIGIN

@app.get("/api/paper/status")
async def paper_execution_status():
    return {
        "mode": "paper" if _paper_only_configured() else "blocked",
        "paper_host_verified": _paper_only_configured(),
        "auto_enabled": bool(_auto_entry.get("enabled", False)) if "_auto_entry" in globals() else False,
        "order_submission_enabled": bool(_auto_entry.get("enabled", False)) if "_auto_entry" in globals() else False,
        "protective_exit_support": False,
        "reason": "BTC crypto bracket/OCO exits are not used here. Guarded Paper auto-entry is available only after explicit enable; exits rely on an experimental server-polled manager and are not guaranteed exchange-native protection.",
        "symbol": "BTC/USD"
    }

@app.post("/api/paper/preview")
async def paper_trade_preview(request: PaperPreviewRequest):
    """Calculate a risk-bounded BTC long setup; this endpoint NEVER submits an order."""
    if not _paper_only_configured():
        raise HTTPException(403, "Paper host verification failed; execution preview blocked")
    account_data = await get_json(f"{PAPER_API_ORIGIN}/v2/account")
    equity = float(account_data.get("equity") or 0)
    if equity <= 0:
        raise HTTPException(409, "Paper account equity is unavailable")
    positions_data = await get_json(f"{PAPER_API_ORIGIN}/v2/positions")
    if any(str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD" for p in positions_data):
        raise HTTPException(409, "An existing BTC position is open; no additional entry preview")
    signal_data = await signal(request.timeframe)
    if signal_data.get("signal") != "LONG_SETUP":
        return {
            "approved": False, "signal": signal_data.get("signal", "WAIT"),
            "reason": "No confirmed LONG_SETUP on the selected timeframe",
            "order_submitted": False
        }
    entry = float(signal_data["last_close"])
    volatility = float(signal_data["atr_14"])
    if entry <= 0 or volatility <= 0:
        raise HTTPException(409, "Invalid price or ATR; preview refused")
    stop_distance = volatility * request.stop_atr_multiple
    stop_price = entry - stop_distance
    target_price = entry + stop_distance * request.reward_risk
    risk_budget = equity * request.risk_percent / 100
    risk_sized_notional = risk_budget * entry / stop_distance
    notional = min(request.max_notional_usd, equity * 0.10, risk_sized_notional)
    if stop_price <= 0 or notional < 1:
        raise HTTPException(409, "Risk sizing is too small or stop price invalid")
    return {
        "approved": True,
        "symbol": "BTC/USD",
        "side": "buy",
        "timeframe": request.timeframe,
        "signal": signal_data["signal"],
        "reference_entry_price": round(entry, 2),
        "proposed_stop_price": round(stop_price, 2),
        "proposed_take_profit_price": round(target_price, 2),
        "atr_14": round(volatility, 2),
        "risk_budget_usd": round(risk_budget, 4),
        "proposed_notional_usd": round(notional, 2),
        "max_notional_usd": request.max_notional_usd,
        "account_equity_usd": round(equity, 2),
        "order_submitted": False,
        "execution_status": "PREVIEW_ONLY",
        "warning": "Reference prices can move. Alpaca crypto does not support bracket/OCO exits in this integration, so no order can be submitted safely."
    }


# Server-side protective exit manager.
# It is PAPER-only, starts DISARMED, and only manages an already-open BTC long.
# It never opens positions. Arming is an explicit API action after deployment.
import asyncio
import json
import sqlite3
from pathlib import Path

STATE_DB_PATH = os.getenv("APEX_STATE_DB", "/var/data/apex_state.sqlite3")

def _state_connection():
    path = Path(STATE_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=5)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS runtime_state (state_key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    return connection

def _persist_runtime_state():
    # Store operational context, but always restart with execution disarmed.
    auto_state = {k: v for k, v in _auto_entry.items() if k != "enabled"}
    exit_state = {k: v for k, v in _exit_manager.items() if k != "armed"}
    now = datetime.now(timezone.utc).isoformat()
    with _state_connection() as connection:
        connection.execute(
            "INSERT INTO runtime_state(state_key,payload,updated_at) VALUES(?,?,?) ON CONFLICT(state_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
            ("auto_entry", json.dumps(auto_state), now),
        )
        connection.execute(
            "INSERT INTO runtime_state(state_key,payload,updated_at) VALUES(?,?,?) ON CONFLICT(state_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
            ("exit_manager", json.dumps(exit_state), now),
        )

def _restore_runtime_state():
    try:
        with _state_connection() as connection:
            rows = dict(connection.execute("SELECT state_key,payload FROM runtime_state").fetchall())
        saved_auto = json.loads(rows.get("auto_entry", "{}"))
        saved_exit = json.loads(rows.get("exit_manager", "{}"))
        for key, value in saved_auto.items():
            if key in _auto_entry and key != "enabled":
                _auto_entry[key] = value
        for key, value in saved_exit.items():
            if key in _exit_manager and key != "armed":
                _exit_manager[key] = value
        _auto_entry["enabled"] = False
        _exit_manager["armed"] = False
        if saved_auto or saved_exit:
            _auto_entry["last_event"] = "RESTART_RECOVERY_REQUIRED_EXECUTION_FORCED_OFF"
            _exit_manager["last_event"] = "RESTART_RECOVERY_REQUIRED_EXECUTION_DISARMED"
    except Exception as exc:
        _auto_entry["enabled"] = False
        _exit_manager["armed"] = False
        _auto_entry["last_event"] = "STATE_RESTORE_FAILED_EXECUTION_FORCED_OFF: " + str(exc)[:100]
        _exit_manager["last_event"] = "STATE_RESTORE_FAILED_EXECUTION_DISARMED"

_exit_manager = {
    "armed": False,
    "position_key": None,
    "entry_price": None,
    "stop_price": None,
    "target_price": None,
    "last_price": None,
    "last_check": None,
    "last_event": "DISARMED",
    "close_order_id": None,
}
_exit_task = None
_exit_lock = asyncio.Lock()

async def _paper_request(method: str, path: str, params: dict | None = None, body: dict | None = None):
    if not _paper_only_configured():
        raise HTTPException(403, "Paper host verification failed")
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.request(
            method, f"{PAPER_API_ORIGIN}{path}",
            headers=HEADERS, params=params, json=body
        )
        if response.status_code >= 400:
            raise HTTPException(502, f"Alpaca paper API returned {response.status_code}")
        return response.json() if response.content else {}

async def _exit_manager_tick():
    if not _exit_manager["armed"] or not _paper_only_configured():
        return
    async with _exit_lock:
        positions = await _paper_request("GET", "/v2/positions")
        btc = next((p for p in positions
                    if str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD"), None)
        if not btc:
            _exit_manager.update({
                "position_key": None, "entry_price": None,
                "stop_price": None, "target_price": None,
                "last_event": "NO_OPEN_BTC_POSITION"
            })
            return

        qty = float(btc.get("qty") or 0)
        entry = float(btc.get("avg_entry_price") or 0)
        if str(btc.get("side", "")).lower() != "long":
            _exit_manager["last_event"] = "BLOCKED_NON_LONG_POSITION"
            _exit_manager["armed"] = False
            return
        if qty <= 0 or entry <= 0:
            _exit_manager["last_event"] = "INVALID_POSITION_DATA"
            return

        position_key = f'{btc.get("symbol")}:{btc.get("qty")}:{btc.get("avg_entry_price")}'
        if _exit_manager["position_key"] != position_key:
            bars_data = await get_json(
                f"{DATA}/v1beta3/crypto/us/bars",
                {"symbols": "BTC/USD", "timeframe": "5Min", "limit": 100, "sort": "desc"}
            )
            bars = list(reversed(bars_data.get("bars", {}).get("BTC/USD", [])))
            volatility = atr(bars, 14)
            if not volatility or volatility <= 0:
                _exit_manager["last_event"] = "WAITING_FOR_VALID_ATR"
                return
            distance = volatility * 1.5
            _exit_manager.update({
                "position_key": position_key,
                "entry_price": entry,
                "stop_price": round(entry - distance, 2),
                "target_price": round(entry + distance * 2.0, 2),
                "last_event": "PROTECTIVE_LEVELS_INITIALIZED"
            })

        trade = await get_json(
            f"{DATA}/v1beta3/crypto/us/latest/trades",
            {"symbols": "BTC/USD"}
        )
        latest = trade.get("trades", {}).get("BTC/USD")
        price = float(latest.get("p")) if latest and latest.get("p") is not None else 0
        _exit_manager["last_price"] = price or None
        checked_at = datetime.now(timezone.utc)
        _exit_manager["last_check"] = checked_at.isoformat()
        if price <= 0:
            _exit_manager["last_event"] = "WAITING_FOR_VALID_MARKET_PRICE"
            return
        try:
            trade_time = datetime.fromisoformat(str(latest.get("t")).replace("Z", "+00:00"))
            trade_age = (checked_at - trade_time).total_seconds()
        except (TypeError, ValueError):
            trade_age = float("inf")
        if trade_age < -30 or trade_age > 30:
            _exit_manager["last_event"] = "BLOCKED_STALE_OR_FUTURE_MARKET_TRADE"
            return

        stop = float(_exit_manager.get("stop_price") or 0)
        target = float(_exit_manager.get("target_price") or 0)
        if stop <= 0 or target <= 0 or not (stop < entry < target):
            _exit_manager["last_event"] = "BLOCKED_INVALID_PROTECTIVE_LEVELS"
            _exit_manager["armed"] = False
            return

        reason = None
        if price <= stop:
            reason = "STOP_LOSS_TRIGGERED"
        elif price >= target:
            reason = "TAKE_PROFIT_TRIGGERED"

        if reason:
            # Disarm BEFORE the broker write so a timeout/restart cannot cause
            # repeated close requests on every five-second poll.
            _exit_manager["armed"] = False
            _exit_manager["last_event"] = reason + "_CLOSE_REQUEST_IN_FLIGHT"
            try:
                result = await _paper_request("DELETE", "/v2/positions/BTCUSD")
                _exit_manager["close_order_id"] = result.get("id")
                # Acceptance is not proof of a flat position. Reconcile broker state.
                remaining = await _paper_request("GET", "/v2/positions")
                still_open = next((p for p in remaining
                    if str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD"), None)
                if still_open:
                    _exit_manager["last_event"] = reason + "_CLOSE_ACCEPTED_POSITION_STILL_OPEN_REQUIRES_INSPECTION"
                else:
                    _exit_manager["last_event"] = reason + "_POSITION_CLOSED_CONFIRMED"
            except Exception:
                _exit_manager["last_event"] = reason + "_CLOSE_REQUEST_FAILED_INSPECT_BROKER"
                raise

async def _exit_manager_loop():
    while True:
        try:
            await _exit_manager_tick()
            await _auto_entry_tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _exit_manager["last_event"] = "ERROR: " + str(exc)[:180]
        finally:
            try:
                _persist_runtime_state()
            except Exception as exc:
                _exit_manager["last_event"] = "STATE_PERSISTENCE_ERROR: " + str(exc)[:120]
                _auto_entry["enabled"] = False
                _exit_manager["armed"] = False
        await asyncio.sleep(5)

@app.on_event("startup")
async def start_exit_manager():
    global _exit_task
    _restore_runtime_state()
    # A restart never re-arms execution. Restored state is informational only.
    if _paper_only_configured() and KEY and SECRET:
        try:
            positions = await _paper_request("GET", "/v2/positions")
            btc = next((p for p in positions
                        if str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD"), None)
            if btc:
                _exit_manager["last_event"] = "RESTART_RECOVERY_REQUIRED_EXISTING_BTC_POSITION"
        except Exception as exc:
            _exit_manager["last_event"] = "STARTUP_RECONCILIATION_FAILED: " + str(exc)[:120]
    _exit_task = asyncio.create_task(_exit_manager_loop())

@app.on_event("shutdown")
async def stop_exit_manager():
    global _exit_task
    if _exit_task:
        _exit_task.cancel()
        try:
            await _exit_task
        except asyncio.CancelledError:
            pass
        _exit_task = None

@app.get("/api/paper/exit-manager")
async def paper_exit_manager_status():
    return {
        "mode": "paper" if _paper_only_configured() else "blocked",
        "symbol": "BTC/USD",
        "armed": _exit_manager["armed"],
        "opens_positions": False,
        "poll_interval_seconds": 5,
        "stop_price": _exit_manager["stop_price"],
        "take_profit_price": _exit_manager["target_price"],
        "last_price": _exit_manager["last_price"],
        "last_check": _exit_manager["last_check"],
        "last_event": _exit_manager["last_event"],
        "close_order_id": _exit_manager["close_order_id"],
        "warning": "Server polling is not a guaranteed exchange-native stop. It depends on Render uptime, network access and market data; gaps/slippage are possible."
    }

@app.post("/api/paper/exit-manager/arm")
async def arm_paper_exit_manager():
    if not _paper_only_configured():
        raise HTTPException(403, "Only the exact Alpaca Paper API host is allowed")
    positions = await _paper_request("GET", "/v2/positions")
    btc = next((p for p in positions
                if str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD"), None)
    if not btc:
        raise HTTPException(409, "No open BTC paper position to protect")
    _exit_manager.update({
        "armed": True, "position_key": None,
        "entry_price": None, "stop_price": None, "target_price": None,
        "last_event": "ARMED_WAITING_FOR_PROTECTIVE_LEVELS",
        "close_order_id": None
    })
    return await paper_exit_manager_status()

@app.post("/api/paper/exit-manager/disarm")
async def disarm_paper_exit_manager():
    _exit_manager["armed"] = False
    _exit_manager["last_event"] = "DISARMED_BY_USER"
    return await paper_exit_manager_status()


class ExitSimulationRequest(BaseModel):
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    take_profit_price: float = Field(gt=0)
    simulated_price: float = Field(gt=0)

def evaluate_exit_simulation(entry: float, stop: float, target: float, price: float) -> dict:
    if not (stop < entry < target):
        raise ValueError("Expected a long setup with stop < entry < target")
    if price <= stop:
        event = "STOP_LOSS_TRIGGERED"
    elif price >= target:
        event = "TAKE_PROFIT_TRIGGERED"
    else:
        event = "HOLD_POSITION"
    return {
        "event": event,
        "would_request_paper_close": event != "HOLD_POSITION",
        "order_submitted": False,
        "manager_state_changed": False
    }

@app.post("/api/paper/exit-manager/simulate")
async def simulate_paper_exit(request: ExitSimulationRequest):
    """Pure deterministic test. Does not call Alpaca or change manager state."""
    try:
        result = evaluate_exit_simulation(
            request.entry_price, request.stop_price,
            request.take_profit_price, request.simulated_price
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "mode": "SIMULATION_ONLY",
        "symbol": "BTC/USD",
        "inputs": request.model_dump(),
        **result,
        "safety": "No broker API call; no order submitted; manager remains unchanged."
    }


class PaperLifecycleSimulationRequest(BaseModel):
    entry_price: float = Field(gt=0)
    atr_14: float = Field(gt=0)
    simulated_prices: list[float] = Field(min_length=1, max_length=20)
    notional_usd: float = Field(default=10.0, gt=0, le=10.0)

@app.post("/api/paper/lifecycle/simulate")
async def simulate_paper_trade_lifecycle(request: PaperLifecycleSimulationRequest):
    """Simulate entry-to-exit lifecycle in memory only; never contacts Alpaca."""
    entry = float(request.entry_price)
    stop = round(entry - 1.5 * float(request.atr_14), 2)
    target = round(entry + (1.5 * float(request.atr_14) * 2.0), 2)
    if stop <= 0:
        raise HTTPException(422, "ATR is too large for a valid positive stop price")
    prices = [float(p) for p in request.simulated_prices]
    if any(p <= 0 for p in prices):
        raise HTTPException(422, "All simulated prices must be greater than zero")

    trace = [
        {"step": 1, "event": "SIMULATED_ENTRY_CREATED", "price": entry},
        {"step": 2, "event": "SIMULATED_POSITION_DETECTED", "price": entry,
         "quantity_btc": round(float(request.notional_usd) / entry, 8)},
        {"step": 3, "event": "PROTECTIVE_LEVELS_SET", "stop_price": stop,
         "take_profit_price": target},
    ]
    final_event = "POSITION_OPEN_HOLDING"
    closed = False
    for index, price in enumerate(prices, start=4):
        if closed:
            break
        if price <= stop:
            final_event = "SIMULATED_STOP_LOSS_EXIT"
            trace.append({"step": index, "event": final_event, "price": price})
            closed = True
        elif price >= target:
            final_event = "SIMULATED_TAKE_PROFIT_EXIT"
            trace.append({"step": index, "event": final_event, "price": price})
            closed = True
        else:
            trace.append({"step": index, "event": "HOLD_POSITION", "price": price})

    if closed:
        trace.append({"step": len(trace) + 1, "event": "SIMULATED_POSITION_CLOSED"})
    return {
        "mode": "SIMULATION_ONLY",
        "symbol": "BTC/USD",
        "entry_price": entry,
        "notional_usd": float(request.notional_usd),
        "stop_price": stop,
        "take_profit_price": target,
        "final_event": final_event,
        "position_closed_in_simulation": closed,
        "trace": trace,
        "order_submitted": False,
        "alpaca_api_called": False,
        "live_or_paper_positions_changed": False,
        "exit_manager_state_changed": False,
        "safety": "Entire lifecycle is simulated in memory. No Alpaca API call and no order submission."
    }


# Paper-only automatic entry controller. It is OFF after every server restart.
# Daily trade count is unlimited; risk, exposure, cooldown and daily-loss guards remain.
_auto_entry = {
    "enabled": False, "mode": "paper", "timeframe": "5Min",
    "risk_fraction": 0.005, "max_notional_usd": 10.0,
    "max_equity_fraction": 0.10, "daily_loss_limit_fraction": 0.02,
    "cooldown_seconds": 900, "day_key": None, "day_start_equity": None,
    "last_entry_attempt": None, "last_signal_bar": None,
    "last_event": "DISABLED", "last_order_id": None,
    "last_order_status": None, "trades_today": 0,
}
_auto_entry_lock = asyncio.Lock()

def _utc_day_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()

async def _auto_entry_tick():
    if not _auto_entry["enabled"] or not _paper_only_configured():
        return
    async with _auto_entry_lock:
        try:
            day_key = _utc_day_key()
            account = await _paper_request("GET", "/v2/account")
            equity = float(account.get("equity") or 0)
            if equity <= 0:
                _auto_entry["last_event"] = "BLOCKED_INVALID_EQUITY"
                return
            if _auto_entry["day_key"] != day_key:
                _auto_entry.update({"day_key": day_key, "day_start_equity": equity, "trades_today": 0})
            day_start = float(_auto_entry.get("day_start_equity") or equity)
            if equity <= day_start * (1 - _auto_entry["daily_loss_limit_fraction"]):
                _auto_entry.update({"enabled": False, "last_event": "AUTO_DISABLED_DAILY_LOSS_LIMIT"})
                return

            positions = await _paper_request("GET", "/v2/positions")
            btc = next((p for p in positions if str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD"), None)
            if btc:
                # Fail closed on partial fills or residual entry orders. Do not
                # manage a position while an entry order may still be filling.
                pending_orders = await _paper_request("GET", "/v2/orders", {"status": "open", "limit": 100})
                if any(str(o.get("symbol", "")).replace("/", "").upper() == "BTCUSD" for o in pending_orders):
                    _auto_entry["last_event"] = "PARTIAL_FILL_OR_OPEN_ORDER_REQUIRES_RECONCILIATION"
                    _auto_entry["enabled"] = False
                    return
                if not _exit_manager["armed"]:
                    _exit_manager.update({
                        "armed": True, "position_key": None, "entry_price": None,
                        "stop_price": None, "target_price": None,
                        "last_event": "AUTO_ARMED_FOR_EXISTING_BTC_POSITION", "close_order_id": None
                    })
                _auto_entry["last_event"] = "POSITION_OPEN_EXIT_MANAGER_ACTIVE"
                return

            open_orders = await _paper_request("GET", "/v2/orders", {"status": "open", "limit": 100})
            if any(str(o.get("symbol", "")).replace("/", "").upper() == "BTCUSD" for o in open_orders):
                _auto_entry["last_event"] = "WAITING_FOR_EXISTING_BTC_ORDER"
                return

            now = datetime.now(timezone.utc)
            last_attempt = _auto_entry.get("last_entry_attempt")
            if last_attempt and (now - datetime.fromisoformat(last_attempt)).total_seconds() < _auto_entry["cooldown_seconds"]:
                _auto_entry["last_event"] = "COOLDOWN_ACTIVE"
                return

            signal_data = await signal("5Min")
            bar_time = signal_data.get("last_bar_time")
            if signal_data.get("signal") != "LONG_SETUP":
                _auto_entry["last_event"] = "NO_CONFIRMED_LONG_SETUP"
                return
            if not bar_time or bar_time == _auto_entry.get("last_signal_bar"):
                _auto_entry["last_event"] = "WAITING_FOR_NEW_5MIN_CANDLE"
                return
            # Fail closed on stale/future market bars. Do not trade a delayed feed.
            try:
                bar_dt = datetime.fromisoformat(str(bar_time).replace("Z", "+00:00"))
                bar_age = (datetime.now(timezone.utc) - bar_dt).total_seconds()
            except (TypeError, ValueError):
                _auto_entry["last_event"] = "BLOCKED_INVALID_SIGNAL_TIMESTAMP"
                return
            if bar_age < -30 or bar_age > 600:
                _auto_entry["last_event"] = "BLOCKED_STALE_SIGNAL_BAR"
                return

            quote_data = await get_json(f"{DATA}/v1beta3/crypto/us/latest/quotes", {"symbols": "BTC/USD"})
            quote = quote_data.get("quotes", {}).get("BTC/USD", {})
            reference_price = float(quote.get("ap") or 0)
            quote_time = quote.get("t")
            try:
                quote_age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(quote_time).replace("Z", "+00:00"))).total_seconds()
            except (TypeError, ValueError):
                quote_age = float("inf")
            if quote_age < -30 or quote_age > 30:
                _auto_entry["last_event"] = "BLOCKED_STALE_OR_MISSING_QUOTE"
                return
            if reference_price <= 0:
                trade_data = await get_json(f"{DATA}/v1beta3/crypto/us/latest/trades", {"symbols": "BTC/USD"})
                reference_price = float(trade_data.get("trades", {}).get("BTC/USD", {}).get("p") or 0)
            volatility = float(signal_data.get("atr_14") or 0)
            if reference_price <= 0 or volatility <= 0:
                _auto_entry["last_event"] = "BLOCKED_INVALID_PRICE_OR_ATR"
                return

            stop_distance = volatility * 1.5
            stop_price = reference_price - stop_distance
            risk_budget = equity * _auto_entry["risk_fraction"]
            risk_sized_notional = risk_budget * reference_price / stop_distance
            notional = min(_auto_entry["max_notional_usd"], equity * _auto_entry["max_equity_fraction"], risk_sized_notional)
            if stop_price <= 0 or notional < 1.0:
                _auto_entry["last_event"] = "BLOCKED_RISK_SIZE_BELOW_MINIMUM"
                _auto_entry["last_signal_bar"] = bar_time
                return

            quantity = round(notional / reference_price, 8)
            if quantity <= 0:
                _auto_entry["last_event"] = "BLOCKED_INVALID_ORDER_QUANTITY"
                return

            _auto_entry["last_entry_attempt"] = now.isoformat()
            _auto_entry["last_signal_bar"] = bar_time
            _auto_entry["last_event"] = "PAPER_ENTRY_SUBMITTING"
            order = await _paper_request("POST", "/v2/orders", body={
                "symbol": "BTC/USD", "qty": f"{quantity:.8f}",
                "side": "buy", "type": "market", "time_in_force": "gtc"
            })
            _auto_entry.update({
                "last_order_id": order.get("id"),
                "last_order_status": order.get("status"),
                "last_event": "PAPER_ENTRY_ORDER_SUBMITTED",
                "trades_today": int(_auto_entry["trades_today"]) + 1
            })
        except Exception as exc:
            _auto_entry["last_event"] = "ERROR: " + str(exc)[:180]

@app.get("/api/paper/auto-entry")
async def auto_entry_status():
    return {
        **_auto_entry,
        "mode": "paper" if _paper_only_configured() else "blocked",
        "daily_trade_count_limit": None,
        "one_open_btc_position_max": True,
        "order_submission_enabled": bool(_auto_entry["enabled"] and _paper_only_configured()),
        "warning": "Paper-only. Auto Entry is OFF by default and resets OFF after server restart. Software-polled exits are not guaranteed exchange-native protection."
    }

@app.post("/api/paper/auto-entry/enable")
async def enable_auto_entry():
    if not _paper_only_configured():
        raise HTTPException(403, "Only the exact Alpaca Paper API host is allowed")
    account = await _paper_request("GET", "/v2/account")
    equity = float(account.get("equity") or 0)
    if equity <= 0:
        raise HTTPException(409, "Paper account equity is unavailable")
    positions = await _paper_request("GET", "/v2/positions")
    if any(str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD" for p in positions):
        raise HTTPException(409, "Existing BTC Paper position found; inspect it before enabling Auto Entry")
    _auto_entry.update({
        "enabled": True, "day_key": _utc_day_key(), "day_start_equity": equity,
        "last_entry_attempt": None, "last_signal_bar": None,
        "last_event": "ENABLED_WAITING_FOR_CONFIRMED_LONG_SETUP",
        "last_order_id": None, "last_order_status": None, "trades_today": 0
    })
    return await auto_entry_status()

@app.post("/api/paper/auto-entry/disable")
async def disable_auto_entry():
    _auto_entry["enabled"] = False
    _auto_entry["last_event"] = "DISABLED_BY_USER"
    return await auto_entry_status()


@app.get("/api/paper/auto-entry/dry-run")
async def auto_entry_dry_run():
    """Read-only preflight of Auto Entry eligibility. Never submits orders or mutates state."""
    if not _paper_only_configured():
        raise HTTPException(403, "Only the exact Alpaca Paper API host is allowed")
    account = await _paper_request("GET", "/v2/account")
    equity = float(account.get("equity") or 0)
    buying_power = float(account.get("buying_power") or 0)
    positions = await _paper_request("GET", "/v2/positions")
    btc_position = next((p for p in positions if str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD"), None)
    orders = await _paper_request("GET", "/v2/orders", {"status": "open", "limit": 100})
    btc_order = next((o for o in orders if str(o.get("symbol", "")).replace("/", "").upper() == "BTCUSD"), None)
    signal_data = await signal("5Min")
    quote_data = await get_json(f"{DATA}/v1beta3/crypto/us/latest/quotes", {"symbols": "BTC/USD"})
    quote = quote_data.get("quotes", {}).get("BTC/USD", {})
    ask = float(quote.get("ap") or 0)
    quote_time = quote.get("t")
    quote_fresh = False
    quote_age = None
    try:
        quote_age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(quote_time).replace("Z", "+00:00"))).total_seconds()
        quote_fresh = -30 <= quote_age <= 30
    except (TypeError, ValueError):
        pass
    volatility = float(signal_data.get("atr_14") or 0)

    checks = []
    def add_check(name: str, passed: bool, detail: str):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    add_check("paper_host", _paper_only_configured(), "Exact Alpaca Paper API host allow-list")
    add_check("account_equity", equity > 0, f"Equity USD {equity:.2f}")
    add_check("buying_power", buying_power > 0, f"Buying power USD {buying_power:.2f}")
    add_check("no_existing_btc_position", btc_position is None, "No open BTC position" if btc_position is None else "BTC position already open")
    add_check("no_existing_btc_order", btc_order is None, "No open BTC order" if btc_order is None else "Open BTC order already exists")
    add_check("long_signal", signal_data.get("signal") == "LONG_SETUP", f"Signal: {signal_data.get('signal', 'UNKNOWN')}")
    add_check("valid_ask", ask > 0, f"Latest ask USD {ask:.2f}")
    add_check("fresh_quote", quote_fresh, f"Quote age {quote_age:.1f}s" if quote_age is not None else "Missing or invalid quote timestamp")
    add_check("valid_atr", volatility > 0, f"ATR(14) USD {volatility:.2f}")

    bar_time = signal_data.get("last_bar_time")
    same_bar = bool(bar_time and bar_time == _auto_entry.get("last_signal_bar"))
    add_check("new_signal_bar", not same_bar and bool(bar_time), "New M5 candle" if not same_bar and bar_time else "Missing or already processed M5 candle")
    bar_fresh = False
    bar_age = None
    try:
        bar_dt = datetime.fromisoformat(str(bar_time).replace("Z", "+00:00"))
        bar_age = (datetime.now(timezone.utc) - bar_dt).total_seconds()
        bar_fresh = -30 <= bar_age <= 600
    except (TypeError, ValueError):
        pass
    add_check("fresh_signal_bar", bar_fresh, f"Signal candle age {bar_age:.0f}s" if bar_age is not None else "Invalid or missing candle timestamp")

    cooldown_ok = True
    last_attempt = _auto_entry.get("last_entry_attempt")
    if last_attempt:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_attempt)).total_seconds()
        cooldown_ok = elapsed >= _auto_entry["cooldown_seconds"]
    add_check("cooldown", cooldown_ok, "Cooldown complete" if cooldown_ok else "15-minute cooldown still active")

    daily_baseline = _auto_entry.get("day_start_equity")
    daily_loss_known = daily_baseline is not None
    daily_loss_ok = True
    if daily_loss_known and equity > 0:
        daily_loss_ok = equity > float(daily_baseline) * (1 - _auto_entry["daily_loss_limit_fraction"])
    add_check("daily_loss_guard", daily_loss_ok, "Within 2% daily loss limit" if daily_loss_known else "Baseline not initialized while Auto Entry is OFF; will initialize on enable")

    stop_distance = volatility * 1.5
    stop_price = ask - stop_distance if ask > 0 and volatility > 0 else 0
    risk_budget = equity * _auto_entry["risk_fraction"] if equity > 0 else 0
    risk_notional = risk_budget * ask / stop_distance if ask > 0 and stop_distance > 0 else 0
    notional = min(_auto_entry["max_notional_usd"], equity * _auto_entry["max_equity_fraction"], risk_notional) if equity > 0 else 0
    if buying_power > 0:
        notional = min(notional, buying_power)
    add_check("valid_stop", stop_price > 0, f"Calculated stop USD {stop_price:.2f}")
    add_check("minimum_order_size", notional >= 1.0, f"Risk-sized notional USD {notional:.2f}; minimum USD 1.00")

    eligible = all(item["passed"] for item in checks)
    return {
        "mode": "PAPER_DRY_RUN",
        "result": "ENTRY_ELIGIBLE" if eligible else "ENTRY_BLOCKED",
        "auto_entry_enabled": bool(_auto_entry["enabled"]),
        "signal": signal_data.get("signal"),
        "timeframe": "5Min",
        "last_bar_time": bar_time,
        "reference_ask": round(ask, 2) if ask else None,
        "atr_14": round(volatility, 2) if volatility else None,
        "proposed_notional_usd": round(notional, 2),
        "proposed_quantity_btc": round(notional / ask, 8) if ask > 0 else 0,
        "proposed_stop_price": round(stop_price, 2) if stop_price > 0 else None,
        "proposed_take_profit_price": round(ask + stop_distance * 2, 2) if ask > 0 and stop_distance > 0 else None,
        "checks": checks,
        "order_submitted": False,
        "alpaca_write_api_called": False,
        "auto_entry_state_changed": False,
        "exit_manager_state_changed": False,
        "safety": "Read-only preflight. Uses market/account reads only; no order submission."
    }


# Stage 5: read-only Paper operations validation.
# This endpoint reconciles broker-visible state but deliberately performs GETs only.
@app.get("/api/paper/validation")
async def paper_validation_report():
    if not _paper_only_configured():
        raise HTTPException(403, "Only the exact Alpaca Paper API host is allowed")

    account = await _paper_request("GET", "/v2/account")
    positions = await _paper_request("GET", "/v2/positions")
    open_orders = await _paper_request("GET", "/v2/orders", {"status": "open", "limit": 100})
    btc_positions = [
        item for item in positions
        if str(item.get("symbol", "")).replace("/", "").upper() == "BTCUSD"
    ]
    btc_orders = [
        item for item in open_orders
        if str(item.get("symbol", "")).replace("/", "").upper() == "BTCUSD"
    ]

    equity = float(account.get("equity") or 0)
    checks = [
        {"check": "paper_host_verified", "passed": _paper_only_configured()},
        {"check": "paper_account_active", "passed": str(account.get("status", "")).lower() == "active"},
        {"check": "positive_equity", "passed": equity > 0},
        {"check": "auto_entry_off", "passed": not bool(_auto_entry.get("enabled"))},
        {"check": "exit_manager_disarmed", "passed": not bool(_exit_manager.get("armed"))},
        {"check": "no_open_btc_orders", "passed": len(btc_orders) == 0},
        {"check": "no_open_btc_positions", "passed": len(btc_positions) == 0},
    ]
    passed = sum(1 for item in checks if item["passed"])
    return {
        "stage": 5,
        "mode": "PAPER_READ_ONLY_VALIDATION",
        "result": "CLEAN" if passed == len(checks) else "REQUIRES_REVIEW",
        "checks_passed": passed,
        "checks_total": len(checks),
        "checks": checks,
        "account": {
            "status": account.get("status"),
            "currency": account.get("currency"),
            "equity": account.get("equity"),
            "buying_power": account.get("buying_power"),
        },
        "btc_open_positions": len(btc_positions),
        "btc_open_orders": len(btc_orders),
        "auto_entry_enabled": bool(_auto_entry.get("enabled")),
        "exit_manager_armed": bool(_exit_manager.get("armed")),
        "broker_write_api_called": False,
        "order_submitted": False,
        "note": "Read-only snapshot only. A clean report is not proof of successful fills, protective exits, restart recovery, or profitability."
    }


# Stage 6: readiness assessment only. No live broker adapter or live order route exists.
@app.get("/api/live/readiness")
async def live_trading_readiness():
    gates = [
        {"gate": "strategy_validation", "passed": False, "detail": "Stage 4 strategy validation remains open; current tested strategy results are not profitable."},
        {"gate": "paper_lifecycle_evidence", "passed": False, "detail": "Controlled Paper entry/fill/partial-fill/rejection/exit/restart evidence is not complete."},
        {"gate": "exchange_native_protection", "passed": False, "detail": "This integration does not provide verified exchange-native BTC protective orders."},
        {"gate": "live_broker_adapter", "passed": False, "detail": "No live broker adapter or live order submission endpoint is implemented."},
        {"gate": "production_security_and_monitoring", "passed": False, "detail": "Production identity, secret rotation, alerting, and operational controls require independent review."},
        {"gate": "explicit_live_authorization", "passed": False, "detail": "No explicit authorization to enable real-money execution has been given."},
    ]
    return {
        "stage": 6,
        "mode": "READINESS_ASSESSMENT_ONLY",
        "live_trading_supported": False,
        "live_orders_enabled": False,
        "result": "NOT_READY",
        "gates_passed": sum(1 for item in gates if item["passed"]),
        "gates_total": len(gates),
        "gates": gates,
        "paper_auto_entry_enabled": bool(_auto_entry.get("enabled")),
        "paper_exit_manager_armed": bool(_exit_manager.get("armed")),
        "order_submitted": False,
        "note": "This endpoint is informational and never connects to a live broker or submits orders."
    }
