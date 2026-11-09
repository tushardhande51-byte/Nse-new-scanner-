import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

# Broker-free EOD scanner. NSE EQ universe; daily candles from Yahoo Finance.
NSE_CSV_URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
]
NSE_HOME = "https://www.nseindia.com/"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}.NS"
TIMEOUT = 25
MAX_WORKERS = 8
MIN_ROWS = 210
VOLUME_MULTIPLIER = 1.5
RSI_MIN, RSI_MAX = 55, 70
ADX_MIN = 20
LEVEL_LOOKBACK = 120
PIVOT_WIDTH = 3
LEVEL_BUFFER_PCT = 0.005
# Advisory trade-quality warnings; these never reject a strict 6/6 match.
NEAR_RESISTANCE_PCT = 2.0
CLOSE_RESISTANCE_PCT = 4.0
HIGH_VOLUME_RATIO = 3.0
UNUSUAL_VOLUME_RATIO = 5.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Accept": "application/json,text/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def now_ist():
    return datetime.now(ZoneInfo("Asia/Kolkata"))


def get_nse_universe():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(NSE_HOME, timeout=TIMEOUT)
    except requests.RequestException:
        pass

    last_error = None
    for url in NSE_CSV_URLS:
        try:
            response = session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            frame = pd.read_csv(io.BytesIO(response.content))
            frame.columns = [str(c).strip().upper() for c in frame.columns]
            if "SYMBOL" not in frame.columns or "SERIES" not in frame.columns:
                raise ValueError("NSE equity CSV does not contain SYMBOL/SERIES columns")
            frame["SYMBOL"] = frame["SYMBOL"].astype(str).str.strip()
            frame["SERIES"] = frame["SERIES"].astype(str).str.strip().str.upper()
            frame = frame[(frame["SERIES"] == "EQ") & frame["SYMBOL"].str.fullmatch(r"[A-Z0-9&._-]+")]
            frame = frame.drop_duplicates("SYMBOL")
            if frame.empty:
                raise ValueError("NSE equity universe is empty")
            name_col = "NAME OF COMPANY" if "NAME OF COMPANY" in frame.columns else None
            return [
                (row["SYMBOL"], str(row[name_col]).strip() if name_col else row["SYMBOL"])
                for _, row in frame.iterrows()
            ]
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not download official NSE equity list: {last_error}")


def fetch_history(symbol):
    url = YAHOO_CHART.format(requests.utils.quote(symbol, safe=""))
    params = {"range": "1y", "interval": "1d", "events": "history"}
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if response.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json().get("chart", {})
            if payload.get("error") or not payload.get("result"):
                return None
            result = payload["result"][0]
            quote = result["indicators"]["quote"][0]
            frame = pd.DataFrame({
                "date": pd.to_datetime(result["timestamp"], unit="s", utc=True),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
            }).dropna()
            frame = frame.sort_values("date").reset_index(drop=True)
            return frame if len(frame) >= MIN_ROWS else None
        except Exception:
            if attempt < 2:
                time.sleep(1 + attempt)
    return None


def rsi(series, period=14):
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    result = 100 - 100 / (1 + rs)
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100)
    result = result.mask((avg_loss == 0) & (avg_gain == 0), 50)
    return result


