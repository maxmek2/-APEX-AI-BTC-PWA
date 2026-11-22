"""Stage 4.4: pullback and relative-volume research variants.

All signals are formed from completed 15m bars and filled at the next 5m open.
Read-only research only; no broker/order dependencies.
"""
from __future__ import annotations
from statistics import median
from .stage43 import aggregate_complete_5m, atr_values, ema_values, run_breakout_backtest, _stamp


def build_stage44_signals(bars: list[dict], lookback: int = 20) -> dict:
    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    m15 = aggregate_complete_5m(bars, 15)
    h1 = aggregate_complete_5m(bars, 60)
    atrs = atr_values(m15, 14)
    closes = [x["c"] for x in h1]
    ema20, ema50, ema200 = (ema_values(closes, p) for p in (20, 50, 200))
    h1_state = {}
    for i, item in enumerate(h1):
        h1_state[item["bucket"]] = {
            "valid_20_50": ema20[i] is not None and ema50[i] is not None,
            "bull_20_50": ema20[i] is not None and ema50[i] is not None and ema20[i] > ema50[i] and closes[i] > ema20[i],
            "valid_50_200": ema50[i] is not None and ema200[i] is not None,
            "bull_50_200": ema50[i] is not None and ema200[i] is not None and ema50[i] > ema200[i] and closes[i] > ema50[i],
        }
    by15 = {x["bucket"]: i for i, x in enumerate(m15)}
    by60 = {x["bucket"]: i for i, x in enumerate(h1)}
    names = ("breakout_relvol_1p5", "breakout_pullback", "breakout_pullback_relvol", "breakout_relvol_1p5_1h20_50")
    masks = {name: [False] * len(bars) for name in names}
    atr_base = [None] * len(bars)
    diag = {"complete_15m_bars": len(m15), "complete_1h_bars": len(h1),
            "breakout_events": 0, "volume_ratio_pass": 0, "pullback_confirmations": 0,
            "hourly_ema20_50_valid": 0, "hourly_ema20_50_bullish": 0,
            "hourly_ema50_200_valid": 0, "hourly_ema50_200_bullish": 0,
            "breakouts_with_valid_1h": 0, "breakouts_with_bullish_1h20_50": 0,
            "breakouts_with_bullish_1h50_200": 0}
    pending = []
    for i, bar in enumerate(bars):
        close_ts = int(_stamp(bar).timestamp()) + 300
        if close_ts % 900:
            continue
        b15 = close_ts // 900 - 1
        p = by15.get(b15)
        if p is None or p < max(lookback, 14) or atrs[p] is None or atrs[p] <= 0:
            continue
        cur = m15[p]
        prev = m15[p-lookback:p]
        ceiling = max(x["h"] for x in prev)
        vol_med = median(x["v"] for x in prev)
        ratio = cur["v"] / vol_med if vol_med > 0 else None
        breakout = cur["c"] > ceiling
        atr = atrs[p]
        atr_base[i] = atr
        if breakout:
            diag["breakout_events"] += 1
            if ratio is not None and ratio >= 1.5:
                diag["volume_ratio_pass"] += 1
                masks["breakout_relvol_1p5"][i] = True
            pending.append({"level": ceiling, "atr": atr, "expires": p + 4, "ratio": ratio})
        # A pullback must happen after a prior breakout, touch near its level,
        # then close back above that level. No same-candle breakout entry.
        survivors = []
        for setup in pending:
            if p > setup["expires"]:
                continue
            touched = cur["l"] <= setup["level"] + 0.25 * setup["atr"]
            reclaimed = cur["c"] >= setup["level"]
            if p > setup.get("origin", p) and touched and reclaimed:
                diag["pullback_confirmations"] += 1
                masks["breakout_pullback"][i] = True
                if ratio is not None and ratio >= 1.5:
                    masks["breakout_pullback_relvol"][i] = True
                continue
            survivors.append(setup)
        pending = survivors
        # Add origin index to newly-created setups (after prior setups processed).
        for setup in pending:
            if "origin" not in setup:
                setup["origin"] = p
        # Most recently completed hourly candle only.
        b1 = close_ts // 3600 - 1
        hp = by60.get(b1)
        if hp is None:
            earlier = [k for k in by60 if k <= b1]
            hp = by60[max(earlier)] if earlier else None
        state = h1_state[h1[hp]["bucket"]] if hp is not None else None
        if state:
            diag["hourly_ema20_50_valid"] += int(state["valid_20_50"])
            diag["hourly_ema20_50_bullish"] += int(state["bull_20_50"])
            diag["hourly_ema50_200_valid"] += int(state["valid_50_200"])
            diag["hourly_ema50_200_bullish"] += int(state["bull_50_200"])
            if breakout:
                diag["breakouts_with_valid_1h"] += int(state["valid_50_200"])
                diag["breakouts_with_bullish_1h20_50"] += int(state["bull_20_50"])
                diag["breakouts_with_bullish_1h50_200"] += int(state["bull_50_200"])
            masks["breakout_relvol_1p5_1h20_50"][i] = bool(breakout and ratio is not None and ratio >= 1.5 and state["bull_20_50"])
    return {"signals": masks, "atr_by_base": atr_base, "diagnostics": diag}


def run_stage44_report(bars: list[dict], train_fraction: float = 0.60,
                       starting_equity: float = 100.0, notional_usd: float = 10.0,
                       fee_rate: float = 0.0025, slippage_bps: float = 5.0) -> dict:
    built = build_stage44_signals(bars)
    masks, atrs = built["signals"], built["atr_by_base"]
    split = int(len(bars) * train_fraction)
    if split < 1000 or len(bars) - split < 100:
        raise ValueError("Insufficient chronological training or holdout data")
    first_fill = bars[split + 1].get("t")
    reports = {}
    for name, mask in masks.items():
        train = run_breakout_backtest(bars[:split+1], mask[:split+1], atrs[:split+1],
                                      starting_equity, notional_usd, fee_rate, slippage_bps)
        costs = []
        for bps in sorted({0, 5, 10, 20, slippage_bps}):
            test = run_breakout_backtest(bars, mask, atrs, starting_equity, notional_usd,
                                         fee_rate, bps, start_index=split)
            valid = all(t.get("entry_time") and t["entry_time"] >= first_fill for t in test["trades"])
            costs.append({"slippage_bps_per_side": bps, "metrics": test["metrics"],
                          "entries_after_split": valid})
        selected = next(x for x in costs if x["slippage_bps_per_side"] == slippage_bps)
        reports[name] = {"training_metrics": train["metrics"], "holdout_metrics": selected["metrics"],
                         "holdout_entries_after_split": selected["entries_after_split"],
                         "cost_sensitivity": costs,
                         "training_signal_count": sum(mask[:split+1]),
                         "holdout_signal_count": sum(mask[split:])}
    return {"reports": reports, "diagnostics": built["diagnostics"],
            "split_index": split, "first_possible_holdout_fill": first_fill}
