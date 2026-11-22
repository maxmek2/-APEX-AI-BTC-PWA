import os
import math
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

try:
    from .stage43 import build_breakout_signals, run_breakout_backtest
    from .stage44 import run_stage44_report, build_stage44_signals
    from .stage45 import run_stage45_report
    from .stage46 import run_stage46_report
    from .stage47 import run_stage47_report
    from .stage48 import run_stage48_report
    from .stage53 import run_stage53_report
    from .stage54 import run_stage54_report
    from .stage55 import run_stage55_report
    from .stage56 import run_stage56_failure_report
    from .stage57 import run_stage57_candidate_report
    from .stage58 import run_stage58_execution_diagnostics
    from .stage59 import run_stage59_accounting_audit
    from .stage510 import run_stage510_cost_edge_diagnostics
    from .stage511 import run_stage511_stop_loss_diagnostics
    from .stage512 import run_stage512_entry_quality_diagnostics
    from .stage513 import run_stage513_temporal_stability_audit
    from .stage514 import run_stage514_strategy_decision_gate
    from .stage515 import run_stage515_loss_concentration_investigation
    from .stage516 import run_stage516_trade_path_diagnostics
    from .stage517 import run_stage517_log_backtest
except ImportError:  # uvicorn main:app with backend as app-dir
    from stage43 import build_breakout_signals, run_breakout_backtest
    from stage44 import run_stage44_report, build_stage44_signals
    from stage45 import run_stage45_report
    from stage46 import run_stage46_report
    from stage47 import run_stage47_report
    from stage48 import run_stage48_report
    from stage53 import run_stage53_report
    from stage54 import run_stage54_report
    from stage55 import run_stage55_report
    from stage56 import run_stage56_failure_report
    from stage57 import run_stage57_candidate_report
    from stage58 import run_stage58_execution_diagnostics
    from stage59 import run_stage59_accounting_audit
    from stage510 import run_stage510_cost_edge_diagnostics
    from stage511 import run_stage511_stop_loss_diagnostics
    from stage512 import run_stage512_entry_quality_diagnostics
    from stage513 import run_stage513_temporal_stability_audit
    from stage514 import run_stage514_strategy_decision_gate
    from stage515 import run_stage515_loss_concentration_investigation
    from stage516 import run_stage516_trade_path_diagnostics
    from stage517 import run_stage517_log_backtest

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
    protected_read_paths = {"/api/account", "/api/positions"}
    requires_token = request.url.path.startswith("/api/paper/") or request.url.path in protected_read_paths
    if requires_token and request.method != "OPTIONS":
        expected = os.getenv("APEX_API_TOKEN", "").strip()
        if not expected:
            return JSONResponse(status_code=503, content={"detail": "Paper API locked: configure APEX_API_TOKEN on the backend"})
        supplied = request.headers.get("authorization", "")
        scheme, _, token = supplied.partition(" ")
        if scheme.lower() != "bearer" or not token or not secrets.compare_digest(token, expected):
            return JSONResponse(status_code=401, content={"detail": "Valid Bearer token required"})
    response = await call_next(request)
    if requires_token:
        response.headers["Cache-Control"] = "no-store, private"
    return response

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