def adx(frame, period=14):
    high, low, close = frame["high"], frame["low"], frame["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    previous_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def support_resistance_levels(frame, entry):
    # Levels are advisory only: never reject a stock that has passed 6/6.
    recent = frame.tail(LEVEL_LOOKBACK).copy()
    pivot_high = recent["high"].eq(recent["high"].rolling(2 * PIVOT_WIDTH + 1, center=True).max())
    pivot_low = recent["low"].eq(recent["low"].rolling(2 * PIVOT_WIDTH + 1, center=True).min())

    atr_series = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - frame["close"].shift(1)).abs(),
        (frame["low"] - frame["close"].shift(1)).abs(),
    ], axis=1).max(axis=1).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    atr_value = float(atr_series.iloc[-1])
    if pd.isna(atr_value) or atr_value <= 0:
        atr_value = entry * 0.02

    supports = recent.loc[pivot_low & (recent["low"] < entry), "low"]
    if not supports.empty:
        support = float(supports.max())
        support_source = "Pivot support"
    else:
        support = entry - 1.5 * atr_value
        support_source = "ATR fallback support"

    stoploss = support * (1 - LEVEL_BUFFER_PCT)
    if not stoploss < entry:
        stoploss = entry - 1.5 * atr_value
        support = stoploss
        support_source = "ATR fallback support"

    resistance_values = sorted(
        float(value)
        for value in recent.loc[pivot_high & (recent["high"] > entry), "high"].dropna()
    )
    resistance_zones = []
    for level in resistance_values:
        if not resistance_zones or (level - resistance_zones[-1]) / resistance_zones[-1] > 0.01:
            resistance_zones.append(level)

    risk = entry - stoploss
    # Prefer actual overhead pivot resistance. Only use projections when a
    # usable pivot level is unavailable; never label a projection as resistance.
    targets, target_sources, target_resistance_prices = [], [], []
    projection_multiples = [1.1, 2.0, 3.0]
    for i in range(3):
        if i < len(resistance_zones):
            raw_resistance = resistance_zones[i]
            candidate = raw_resistance * (1 - LEVEL_BUFFER_PCT)
            if candidate > entry and (not targets or candidate > targets[-1]):
                targets.append(candidate)
                target_sources.append("Actual pivot resistance")
                target_resistance_prices.append(raw_resistance)
                continue

        candidate = entry + risk * projection_multiples[i]
        if targets and candidate <= targets[-1]:
            candidate = targets[-1] + risk * 0.5
        actual_multiple = (candidate - entry) / risk if risk > 0 else 0
        targets.append(candidate)
        target_sources.append(f"Projected target ({actual_multiple:.2f}R; no usable pivot)")
        target_resistance_prices.append(None)

    reward_to_t1 = targets[0] - entry
    risk_reward_t1 = reward_to_t1 / risk if risk > 0 else 0
    resistances = (resistance_zones + [None, None, None])[:3]
    # Measure the nearest actual overhead pivot, not a projected target.
    nearest_resistance = resistance_zones[0] if resistance_zones else None
    resistance_gap_pct = (
        (nearest_resistance - entry) / entry * 100
        if nearest_resistance is not None and entry > 0 else None
    )
    if resistance_gap_pct is None:
        resistance_warning = "NO OVERHEAD PIVOT - projection only"
    elif resistance_gap_pct < NEAR_RESISTANCE_PCT:
        resistance_warning = "NEAR RESISTANCE - entry has limited room"
    elif resistance_gap_pct < CLOSE_RESISTANCE_PCT:
        resistance_warning = "RESISTANCE CLOSE - check breakout strength"
    else:
        resistance_warning = "ROOM TO RESISTANCE"
    stoploss_risk_pct = (entry - stoploss) / entry * 100 if entry > 0 else 0
    support_sl_buffer_pct = (support - stoploss) / support * 100 if support > 0 else 0
    # After T1, keep the remaining-position stop below the original support.
    return (support, resistances, stoploss, targets, risk_reward_t1,
            support_source, target_sources, target_resistance_prices,
            nearest_resistance, resistance_gap_pct, resistance_warning,
            stoploss_risk_pct, support_sl_buffer_pct)

def evaluate(symbol, company):
    frame = fetch_history(symbol)
    if frame is None or len(frame) < MIN_ROWS:
        return None
    close = frame["close"]
    frame["ema20"] = close.ewm(span=20, adjust=False).mean()
    frame["ema50"] = close.ewm(span=50, adjust=False).mean()
    frame["rsi14"] = rsi(close)
    frame["avg_volume20"] = frame["volume"].rolling(20).mean()
    frame["prior_high20"] = frame["high"].shift(1).rolling(20).max()
    frame["adx14"] = adx(frame)
    row = frame.iloc[-1]
    needed = ["close", "ema20", "ema50", "rsi14", "volume", "avg_volume20", "prior_high20", "adx14"]
    if row[needed].isna().any():
        return None

    checks = {
        "Close > EMA20": row.close > row.ema20,
        "EMA20 > EMA50": row.ema20 > row.ema50,
        "RSI 55-70": RSI_MIN <= row.rsi14 <= RSI_MAX,
        "Volume > 1.5x 20D avg": row.volume > row.avg_volume20 * VOLUME_MULTIPLIER,
        "20D breakout": row.close > row.prior_high20,
        "ADX > 20": row.adx14 > ADX_MIN,
    }
    if sum(bool(value) for value in checks.values()) != 6:
        return None

    entry = float(row.close)
    levels = support_resistance_levels(frame, entry)
    (support, resistances, stoploss, targets, risk_reward_t1, support_source,
     target_sources, target_resistance_prices, nearest_resistance,
     resistance_gap_pct, resistance_warning, stoploss_risk_pct,
     support_sl_buffer_pct) = levels
    volume_ratio = float(row.volume / row.avg_volume20)
    if volume_ratio >= UNUSUAL_VOLUME_RATIO:
        volume_warning = "UNUSUAL VOLUME - verify news / bulk or block deal"
    elif volume_ratio >= HIGH_VOLUME_RATIO:
        volume_warning = "HIGH VOLUME - verify reason"
    else:
        volume_warning = "Normal relative volume"

    return {
        "symbol": symbol,
        "company": company,
        "date": str(row.date.date()),
        "close": entry,
        "ema20": float(row.ema20),
        "ema50": float(row.ema50),
        "rsi": float(row.rsi14),
        "adx": float(row.adx14),
        "volume_ratio": volume_ratio,
        "volume_warning": volume_warning,
        "entry": entry,
        "support": support,
        "support_source": support_source,
        "nearest_actual_resistance": nearest_resistance,
        "resistance_gap_pct": resistance_gap_pct,
        "resistance_warning": resistance_warning,
        "stoploss_risk_pct_from_entry": stoploss_risk_pct,
        "support_to_stoploss_buffer_pct": support_sl_buffer_pct,
        "resistance_1": resistances[0],
        "resistance_2": resistances[1],
        "resistance_3": resistances[2],
        "target_1_source": target_sources[0],
        "target_2_source": target_sources[1],
        "target_3_source": target_sources[2],
        "target_1_resistance_price": target_resistance_prices[0],
        "target_2_resistance_price": target_resistance_prices[1],
        "target_3_resistance_price": target_resistance_prices[2],
        "stoploss": stoploss,
        "target_1": targets[0],
        "target_2": targets[1],
        "target_3": targets[2],
        "risk_reward_to_t1": risk_reward_t1,
        "rr_assessment": ("LOW R:R - caution" if risk_reward_t1 < 1.0 else
                          "MODERATE R:R - check risk" if risk_reward_t1 < 1.5 else
                          "R:R 1.5 or higher"),
        "trade_quality": (
            "GREEN - GOOD SETUP" if
            stoploss_risk_pct <= 5.0 and risk_reward_t1 >= 1.5
            and target_sources[0] == "Actual pivot resistance"
            else "RED - HIGH RISK / WEAK R:R" if
            stoploss_risk_pct > 8.0 or risk_reward_t1 < 1.0
            else "YELLOW - MODERATE / CHECK SETUP"
        ),
        "trade_quality_emoji": (
            "🟢" if stoploss_risk_pct <= 5.0 and risk_reward_t1 >= 1.5
            and target_sources[0] == "Actual pivot resistance"
            else "🔴" if stoploss_risk_pct > 8.0 or risk_reward_t1 < 1.0
            else "🟡"
        ),
        "booking_plan": "50%-30%-20%",
        "stoploss_after_t1": "Keep below support",
        "filters_passed": "6/6",
    }


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram not sent: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets missing.")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return bool(response.json().get("ok"))
    except Exception as exc:
        print(f"Telegram delivery failed: {exc}")
        return False