def _completed_bars(bars: list[dict], timeframe: str, now: datetime | None = None) -> list[dict]:
    """Keep only candles whose full interval has elapsed; avoid intrabar signals."""
    seconds = {"1Min": 60, "5Min": 300, "15Min": 900, "1Hour": 3600}[timeframe]
    current = now or datetime.now(timezone.utc)
    completed = []
    for bar in bars:
        try:
            stamp = datetime.fromisoformat(str(bar.get("t")).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp + timedelta(seconds=seconds) <= current:
                completed.append(bar)
        except (TypeError, ValueError):
            continue
    return completed


@app.get("/api/signal")
async def signal(timeframe:str=Query("5Min",pattern="^(1Min|5Min|15Min|1Hour)$")):
    data=await get_json(
        f"{DATA}/v1beta3/crypto/us/bars",
        {"symbols":"BTC/USD","timeframe":timeframe,"limit":100,"sort":"desc"}
    )
    bars=data.get("bars",{}).get("BTC/USD",[])
    bars=list(reversed(bars))  # Keep candles chronological after fetching newest first.
    bars=_completed_bars(bars, timeframe)
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
                         slippage_bps: float = 0.0, start_index: int = 21,
                         fast_period: int = 9, slow_period: int = 21,
                         stop_atr_multiple: float = 1.5,
                         reward_risk: float = 2.0,
                         entry_filter: list[bool] | None = None) -> dict:
    """Deterministic long-only close-signal/next-open-fill OHLC backtest.

    Fees apply to executed notional on entry and exit. Slippage is an adverse
    percentage of price on both sides, expressed in basis points.
    """
    if len(bars) < 50:
        raise ValueError("At least 50 candles are required")
    if (not isinstance(fast_period, int) or not isinstance(slow_period, int)
            or fast_period < 2 or slow_period <= fast_period or slow_period > 200):
        raise ValueError("EMA periods must be integers with 2 <= fast < slow <= 200")
    if stop_atr_multiple <= 0 or reward_risk <= 0:
        raise ValueError("ATR stop multiple and reward/risk must be positive")
    if not isinstance(start_index, int) or start_index < slow_period or start_index >= len(bars) - 1:
        raise ValueError("start_index must be an integer from slow_period through len(bars)-2")
    if entry_filter is not None and len(entry_filter) != len(bars):
        raise ValueError("entry_filter length must match bars")
    if starting_equity <= 0 or notional_usd <= 0 or fee_rate < 0 or slippage_bps < 0:
        raise ValueError("Equity/notional must be positive; fee and slippage must be non-negative")
    slip = slippage_bps / 10000.0
    if slip >= 1:
        raise ValueError("Slippage must be below 10000 basis points")
    closes = [float(item["c"]) for item in bars]
    fast, slow, volatility = ema_series(closes, fast_period), ema_series(closes, slow_period), atr_series(bars, 14)
    position, trades = None, []

    def close_position(candle: dict, exit_price: float, reason: str) -> None:
        nonlocal position
        entry, quantity = float(position["entry"]), float(position["quantity"])
        executed_exit = exit_price * (1.0 - slip)
        gross = (executed_exit - entry) * quantity
        fees = (entry * quantity + executed_exit * quantity) * fee_rate
        slippage_cost = (entry - float(position["reference_entry"])) * quantity + (exit_price - executed_exit) * quantity
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
    # Indicators retain their full pre-test warm-up history, while entries
    # are permitted only from start_index onward. This supports honest
    # chronological out-of-sample evaluation without indicator look-ahead.
    for i in range(start_index, len(bars)-1):
        if position is not None:
            hit = _backtest_exit_for_candle(position, bars[i])
            if hit:
                close_position(bars[i], hit[0], hit[1])
            continue
        a = volatility[i]
        if (fast[i] is None or slow[i] is None or a is None or a <= 0
                or not (fast[i] > slow[i] and closes[i] > fast[i])
                or (entry_filter is not None and not entry_filter[i])):
            continue
        entry_bar = bars[i+1]
        reference_entry = float(entry_bar["o"])
        if reference_entry <= 0:
            continue
        entry = reference_entry * (1.0 + slip)
        position = {"entry": entry, "reference_entry": reference_entry,
                    "quantity": notional_usd/entry,
                    "stop": entry-stop_atr_multiple*a, "target": entry+stop_atr_multiple*reward_risk*a,
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


@app.get("/api/backtest/walk-forward")
async def walk_forward_backtest(
    timeframe: str = Query("5Min", pattern="^(1Min|5Min|15Min|1Hour)$"),
    limit: int = Query(2000, ge=300, le=10000),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
    train_fraction: float = Query(0.70, ge=0.60, le=0.80),
):
    """Chronological fixed-strategy train/test report; never submits orders."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 300:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 300,
            "automated_execution": False, "order_submitted": False,
        }
    split = int(len(bars) * train_fraction)
    if split < 100 or len(bars) - split < 50:
        raise HTTPException(422, "Insufficient candles in chronological train/test segments")
    # Training ends on the split candle. Test signals begin at that candle's
    # close and can only fill on the following candle's open.
    train_bars = bars[:split + 1]
    train = run_ema_atr_backtest(
        train_bars, starting_equity, notional_usd, fee_rate, slippage_bps
    )
    test = run_ema_atr_backtest(
        bars, starting_equity, notional_usd, fee_rate, slippage_bps,
        start_index=split,
    )
    test_entries = [t for t in test["trades"] if t.get("entry_time")]
    first_test_fill = bars[split + 1].get("t")
    leakage_free = all(t["entry_time"] >= first_test_fill for t in test_entries)
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "chronological_fixed_strategy_evaluation",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "split": {
            "method": "chronological", "train_fraction": train_fraction,
            "train_bars": len(train_bars), "test_bars": len(bars) - split - 1,
            "train_from": bars[0].get("t"), "train_to": bars[split].get("t"),
            "test_signal_from": bars[split].get("t"),
            "first_possible_test_fill": first_test_fill,
            "test_to": bars[-1].get("t"),
        },
        "assumptions": {
            "strategy": "Fixed EMA9 > EMA21 and close > EMA9; next-candle-open entry; SL 1.5x ATR14; TP 2.0x ATR14",
            "fee_per_side_percent": fee_rate * 100,
            "slippage_bps_per_side": slippage_bps,
            "same_candle_policy": "STOP_LOSS_FIRST",
            "test_starts_flat": True,
            "parameters_optimized_on_test": False,
        },
        "train_metrics": train["metrics"],
        "out_of_sample_metrics": test["metrics"],
        "checks": {
            "chronological_split": True,
            "test_entries_after_split": leakage_free,
            "test_parameters_untuned": True,
        },
        "interpretation": "Research diagnostic only. One chronological holdout is not proof of robustness; repeat across market regimes and walk-forward windows before considering strategy validation.",
        "automated_execution": False, "order_submitted": False,
        "alpaca_write_api_called": False,
    }


@app.get("/api/backtest/optimize")
async def optimize_backtest(
    timeframe: str = Query("5Min", pattern="^(1Min|5Min|15Min|1Hour)$"),
    limit: int = Query(1000, ge=600, le=10000),
    train_fraction: float = Query(0.60, gt=0.50, lt=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Select fixed strategy parameters on training data; evaluate once on untouched holdout."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 600:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 600,
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }

    split = int(len(bars) * train_fraction)
    if split <= 51 or len(bars) - split < 50:
        raise HTTPException(422, "Insufficient candles for training and untouched holdout")
    candidates = []
    for fast_period, slow_period in ((9, 21), (12, 26), (20, 50)):
        for stop_multiple in (1.5, 2.0):
            for reward_risk in (1.5, 2.0, 2.5):
                train = run_ema_atr_backtest(
                    bars[:split + 1], starting_equity, notional_usd,
                    fee_rate, slippage_bps, start_index=slow_period,
                    fast_period=fast_period, slow_period=slow_period,
                    stop_atr_multiple=stop_multiple, reward_risk=reward_risk,
                )
                candidates.append({
                    "parameters": {
                        "ema_fast": fast_period, "ema_slow": slow_period,
                        "atr_stop_multiple": stop_multiple, "reward_risk": reward_risk,
                    },
                    "training_metrics": train["metrics"],
                })

    eligible = [item for item in candidates if item["training_metrics"]["trades"] >= 1]
    selected = max(
        eligible,
        key=lambda item: item["training_metrics"]["net_pnl_usd"],
    ) if eligible else None

    holdout = None
    cost_sensitivity = []
    boundary_ok = None
    if selected:
        params = selected["parameters"]
        for cost_bps in sorted({0, 5, 10, 20, slippage_bps}):
            test = run_ema_atr_backtest(
                bars, starting_equity, notional_usd, fee_rate, cost_bps,
                start_index=split, fast_period=params["ema_fast"],
                slow_period=params["ema_slow"],
                stop_atr_multiple=params["atr_stop_multiple"],
                reward_risk=params["reward_risk"],
            )
            first_test_fill = bars[split + 1].get("t")
            test_entries = [trade for trade in test["trades"] if trade.get("entry_time")]
            entries_valid = all(
                trade["entry_time"] and trade["entry_time"] >= first_test_fill
                for trade in test_entries
            )
            cost_sensitivity.append({
                "slippage_bps_per_side": cost_bps,
                "metrics": test["metrics"],
                "test_entries_after_split": entries_valid,
            })
            if cost_bps == slippage_bps:
                holdout = test["metrics"]
                boundary_ok = entries_valid

    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "train_selected_untouched_holdout_evaluation",
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "split": {
            "method": "chronological", "train_fraction": train_fraction,
            "training_bars": split + 1, "holdout_bars": len(bars) - split - 1,
            "train_to": bars[split].get("t"),
            "first_possible_holdout_fill": bars[split + 1].get("t"),
            "holdout_to": bars[-1].get("t"),
        },
        "search_space": {
            "candidate_count": len(candidates),
            "ema_pairs": [[9, 21], [12, 26], [20, 50]],
            "atr_stop_multiples": [1.5, 2.0],
            "reward_risk_values": [1.5, 2.0, 2.5],
            "selection_rule": "highest training net PnL among candidates with at least one training trade",
            "holdout_used_for_selection": False,
        },
        "training_candidates": candidates,
        "selected_parameters": selected["parameters"] if selected else None,
        "selected_training_metrics": selected["training_metrics"] if selected else None,
        "untouched_holdout_metrics": holdout,
        "cost_sensitivity": cost_sensitivity,
        "checks": {
            "chronological_split": True,
            "holdout_parameters_untuned": True,
            "holdout_entries_after_split": boundary_ok,
            "candidate_selection_used_training_only": True,
        },
        "limitations": [
            "The small fixed candidate grid can still overfit the training sample; an untouched holdout is not independent future validation.",
            "The selected parameters are not certified profitable; no parameter search can guarantee future results.",
            "Costs are assumptions, not verified broker fees or measured fills.",
            "OHLC bars cannot establish intrabar path; ambiguous stop/target bars assume stop first.",
            "Drawdown is based on closed trades and excludes intratrade mark-to-market drawdown.",
        ],
        "automated_execution": False, "order_submitted": False,
        "alpaca_write_api_called": False,
    }




def rsi_series(values: list[float], period: int = 14) -> list[float | None]:
    """Wilder RSI; each output uses only values at or before its index."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i-1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i-1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)
    out[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        out[i] = value(avg_gain, avg_loss)
    return out


def higher_timeframe_bullish_by_index(
    bars: list[dict], group_minutes: int
) -> list[bool]:
    """Map fully completed 15m/1h EMA9/21 trend candles onto each 5m close.

    Only complete higher-timeframe buckets are eligible. The current partial
    15m/1h candle is never used, preventing intrabar higher-timeframe leakage.
    """
    if group_minutes not in (15, 60):
        raise ValueError("group_minutes must be 15 or 60")
    seconds = group_minutes * 60
    bucket_map: dict[int, dict] = {}
    bucket_counts: dict[int, int] = {}
    base_seconds = 300
    stamps: list[datetime] = []
    for bar in bars:
        stamp = datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamps.append(stamp)
        bucket = int(stamp.timestamp()) // seconds
        item = bucket_map.get(bucket)
        if item is None:
            bucket_map[bucket] = {
                "t": bar["t"], "o": float(bar["o"]), "h": float(bar["h"]),
                "l": float(bar["l"]), "c": float(bar["c"]), "v": float(bar.get("v", 0)),
            }
            bucket_counts[bucket] = 1
        else:
            item["h"] = max(item["h"], float(bar["h"]))
            item["l"] = min(item["l"], float(bar["l"]))
            item["c"] = float(bar["c"])
            item["v"] += float(bar.get("v", 0))
            bucket_counts[bucket] += 1

    complete = sorted(
        (bucket, bucket_map[bucket]) for bucket in bucket_map
        if bucket_counts[bucket] == group_minutes // 5
    )
    closes = [item["c"] for _, item in complete]
    fast, slow = ema_series(closes, 9), ema_series(closes, 21)
    bucket_to_position = {bucket: pos for pos, (bucket, _) in enumerate(complete)}
    result = [False] * len(bars)
    for i, stamp in enumerate(stamps):
        close_ts = int(stamp.timestamp()) + base_seconds
        last_complete_bucket = close_ts // seconds - 1
        pos = bucket_to_position.get(last_complete_bucket)
        if pos is not None and fast[pos] is not None and slow[pos] is not None:
            result[i] = fast[pos] > slow[pos] and closes[pos] > fast[pos]
        else:
            # A previously completed bucket may be available even when the
            # immediately preceding bucket is absent from the fetched sample.
            eligible = [p for b, p in bucket_to_position.items() if b <= last_complete_bucket]
            if eligible:
                p = max(eligible)
                if fast[p] is not None and slow[p] is not None:
                    result[i] = fast[p] > slow[p] and closes[p] > fast[p]
    return result


def build_stage42_filters(bars: list[dict]) -> dict[str, list[bool]]:
    closes = [float(bar["c"]) for bar in bars]
    volatility = atr_series(bars, 14)
    rsi = rsi_series(closes, 14)
    mtf15 = higher_timeframe_bullish_by_index(bars, 15)
    mtf60 = higher_timeframe_bullish_by_index(bars, 60)
    mtf = [mtf15[i] and mtf60[i] for i in range(len(bars))]
    rsi_ok = [value is not None and 50.0 <= value <= 70.0 for value in rsi]
    # Explicit low-volatility/sideways exclusion; threshold is a research
    # hypothesis, not a calibrated or universally valid BTC threshold.
    atr_ok = [
        volatility[i] is not None and closes[i] > 0
        and volatility[i] / closes[i] >= 0.0004
        for i in range(len(bars))
    ]
    return {
        "baseline": [True] * len(bars),
        "mtf_15m_1h": mtf,
        "rsi_50_70": rsi_ok,
        "atr_pct_min_0_04": atr_ok,
        "combined_mtf_rsi_atr": [
            mtf[i] and rsi_ok[i] and atr_ok[i] for i in range(len(bars))
        ],
    }


@app.get("/api/backtest/stage4-2")
async def stage42_filter_research(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(2000, ge=600, le=10000),
    train_fraction: float = Query(0.60, gt=0.50, lt=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Compare predeclared MTF/RSI/ATR entry filters on train and untouched holdout."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 600:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 600,
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }
    split = int(len(bars) * train_fraction)
    if split <= 60 or len(bars) - split < 50:
        raise HTTPException(422, "Insufficient candles for training and untouched holdout")
    filters = build_stage42_filters(bars)
    reports = {}
    for name, mask in filters.items():
        train = run_ema_atr_backtest(
            bars[:split + 1], starting_equity, notional_usd, fee_rate,
            slippage_bps, start_index=50, entry_filter=mask[:split + 1],
        )
        holdout = run_ema_atr_backtest(
            bars, starting_equity, notional_usd, fee_rate, slippage_bps,
            start_index=split, entry_filter=mask,
        )
        first_fill = bars[split + 1].get("t")
        test_entries = [trade for trade in holdout["trades"] if trade.get("entry_time")]
        reports[name] = {
            "training_metrics": train["metrics"],
            "holdout_metrics": holdout["metrics"],
            "holdout_trade_count": len(test_entries),
            "holdout_entries_after_split": all(
                trade["entry_time"] and trade["entry_time"] >= first_fill
                for trade in test_entries
            ),
            "eligible_signal_bars_train": sum(mask[:split + 1]),
            "eligible_signal_bars_holdout": sum(mask[split:]),
        }
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "fixed_filter_comparison_train_and_untouched_holdout",
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "split": {
            "method": "chronological", "train_fraction": train_fraction,
            "training_bars": split + 1, "holdout_bars": len(bars) - split - 1,
            "train_to": bars[split].get("t"),
            "first_possible_holdout_fill": bars[split + 1].get("t"),
            "holdout_to": bars[-1].get("t"),
        },
        "filter_definitions": {
            "baseline": "EMA9 > EMA21 and close > EMA9",
            "mtf_15m_1h": "Baseline plus fully completed 15m and 1h EMA9 > EMA21 and close > EMA9",
            "rsi_50_70": "Baseline plus Wilder RSI14 between 50 and 70 inclusive",
            "atr_pct_min_0_04": "Baseline plus ATR14 / close >= 0.0004; experimental sideways-market exclusion",
            "combined_mtf_rsi_atr": "Baseline plus all three filters",
            "signal_execution": "Signal at 5m candle close; fill at next candle open; long-only",
        },
        "reports": reports,
        "checks": {
            "chronological_split": True,
            "higher_timeframe_uses_completed_candles_only": True,
            "holdout_filters_predeclared_not_optimized": True,
            "holdout_entries_after_split": all(
                item["holdout_entries_after_split"] for item in reports.values()
            ),
        },
        "limitations": [
            "The 15m/1h bars are aggregated from 5m OHLCV and require complete groups; missing 5m candles can reduce higher-timeframe coverage.",
            "The ATR percentage threshold and RSI range are hypotheses, not calibrated settings.",
            "The holdout contains a limited sample and is not independent future validation.",
            "Fees and slippage are assumptions; OHLC ambiguous exits use stop-first; drawdown is closed-trade only.",
            "This is an EMA/RSI/ATR multi-timeframe filter experiment, not a complete ICT implementation.",
        ],
        "automated_execution": False, "order_submitted": False,
        "alpaca_write_api_called": False,
    }





@app.get("/api/backtest/stage4-3")
async def stage43_breakout_research(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(10000, ge=3000, le=10000),
    train_fraction: float = Query(0.60, gt=0.50, lt=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Read-only 15m Donchian breakout + volume + completed 1h trend comparison."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 3000,
            "reason": "At least 200 completed hourly candles plus warm-up are needed for EMA200 trend context.",
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }
    split = int(len(bars) * train_fraction)
    if split < 1000 or len(bars) - split < 100:
        raise HTTPException(422, "Insufficient chronological training or holdout data")
    built = build_breakout_signals(bars, lookback=20)
    masks, atr_by_base = built["signals"], built["atr_by_base"]
    reports = {}
    first_holdout_fill = bars[split + 1].get("t")
    for name, mask in masks.items():
        train = run_breakout_backtest(
            bars[:split + 1], mask[:split + 1], atr_by_base[:split + 1],
            starting_equity, notional_usd, fee_rate, slippage_bps,
        )
        holdout_costs = []
        for cost_bps in sorted({0, 5, 10, 20, slippage_bps}):
            test = run_breakout_backtest(
                bars, mask, atr_by_base, starting_equity, notional_usd,
                fee_rate, cost_bps, start_index=split,
            )
            entries = [trade for trade in test["trades"] if trade.get("entry_time")]
            boundary_ok = all(
                trade["entry_time"] and trade["entry_time"] >= first_holdout_fill
                for trade in entries
            )
            holdout_costs.append({
                "slippage_bps_per_side": cost_bps,
                "metrics": test["metrics"],
                "entries_after_split": boundary_ok,
            })
        selected_cost = next(x for x in holdout_costs if x["slippage_bps_per_side"] == slippage_bps)
        reports[name] = {
            "training_metrics": train["metrics"],
            "holdout_metrics": selected_cost["metrics"],
            "holdout_trade_count": selected_cost["metrics"]["trades"],
            "holdout_entries_after_split": selected_cost["entries_after_split"],
            "cost_sensitivity": holdout_costs,
            "training_signal_count": sum(mask[:split + 1]),
            "holdout_signal_count": sum(mask[split:]),
        }
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "fixed_breakout_variants_train_and_untouched_holdout",
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "split": {
            "method": "chronological", "train_fraction": train_fraction,
            "training_bars": split + 1, "holdout_bars": len(bars) - split - 1,
            "train_to": bars[split].get("t"),
            "first_possible_holdout_fill": first_holdout_fill,
            "holdout_to": bars[-1].get("t"),
        },
        "strategy": {
            "signal_timeframe": "15Min",
            "execution_timeframe": "5Min",
            "trend_timeframe": "1Hour",
            "breakout": "Completed 15m close above the prior 20 completed 15m candle highs; current candle excluded from channel.",
            "volume": "Completed 15m volume greater than the median of the prior 20 completed 15m candles.",
            "trend": "Latest completed 1h EMA50 > EMA200 and close > EMA50.",
            "entry": "Only at completed 15m close; simulated fill at next 5m candle open.",
            "stop": "1.5 x completed 15m ATR14",
            "target": "2.0R",
            "direction": "Long-only, spot-compatible; no shorting.",
        },
        "variant_definitions": {
            "breakout_only": "15m Donchian 20-candle close breakout",
            "breakout_volume": "Breakout plus 15m volume above prior-20 median",
            "breakout_volume_1h": "Breakout plus volume confirmation and completed 1h EMA50/200 bullish trend",
        },
        "aggregation": built["diagnostics"],
        "reports": reports,
        "checks": {
            "chronological_split": True,
            "holdout_parameters_predeclared": True,
            "15m_signals_only_after_candle_close": True,
            "1h_trend_uses_completed_candles_only": True,
            "current_15m_candle_excluded_from_breakout_channel": True,
            "holdout_entries_after_split": all(x["holdout_entries_after_split"] for x in reports.values()),
            "read_only": True,
        },
        "assumptions": {
            "starting_equity_usd": starting_equity,
            "fixed_notional_usd": notional_usd,
            "fee_per_side_percent": fee_rate * 100,
            "slippage_bps_per_side": slippage_bps,
            "ambiguous_ohlc_exit": "STOP_LOSS_FIRST",
            "drawdown": "Closed-trade equity drawdown; intratrade mark-to-market not modelled.",
        },
        "limitations": [
            "Requires at least 200 completed hourly candles for the EMA200 trend context; shorter datasets are rejected.",
            "Alpaca OHLCV volume is venue-reported crypto volume and may not represent the entire BTC market.",
            "A single chronological holdout is not independent future validation; the strategy remains research-only.",
            "Fixed notional, estimated fees and slippage are modelling assumptions, not verified fills or broker fee quotes.",
            "OHLC bars cannot reveal intrabar path; ambiguous stop/target candles use stop-first. Gaps and latency may differ in real execution.",
            "Long-only spot simulation; short-side performance is not evaluated.",
        ],
        "automated_execution": False, "order_submitted": False,
        "alpaca_write_api_called": False,
    }




@app.get("/api/backtest/stage4-4")
async def stage44_pullback_research(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(10000, ge=3000, le=10000),
    train_fraction: float = Query(0.60, gt=0.50, lt=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Read-only Stage 4.4 relative-volume and post-breakout pullback comparison."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {"symbol": "BTC/USD", "status": "insufficient_data",
                "bars_used": len(bars), "minimum_required": 3000,
                "automated_execution": False, "order_submitted": False,
                "alpaca_write_api_called": False}
    try:
        result = run_stage44_report(bars, train_fraction, starting_equity,
                                    notional_usd, fee_rate, slippage_bps)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    split = result["split_index"]
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "stage4_4_fixed_variants_train_and_untouched_holdout",
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "split": {"method": "chronological", "train_fraction": train_fraction,
                  "training_bars": split, "holdout_bars": len(bars) - split,
                  "train_to": bars[split - 1].get("t"),
                  "first_possible_holdout_fill": result["first_possible_holdout_fill"],
                  "holdout_to": bars[-1].get("t")},
        "strategy": {
            "signal_timeframe": "15Min", "execution_timeframe": "5Min",
            "entry": "Completed 15m signal, simulated fill at next 5m open",
            "pullback": "After a completed 15m close breakout, within next four completed 15m candles price must touch within 0.25 ATR of breakout level and close back above that level",
            "relative_volume": "Current completed 15m volume divided by median of prior 20 completed 15m volumes; threshold >= 1.5",
            "hourly_context": "Latest completed 1h EMA20 > EMA50 and close > EMA20; diagnostic comparison to EMA50 > EMA200 retained",
            "stop": "1.5 x completed 15m ATR14", "target": "2.0R",
            "direction": "Long-only, spot-compatible"
        },
        "variant_definitions": {
            "breakout_relvol_1p5": "15m Donchian breakout plus relative volume >= 1.5",
            "breakout_pullback": "Breakout followed by level retest and reclaim within four 15m candles",
            "breakout_pullback_relvol": "Pullback/reclaim plus relative volume >= 1.5 on confirmation candle",
            "breakout_relvol_1p5_1h20_50": "Breakout plus relative volume and completed 1h EMA20/EMA50 bullish context"
        },
        "diagnostics": result["diagnostics"], "reports": result["reports"],
        "checks": {"chronological_split": True, "fixed_predeclared_variants": True,
                   "15m_signals_after_candle_close": True,
                   "pullback_requires_later_completed_15m_candle": True,
                   "1h_context_uses_completed_candles_only": True,
                   "holdout_entries_after_split": all(x["holdout_entries_after_split"] for x in result["reports"].values()),
                   "read_only": True},
        "assumptions": {"starting_equity_usd": starting_equity,
                        "fixed_notional_usd": notional_usd,
                        "fee_per_side_percent": fee_rate * 100,
                        "slippage_bps_per_side": slippage_bps,
                        "ambiguous_ohlc_exit": "STOP_LOSS_FIRST",
                        "drawdown": "Closed-trade equity drawdown; intratrade mark-to-market not modelled."},
        "limitations": [
            "A single chronological holdout is not independent future validation.",
            "Relative volume is based on Alpaca venue-reported BTC/USD volume, not global BTC volume.",
            "Breakout retest logic is a fixed research hypothesis, not a full ICT implementation.",
            "Estimated fees/slippage and fixed notional are assumptions, not verified fills.",
            "OHLC bars cannot reveal intrabar path; ambiguous stop/target candles use stop-first.",
            "Long-only spot simulation; no short-side test."
        ],
        "automated_execution": False, "order_submitted": False,
        "alpaca_write_api_called": False
    }


@app.get("/api/backtest/rolling-oos")
async def rolling_oos_backtest(
    timeframe: str = Query("5Min", pattern="^(1Min|5Min|15Min|1Hour)$"),
    limit: int = Query(1000, ge=600, le=10000),
    windows: int = Query(4, ge=3, le=8),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Sequential, fixed-rule out-of-sample windows; read-only and never submits orders."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 600:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 600,
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }

    first_oos_index = max(21, int(len(bars) * 0.30))
    available = len(bars) - first_oos_index
    window_size = available // windows
    if window_size < 50:
        raise HTTPException(422, "Not enough candles per out-of-sample window")

    reports = []
    for window_index in range(windows):
        start_index = first_oos_index + window_index * window_size
        end_index = (len(bars) - 1 if window_index == windows - 1
                     else first_oos_index + (window_index + 1) * window_size - 1)
        result = run_ema_atr_backtest(
            bars[:end_index + 1], starting_equity, notional_usd,
            fee_rate, slippage_bps, start_index=start_index,
        )
        trades = result["trades"]
        first_fill = bars[start_index + 1].get("t")
        last_time = bars[end_index].get("t")
        boundary_ok = all(
            trade.get("entry_time") and first_fill <= trade["entry_time"] <= last_time
            for trade in trades
        )
        reports.append({
            "window": window_index + 1, "from": first_fill, "to": last_time,
            "bars": end_index - start_index, "metrics": result["metrics"],
            "test_starts_flat": True, "entries_inside_window": boundary_ok,
        })

    all_boundaries_valid = all(item["entries_inside_window"] for item in reports)
    total_trades = sum(item["metrics"]["trades"] for item in reports)
    positive_windows = sum(item["metrics"]["net_pnl_usd"] > 0 for item in reports)
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "rolling_out_of_sample_research",
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "method": {
            "windows": windows, "first_oos_index": first_oos_index,
            "window_size_approx": window_size,
            "chronological_non_overlapping": True,
            "fixed_parameters_no_test_optimization": True,
            "each_window_starts_flat": True,
            "indicator_warmup_uses_prior_bars": True,
            "strategy": "EMA9 > EMA21 and close > EMA9; next-open entry; SL 1.5x ATR14; TP 2.0x ATR14",
            "fee_per_side_percent": fee_rate * 100,
            "adverse_slippage_bps_per_side": slippage_bps,
            "same_candle_policy": "STOP_LOSS_FIRST",
        },
        "summary": {
            "total_trades": total_trades, "positive_windows": positive_windows,
            "windows": windows, "all_windows_positive": positive_windows == windows,
            "all_entry_boundaries_valid": all_boundaries_valid,
        },
        "window_reports": reports,
        "limitations": [
            "OHLC bars cannot establish intrabar execution sequence; ambiguous stop/target bars assume stop first.",
            "Fees and slippage are assumptions, not measured fills or a verified broker fee schedule.",
            "Each window starts flat; this is a segmented research comparison, not one continuous portfolio equity curve.",
            "Positive historical windows do not prove future profitability.",
        ],
        "automated_execution": False, "order_submitted": False,
        "alpaca_write_api_called": False,
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
    risk_percent: float = Field(default=1.0, gt=0, le=100.0)
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
# A five-trade daily cap is enforced alongside risk, exposure, cooldown and loss guards.
_auto_entry = {
    "enabled": False, "mode": "paper", "timeframe": "5Min",
    "risk_fraction": 0.01, "max_notional_usd": 10.0,
    "max_equity_fraction": 0.10, "daily_loss_limit_fraction": 0.02,
    "max_trades_per_day": 5,
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
        # Re-check after acquiring the lock: a concurrent Disable request may
        # have turned execution off while this tick was waiting.
        if not _auto_entry["enabled"] or not _paper_only_configured():
            return
        try:
            day_key = _utc_day_key()
            account = await _paper_request("GET", "/v2/account")
            equity = float(account.get("equity") or 0)
            buying_power = float(account.get("buying_power") or 0)
            if str(account.get("status", "")).lower() != "active" or bool(account.get("trading_blocked")):
                _auto_entry["last_event"] = "BLOCKED_ACCOUNT_NOT_ACTIVE_OR_TRADING_BLOCKED"
                _auto_entry["enabled"] = False
                return
            if not math.isfinite(equity) or equity <= 0:
                _auto_entry["last_event"] = "BLOCKED_INVALID_EQUITY"
                return
            if not math.isfinite(buying_power) or buying_power <= 0:
                _auto_entry["last_event"] = "BLOCKED_NO_BUYING_POWER"
                return
            if _auto_entry["day_key"] != day_key:
                _auto_entry.update({"day_key": day_key, "day_start_equity": equity, "trades_today": 0})
            day_start = float(_auto_entry.get("day_start_equity") or equity)
            if equity <= day_start * (1 - _auto_entry["daily_loss_limit_fraction"]):
                _auto_entry.update({"enabled": False, "last_event": "AUTO_DISABLED_DAILY_LOSS_LIMIT"})
                return
            if int(_auto_entry.get("trades_today", 0)) >= int(_auto_entry["max_trades_per_day"]):
                _auto_entry["last_event"] = "DAILY_TRADE_LIMIT_REACHED"
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
            volatility = float(signal_data.get("atr_14") or 0)
            # Use only a fresh executable ask. A last-trade fallback can be stale
            # or materially different from the price available to a market buy.
            if not math.isfinite(reference_price) or reference_price <= 0:
                _auto_entry["last_event"] = "BLOCKED_INVALID_OR_MISSING_ASK"
                return
            if not math.isfinite(volatility) or volatility <= 0:
                _auto_entry["last_event"] = "BLOCKED_INVALID_PRICE_OR_ATR"
                return

            stop_distance = volatility * 1.5
            stop_price = reference_price - stop_distance
            risk_budget = equity * _auto_entry["risk_fraction"]
            risk_sized_notional = risk_budget * reference_price / stop_distance
            notional = min(_auto_entry["max_notional_usd"], equity * _auto_entry["max_equity_fraction"], risk_sized_notional, buying_power)
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
        "daily_trade_count_limit": _auto_entry["max_trades_per_day"],
        "one_open_btc_position_max": True,
        "order_submission_enabled": bool(_auto_entry["enabled"] and _paper_only_configured()),
        "warning": "Paper-only. Auto Entry is OFF by default and resets OFF after server restart. Software-polled exits are not guaranteed exchange-native protection."
    }

@app.post("/api/paper/auto-entry/enable")
async def enable_auto_entry():
    if not _paper_only_configured():
        raise HTTPException(403, "Only the exact Alpaca Paper API host is allowed")
    async with _auto_entry_lock:
        if _exit_manager.get("armed"):
            raise HTTPException(409, "Disarm the Paper Exit Manager before enabling Auto Entry")
        account = await _paper_request("GET", "/v2/account")
        try:
            equity = float(account.get("equity") or 0)
            buying_power = float(account.get("buying_power") or 0)
        except (TypeError, ValueError):
            raise HTTPException(409, "Paper account equity or buying power is invalid")
        if str(account.get("status", "")).lower() != "active" or bool(account.get("trading_blocked")):
            raise HTTPException(409, "Paper account is not active or trading is blocked")
        if not math.isfinite(equity) or equity <= 0:
            raise HTTPException(409, "Paper account equity is unavailable")
        if not math.isfinite(buying_power) or buying_power <= 0:
            raise HTTPException(409, "Paper buying power is unavailable")
        positions = await _paper_request("GET", "/v2/positions")
        if any(str(p.get("symbol", "")).replace("/", "").upper() == "BTCUSD" for p in positions):
            raise HTTPException(409, "Existing BTC Paper position found; inspect it before enabling Auto Entry")
        open_orders = await _paper_request("GET", "/v2/orders", {"status": "open", "limit": 100})
        if any(str(o.get("symbol", "")).replace("/", "").upper() == "BTCUSD" for o in open_orders):
            raise HTTPException(409, "Existing BTC Paper order found; reconcile it before enabling Auto Entry")
        today = _utc_day_key()
        if _auto_entry.get("day_key") != today:
            _auto_entry.update({"day_key": today, "day_start_equity": equity, "trades_today": 0})
        elif _auto_entry.get("day_start_equity") is None:
            _auto_entry["day_start_equity"] = equity
        else:
            baseline = float(_auto_entry["day_start_equity"])
            if equity <= baseline * (1 - _auto_entry["daily_loss_limit_fraction"]):
                raise HTTPException(409, "Daily loss limit reached; Auto Entry cannot be enabled again today")
            if int(_auto_entry.get("trades_today", 0)) >= int(_auto_entry["max_trades_per_day"]):
                raise HTTPException(409, "Daily submitted-entry limit reached; Auto Entry cannot be enabled again today")
        # Re-enabling must not reset today's loss baseline, entry count,
        # cooldown, or last processed candle; otherwise the guards are bypassable.
        _auto_entry.update({
            "enabled": True,
            "last_event": "ENABLED_WAITING_FOR_CONFIRMED_LONG_SETUP",
        })
        return await auto_entry_status()

@app.post("/api/paper/auto-entry/disable")
async def disable_auto_entry():
    # Wait for any in-flight tick/order submission to finish, then prevent
    # another tick from starting after this Disable request returns.
    async with _auto_entry_lock:
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

    account_active = str(account.get("status", "")).lower() == "active"
    trading_allowed = not bool(account.get("trading_blocked"))
    add_check("paper_host", _paper_only_configured(), "Exact Alpaca Paper API host allow-list")
    add_check("account_active", account_active and trading_allowed, "Account active and trading not blocked")
    add_check("account_equity", math.isfinite(equity) and equity > 0, f"Equity USD {equity:.2f}")
    add_check("buying_power", math.isfinite(buying_power) and buying_power > 0, f"Buying power USD {buying_power:.2f}")
    add_check("no_existing_btc_position", btc_position is None, "No open BTC position" if btc_position is None else "BTC position already open")
    add_check("no_existing_btc_order", btc_order is None, "No open BTC order" if btc_order is None else "Open BTC order already exists")
    add_check("exit_manager_disarmed", not bool(_exit_manager.get("armed")), "Exit Manager is DISARMED" if not _exit_manager.get("armed") else "Disarm Exit Manager before enabling Auto Entry")
    add_check("long_signal", signal_data.get("signal") == "LONG_SETUP", f"Signal: {signal_data.get('signal', 'UNKNOWN')}")
    add_check("valid_ask", math.isfinite(ask) and ask > 0, f"Latest ask USD {ask:.2f}")
    add_check("fresh_quote", quote_fresh, f"Quote age {quote_age:.1f}s" if quote_age is not None else "Missing or invalid quote timestamp")
    add_check("valid_atr", math.isfinite(volatility) and volatility > 0, f"ATR(14) USD {volatility:.2f}")

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
    add_check("daily_trade_limit", int(_auto_entry.get("trades_today", 0)) < int(_auto_entry["max_trades_per_day"]),
              f'{_auto_entry.get("trades_today", 0)}/{_auto_entry["max_trades_per_day"]} trades used today')

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
    """Stage 6 is an assessment only; this route cannot enable or submit live orders."""
    auto_entry_enabled = bool(_auto_entry.get("enabled"))
    exit_manager_armed = bool(_exit_manager.get("armed"))
    controls_safe = not auto_entry_enabled and not exit_manager_armed
    gates = [
        {"gate": "paper_execution_controls_safe", "passed": controls_safe,
         "detail": "Auto Entry is OFF and Exit Manager is DISARMED." if controls_safe else
                   "Disable Paper Auto Entry and disarm the Exit Manager before continuing verification."},
        {"gate": "strategy_validation", "passed": False,
         "detail": "Stage 4 strategy validation remains open; the currently tested strategy is not profitable."},
        {"gate": "paper_lifecycle_evidence", "passed": False,
         "detail": "Controlled Paper entry, fill, partial-fill, rejection, exit and restart evidence is incomplete."},
        {"gate": "exchange_native_protection", "passed": False,
         "detail": "Verified exchange-native BTC protective orders are not available in this integration."},
        {"gate": "live_broker_adapter", "passed": False,
         "detail": "No live broker adapter or live order submission endpoint is implemented."},
        {"gate": "production_security_and_monitoring", "passed": False,
         "detail": "Production identity, secret rotation, alerting and operational controls require independent review."},
        {"gate": "explicit_live_authorization", "passed": False,
         "detail": "Real-money execution has not been explicitly authorized."},
    ]
    passed = sum(1 for item in gates if item["passed"])
    return {
        "stage": 6,
        "mode": "READINESS_ASSESSMENT_ONLY",
        "live_trading_supported": False,
        "live_orders_enabled": False,
        "result": "NOT_READY",
        "readiness_percent": round(passed / len(gates) * 100),
        "gates_passed": passed,
        "gates_total": len(gates),
        "gates": gates,
        "next_actions": [
            "Keep Auto Entry OFF and Exit Manager DISARMED.",
            "Complete Stage 4 strategy validation with robust out-of-sample results.",
            "Collect controlled Paper lifecycle and restart-recovery evidence.",
            "Review exchange-native protection, production security and monitoring.",
            "Reassess authorization only after every technical gate is independently verified."
        ],
        "paper_auto_entry_enabled": auto_entry_enabled,
        "paper_exit_manager_armed": exit_manager_armed,
        "broker_api_called": False,
        "order_submitted": False,
        "note": "Assessment only. This endpoint makes no broker API calls, cannot enable execution, and never submits orders."
    }


@app.get("/api/backtest/stage4-5")
async def stage45_parameter_research(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(10000, ge=3000, le=10000),
    train_fraction: float = Query(0.60, gt=0.50, lt=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Read-only Stage 4.5: select parameters on training data, then one holdout test."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 3000,
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }
    try:
        result = run_stage45_report(
            bars, train_fraction, starting_equity, notional_usd, fee_rate, slippage_bps
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    split = result["split_index"]
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "stage4_5_train_only_parameter_selection",
        "validation": "RESEARCH_ONLY_NOT_CERTIFIED",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "split": {
            "method": "chronological_strict_boundary",
            "train_fraction": train_fraction,
            "training_bars": split,
            "holdout_bars": len(bars) - split,
            "train_to": bars[split - 1].get("t"),
            "first_possible_holdout_fill": result["first_possible_holdout_fill"],
            "holdout_to": bars[-1].get("t"),
        },
        "research": {
            "strategy": "Breakout pullback + relative volume",
            "predeclared_grid": {
                "relative_volume_threshold": [1.2, 1.5, 1.8],
                "pullback_atr": [0.15, 0.25, 0.40],
                "pullback_bars": [2, 4, 6],
                "donchian_lookback": 20,
                "stop_atr_multiple": 1.5,
                "reward_risk": 2.0,
            },
            "grid_size": result["grid_size"],
            "selection_rule": result["selection_rule"],
            "qualified_candidates": result["qualified_candidates"],
            "selected_parameters": result["selected_parameters"],
            "selected_training_metrics": result["selected_training_metrics"],
            "holdout": result["holdout"],
            "top_training_candidates": result["top_training_candidates"],
            "diagnostics": result["diagnostics"],
            "assumptions": {
                "starting_equity_usd": starting_equity,
                "fixed_notional_usd": notional_usd,
                "fee_per_side_percent": fee_rate * 100,
                "slippage_bps_per_side": slippage_bps,
                "holdout_selection": "No parameter selection or ranking uses holdout metrics.",
            },
        },
        "automated_execution": False,
        "order_submitted": False,
        "alpaca_write_api_called": False,
    }


@app.get("/api/backtest/stage4-6")
async def stage46_walk_forward(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=3000, le=30000),
    folds: int = Query(3, ge=2, le=5),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Read-only Stage 4.6 fixed-parameter chronological walk-forward report."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 3000,
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }
    try:
        result = run_stage46_report(
            bars, starting_equity, notional_usd, fee_rate, slippage_bps, folds
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "stage4_6_fixed_parameter_walk_forward",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "research": result,
        "assumptions": {
            "starting_equity_usd_per_fold": starting_equity,
            "fixed_notional_usd": notional_usd,
            "fee_per_side_percent": fee_rate * 100,
            "slippage_bps_per_side": slippage_bps,
            "each_fold_starts_with_fresh_equity": True,
            "parameters_frozen_before_fold_evaluation": True,
        },
        "automated_execution": False,
        "order_submitted": False,
        "alpaca_write_api_called": False,
    }


@app.get("/api/backtest/stage4-7")
async def stage47_bootstrap_research(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=3000, le=30000),
    folds: int = Query(3, ge=2, le=5),
    simulations: int = Query(2000, ge=100, le=10000),
    seed: int = Query(47, ge=0, le=1000000),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Read-only Stage 4.7 bootstrap robustness report; not a forecast."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 3000,
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }
    try:
        result = run_stage47_report(
            bars, starting_equity, notional_usd, fee_rate, slippage_bps,
            folds, simulations, seed,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "stage4_7_bootstrap_robustness",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "research": result,
        "automated_execution": False,
        "order_submitted": False,
        "alpaca_write_api_called": False,
    }


@app.get("/api/research/shadow-snapshot")
async def paper_shadow_snapshot(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(3000, ge=3000, le=10000),
):
    """Read-only one-shot shadow snapshot; observes signals but never submits orders."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    completed = _completed_bars(bars, "5Min")
    if len(completed) < 1000:
        return {
            "symbol": "BTC/USD", "status": "insufficient_completed_data",
            "bars_used": len(completed), "minimum_required": 1000,
            "shadow_only": True, "order_submitted": False,
            "alpaca_write_api_called": False,
        }
    built = build_stage44_signals(
        completed, lookback=20, relative_volume_threshold=1.5,
        pullback_atr=0.25, pullback_bars=4,
    )
    mask = built["signals"]["breakout_pullback_relvol"]
    signal_indices = [i for i, active in enumerate(mask) if active]
    now = datetime.now(timezone.utc)
    latest_signal = None
    if signal_indices:
        index = signal_indices[-1]
        signal_bar = completed[index]
        signal_close = _stamp_bar_end(signal_bar, 300)
        age = (now - signal_close).total_seconds()
        latest_signal = {
            "signal": "LONG_SETUP",
            "signal_bar_open_time": signal_bar.get("t"),
            "signal_close_time": signal_close.isoformat().replace("+00:00", "Z"),
            "age_seconds": round(age, 1),
            "fresh": 0 <= age <= 1200,
        }
    status = (
        "SHADOW_SIGNAL_OBSERVED" if latest_signal and latest_signal["fresh"]
        else "STALE_SIGNAL_ONLY" if latest_signal
        else "NO_SHADOW_SIGNAL"
    )
    return {
        "symbol": "BTC/USD", "status": status,
        "mode": "READ_ONLY_SHADOW_SNAPSHOT",
        "strategy": "Stage 4.4 pullback + relative volume baseline",
        "bars_used": len(completed), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "latest_completed_bar_time": completed[-1].get("t"),
        "latest_observed_signal": latest_signal,
        "recent_signal_count": len(signal_indices),
        "diagnostics": built["diagnostics"],
        "shadow_only": True,
        "paper_order_enabled": False,
        "order_submitted": False,
        "alpaca_write_api_called": False,
    }


def _stamp_bar_end(bar: dict, seconds: int) -> datetime:
    value = datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value + timedelta(seconds=seconds)


@app.get("/api/research/safety-audit")
async def research_safety_audit():
    """Local configuration audit only; no broker API calls and no state changes."""
    auto_entry_enabled = bool(_auto_entry.get("enabled", False))
    exit_manager_armed = bool(_exit_manager.get("armed", False))
    paper_host_verified = _paper_only_configured()
    controls_safe = not auto_entry_enabled and not exit_manager_armed
    result = "SAFE_FOR_READ_ONLY_RESEARCH" if paper_host_verified and controls_safe else "REQUIRES_REVIEW"
    return {
        "stage": "4.9",
        "result": result,
        "checks": {
            "paper_host_allowlisted": paper_host_verified,
            "paper_auto_entry_off": not auto_entry_enabled,
            "paper_exit_manager_disarmed": not exit_manager_armed,
            "live_trading_supported": False,
            "live_orders_enabled": False,
            "audit_is_read_only": True,
        },
        "paper_auto_entry_enabled": auto_entry_enabled,
        "paper_exit_manager_armed": exit_manager_armed,
        "broker_api_called": False,
        "broker_write_api_called": False,
        "order_submitted": False,
        "note": "This checks local configuration only. It does not inspect broker positions, open orders, fills, secrets, or Render availability.",
    }


@app.get("/api/research/final-readiness")
async def final_readiness_review():
    """Stage 5.0 final review; assessment only and permanently non-enabling."""
    safety = await research_safety_audit()
    live_review = await live_trading_readiness()
    return {
        "stage": "5.0",
        "status": "FINAL_READINESS_REVIEW",
        "result": "NOT_READY",
        "readiness_percent": live_review["readiness_percent"],
        "gates_passed": live_review["gates_passed"],
        "gates_total": live_review["gates_total"],
        "gates": live_review["gates"],
        "research_validation": {
            "evidence_scope": "Snapshot of the latest user-supplied deployed research outputs reviewed on 2026-11-22; not a live re-run.",
            "strategy_validation": "FAILED_CURRENT_OBSERVED_RUNS",
            "stage4_4": "NOT_PROFITABLE_ON_REPORTED_HOLDOUT",
            "stage4_5": {
                "status": "FAILED_TRAINING_QUALIFICATION",
                "bars": 10000,
                "qualified_candidates": 0,
                "best_training_net_pnl_usd": -0.7374,
                "holdout_evaluated": False,
            },
            "stage4_6": {
                "status": "FAILED_WALK_FORWARD_PROFITABILITY",
                "bars": 30000,
                "folds": 3,
                "positive_net_pnl_folds": 0,
                "total_trades": 38,
                "total_net_pnl_usd": -2.2886,
            },
            "stage4_7": {
                "status": "FAILED_BOOTSTRAP_ROBUSTNESS",
                "bars": 30000,
                "observed_trades": 38,
                "simulations": 2000,
                "positive_path_probability_percent": 0.0,
                "median_final_equity_usd": 97.6943,
            },
            "stage4_8": {
                "status": "FAILED_NEGATIVE_NET_PNL",
                "bars": 30000,
                "trades": 98,
                "net_pnl_usd": -6.0294,
                "gross_pnl_usd": -1.1326,
                "max_drawdown_percent": 6.15,
            },
            "stage4_9_safety_audit": safety["result"],
            "note": "Historical research snapshot only. These values are not fetched dynamically by this endpoint and must be refreshed after new research runs.",
        },
        "paper_auto_entry_enabled": live_review["paper_auto_entry_enabled"],
        "paper_exit_manager_armed": live_review["paper_exit_manager_armed"],
        "live_trading_supported": False,
        "live_orders_enabled": False,
        "broker_api_called": False,
        "order_submitted": False,
        "note": "This final review does not certify profitability, does not inspect broker positions/orders, does not activate Paper execution, and cannot enable live trading.",
    }


@app.get("/api/backtest/stage4-8")
async def stage48_trade_diagnostics(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=3000, le=30000),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 4.8 trade failure/cost diagnostics; read-only, no parameter search."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {
            "symbol": "BTC/USD", "status": "insufficient_data",
            "bars_used": len(bars), "minimum_required": 3000,
            "automated_execution": False, "order_submitted": False,
            "alpaca_write_api_called": False,
        }
    try:
        result = run_stage48_report(
            bars, starting_equity, notional_usd, fee_rate, slippage_bps
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "symbol": "BTC/USD", "timeframe": timeframe,
        "status": "stage4_8_trade_failure_and_cost_diagnostics",
        "bars_used": len(bars), "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data, "data_pages_fetched": data_pages,
        "period": {"from": bars[0].get("t"), "to": bars[-1].get("t")},
        "assumptions": {
            "starting_equity_usd": starting_equity,
            "fixed_notional_usd": notional_usd,
            "fee_per_side_percent": fee_rate * 100,
            "slippage_bps_per_side": slippage_bps,
            "signal": "Completed 15m breakout pullback + relative volume >= 1.5",
            "fill": "Next 5m candle open",
            "exits": "1.5x ATR stop, 2R target, conservative stop-first OHLC",
        },
        **result,
        "automated_execution": False, "order_submitted": False,
        "alpaca_write_api_called": False,
    }

# Stage 5.1-5.4 offline verification routes; deliberately no broker execution.
try:
    from .stage5_ops import router as stage5_ops_router
except ImportError:
    from stage5_ops import router as stage5_ops_router
app.include_router(stage5_ops_router)


@app.get("/api/research/stage5-1/run")
async def stage51_run_real_backtest(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(10000, ge=3000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
    minimum_trades: int = Query(30, ge=10, le=500),
):
    """Run frozen Stage 4.4 variants on real fetched history with chronological train/holdout."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {
            "stage": "5.1", "result": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "minimum_bars": 3000,
            "broker_api_called": False, "order_submitted": False,
        }
    try:
        report = run_stage44_report(
            bars, train_fraction=train_fraction,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    def gate(metrics: dict) -> bool:
        pf = metrics.get("net_profit_factor", metrics.get("profit_factor"))
        pf_ok = pf == "infinite" or (isinstance(pf, (int, float)) and pf > 1)
        return (
            int(metrics.get("trades", 0)) >= minimum_trades
            and float(metrics.get("net_pnl_usd", 0)) > 0
            and pf_ok
        )

    evaluated = {}
    for name, item in report["reports"].items():
        train_metrics = item["training_metrics"]
        holdout_metrics = item["holdout_metrics"]
        train_pass = gate(train_metrics)
        holdout_pass = gate(holdout_metrics) and train_pass and item["holdout_entries_after_split"]
        evaluated[name] = {
            **item,
            "training_gate_passed": train_pass,
            "holdout_gate_passed": holdout_pass,
            "validated": train_pass and holdout_pass,
        }
    validated_count = sum(x["validated"] for x in evaluated.values())
    return {
        "stage": "5.1",
        "status": "LIVE_DATA_READ_ONLY_BACKTEST",
        "result": "RESEARCH_GATE_PASSED" if validated_count else "NOT_VALIDATED",
        "symbol": "BTC/USD",
        "timeframe": timeframe,
        "bars_used": len(bars),
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data,
        "data_pages_fetched": data_pages,
        "period": {"from": bars[0].get("t"), "to": bars[-1].get("t")},
        "train_fraction": train_fraction,
        "minimum_trades_per_segment": minimum_trades,
        "variants": evaluated,
        "validated_variant_count": validated_count,
        "selection_policy": "All four frozen Stage 4.4 variants evaluated; no parameter search or holdout-based selection.",
        "limitations": [
            "Alpaca historical market-data GET only; no account, order, or position API calls.",
            "Fees and slippage are modelling assumptions, not verified fills.",
            "Each holdout run is a separate flat-start segment; it is not a continuous portfolio simulation.",
            "A passing historical gate is not proof of future profitability or authorization for execution.",
        ],
        "broker_api_called": False,
        "market_data_api_read": True,
        "order_submitted": False,
        "alpaca_write_api_called": False,
        "automated_execution": False,
    }

@app.get("/api/research/stage5-3/run")
async def stage53_strategy_diagnostics(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(10000, ge=3000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
    minimum_training_trades: int = Query(30, ge=10, le=500),
    max_training_drawdown_percent: float = Query(5.0, gt=0, le=50),
):
    """Read-only Stage 5.3 diagnostics and training-only parameter search."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 3000:
        return {
            "stage": "5.3", "result": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "minimum_bars": 3000,
            "broker_api_called": False, "order_submitted": False,
            "alpaca_write_api_called": False, "automated_execution": False,
        }
    try:
        report = run_stage53_report(
            bars, train_fraction=train_fraction,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            minimum_training_trades=minimum_training_trades,
            max_training_drawdown_percent=max_training_drawdown_percent,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "symbol": "BTC/USD",
        "timeframe": timeframe,
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data,
        "data_pages_fetched": data_pages,
        "period": {"from": bars[0].get("t"), "to": bars[-1].get("t")},
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-4/run")
async def stage54_regime_robustness(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(10000, ge=5000, le=30000),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
    folds: int = Query(4, ge=3, le=6),
    minimum_trades_per_fold: int = Query(10, ge=3, le=100),
    max_drawdown_percent: float = Query(5.0, gt=0, le=50),
):
    """Read-only Stage 5.4 fixed-strategy regime and sequential fold report."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.4", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "minimum_bars": 5000,
            "market_data_api_read": True, "order_submitted": False,
            "alpaca_write_api_called": False, "automated_execution": False,
        }
    try:
        report = run_stage54_report(
            bars, starting_equity=starting_equity,
            notional_usd=notional_usd, fee_rate=fee_rate,
            slippage_bps=slippage_bps, folds=folds,
            minimum_trades_per_fold=minimum_trades_per_fold,
            max_drawdown_percent=max_drawdown_percent,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": has_more_data,
        "data_pages_fetched": data_pages,
    })
    return report