def main():
    started = now_ist()
    print(f"NSE EOD TECHNICAL SCANNER | {started:%Y-%m-%d %H:%M:%S %Z}")
    print("No broker connection or order placement.")
    print("Every strict 6/6 match is retained; pivot levels are used where available and ATR/R-multiple fallbacks complete SL/targets; R:R never rejects a match.")
    universe = get_nse_universe()
    print(f"NSE EQ symbols downloaded: {len(universe)}")

    matches, errors = [], 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(evaluate, symbol, company): symbol for symbol, company in universe}
        for count, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                result = future.result()
                if result:
                    matches.append(result)
                    print(f"6/6 TECHNICAL MATCH: {symbol} | T1 R:R={result['risk_reward_to_t1']:.2f}")
            except Exception as exc:
                errors += 1
                print(f"ERROR {symbol}: {exc}")
            if count % 100 == 0:
                print(f"Progress: {count}/{len(universe)} | matches={len(matches)} | errors={errors}")

    matches.sort(key=lambda item: (item["adx"], item["volume_ratio"]), reverse=True)
    output = pd.DataFrame(matches)
    output.to_csv("nse_swing_signals.csv", index=False)

    report_date = now_ist().strftime("%d-%m-%Y")
    lines = [
        "NSE SWING SCANNER - EOD",
        f"Date: {report_date}",
        f"Universe: {len(universe)} NSE EQ symbols",
        "Signal rule: strict 6/6 only; R:R is displayed, never used to reject a stock | No orders placed",
        "Target labels: actual pivot resistance is shown with its price; projections are clearly labelled and are not resistance levels.",
        "Booking plan: T1 50%, T2 30%, T3 remaining 20%; after T1 keep SL below support.",
        "",
    ]
    if not matches:
        lines.append("No stock passed the strict 6/6 technical filters. Support/targets and R:R do not reject 6/6 matches.")
    else:
        lines.append(f"Actionable matches: {len(matches)}")
        for item in matches[:20]:
            lines.extend([
                f"{item['symbol']} - {item['company']}",
                f"{item['trade_quality_emoji']} TRADE QUALITY: {item['trade_quality']}",
                f"Entry: Rs {item['entry']:.2f}",
                f"Support: Rs {item['support']:.2f} ({item['support_source']}) | Stop-loss: Rs {item['stoploss']:.2f}",
                f"Risk to SL: {item['stoploss_risk_pct_from_entry']:.2f}% of entry | Support-to-SL buffer: {item['support_to_stoploss_buffer_pct']:.2f}%",
                f"Nearest actual resistance: Rs {item['nearest_actual_resistance']:.2f} ({item['resistance_gap_pct']:.2f}% above entry)" if item['nearest_actual_resistance'] is not None else "Nearest actual resistance: Not found",
                f"Resistance check: {item['resistance_warning']}",
                f"T1: Rs {item['target_1']:.2f} | {item['target_1_source']}" +
                    (f" at Rs {item['target_1_resistance_price']:.2f}" if item["target_1_resistance_price"] is not None else "") + " | book 50%",
                f"T2: Rs {item['target_2']:.2f} | {item['target_2_source']}" +
                    (f" at Rs {item['target_2_resistance_price']:.2f}" if item["target_2_resistance_price"] is not None else "") + " | book 30%",
                f"T3: Rs {item['target_3']:.2f} | {item['target_3_source']}" +
                    (f" at Rs {item['target_3_resistance_price']:.2f}" if item["target_3_resistance_price"] is not None else "") + " | book final 20%",
                f"T1 Risk:Reward: 1:{item['risk_reward_to_t1']:.2f} | {item['rr_assessment']}",
                "After T1: keep remaining-position SL below support; no automatic breakeven move.",
                f"RSI: {item['rsi']:.1f} | ADX: {item['adx']:.1f} | Volume: {item['volume_ratio']:.1f}x | {item['volume_warning']}",
                "",
            ])
        if len(matches) > 20:
            lines.append(f"Full list: nse_swing_signals.csv ({len(matches)} stocks)")
    lines.extend(["", "Data: NSE EQ universe + Yahoo Finance daily candles. Verify prices/levels before trading."])
    message = "\n".join(lines)
    print(message)
    delivered = send_telegram(message)
    print(f"Telegram delivered: {delivered}")
    print(f"Finished: {now_ist():%Y-%m-%d %H:%M:%S %Z}; data errors={errors}; matches={len(matches)}")


if __name__ == "__main__":
    main()