@app.get("/api/research/stage5-5/run")
async def stage55_history_cost_audit(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
):
    """Read-only extended-history data-integrity and cost-reconciliation audit."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.5", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "market_data_api_read": True,
            "order_submitted": False, "alpaca_write_api_called": False,
            "automated_execution": False,
        }
    try:
        return run_stage55_report(
            bars, requested_bars=limit, has_more_data=has_more_data,
            data_pages_fetched=data_pages, starting_equity=starting_equity,
            notional_usd=notional_usd, fee_rate=fee_rate,
            slippage_bps=slippage_bps, train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get("/api/research/stage5-6/run")
async def stage56_training_failure_attribution(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
):
    """Training-only read-only failure attribution; holdout is not evaluated."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.6", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "alpaca_write_api_called": False,
            "automated_execution": False,
        }
    try:
        report = run_stage56_failure_report(
            bars, requested_bars=limit, starting_equity=starting_equity,
            notional_usd=notional_usd, fee_rate=fee_rate,
            slippage_bps=slippage_bps, train_fraction=train_fraction,
        )
        report["has_more_data"] = bool(has_more_data)
        report["data_pages_fetched"] = data_pages
        return report
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get("/api/research/stage5-7/run")
async def stage57_hourly_trend_candidate(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
    minimum_training_trades: int = Query(30, ge=10, le=500),
):
    """Stage 5.7: one fixed hourly-trend candidate; training-only and read-only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.7", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage57_candidate_report(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
            minimum_training_trades=minimum_training_trades,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-8/run")
async def stage58_execution_diagnostics(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.8: diagnose the fixed Stage 5.7 candidate on training bars only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.8", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage58_execution_diagnostics(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-9/run")
async def stage59_trade_accounting_audit(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.9: independent trade accounting audit on training data only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.9", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage59_accounting_audit(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-10/run")
async def stage510_cost_edge_diagnostics(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.10: fixed-strategy cost/edge diagnostics on training data only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.10", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage510_cost_edge_diagnostics(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-11/run")
async def stage511_stop_loss_diagnostics(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.11: stop-loss root cause diagnostics on training data only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.11", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage511_stop_loss_diagnostics(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-12/run")
async def stage512_entry_quality_diagnostics(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.12: entry timing and false-breakout diagnostics, training only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.12", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage512_entry_quality_diagnostics(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-13/run")
async def stage513_temporal_stability_audit(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.13: temporal stability and sample adequacy, training only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.13", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage513_temporal_stability_audit(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-14/run")
async def stage514_strategy_decision_gate(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.14: deterministic research decision gate; training only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.14", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage514_strategy_decision_gate(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-15/run")
async def stage515_loss_concentration_investigation(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.15: training-only loss concentration investigation."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.15", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage515_loss_concentration_investigation(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

@app.get("/api/research/stage5-16/run")
async def stage516_trade_path_diagnostics(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.16: training-only MFE/MAE and OHLC path diagnostics."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.16", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage516_trade_path_diagnostics(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report


@app.get("/api/research/stage5-17/run")
async def stage517_log_return_backtest(
    timeframe: str = Query("5Min", pattern="^5Min$"),
    limit: int = Query(30000, ge=5000, le=30000),
    train_fraction: float = Query(0.60, ge=0.50, le=0.80),
    starting_equity: float = Query(100, gt=0, le=1000000),
    notional_usd: float = Query(10, gt=0, le=100000),
    fee_rate: float = Query(0.0025, ge=0, le=0.02),
    slippage_bps: float = Query(5, ge=0, le=500),
):
    """Stage 5.17: fixed logarithmic-return momentum backtest, training only."""
    bars, has_more_data, data_pages = await fetch_backtest_bars(timeframe, limit)
    if len(bars) < 5000:
        return {
            "stage": "5.17", "status": "INSUFFICIENT_DATA",
            "bars_used": len(bars), "requested_bars": limit,
            "minimum_bars": 5000, "holdout_accessed": False,
            "order_submitted": False, "automated_execution": False,
        }
    try:
        report = run_stage517_log_backtest(
            bars, requested_bars=limit,
            starting_equity=starting_equity, notional_usd=notional_usd,
            fee_rate=fee_rate, slippage_bps=slippage_bps,
            train_fraction=train_fraction,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    report.update({
        "requested_bars": limit,
        "history_complete_for_request": len(bars) == limit,
        "has_more_data": bool(has_more_data),
        "data_pages_fetched": data_pages,
        "market_data_api_read": True,
    })
    return report

