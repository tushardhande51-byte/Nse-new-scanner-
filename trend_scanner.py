import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

NSE_CSV_URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
]
NSE_HOME = "https://www.nseindia.com/"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}.NS"
TIMEOUT = 25
MAX_WORKERS = 10
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
                raise ValueError("NSE CSV missing SYMBOL/SERIES")
            frame["SYMBOL"] = frame["SYMBOL"].astype(str).str.strip()
            frame["SERIES"] = frame["SERIES"].astype(str).str.strip().str.upper()
            frame = frame[(frame["SERIES"] == "EQ") & frame["SYMBOL"].str.fullmatch(r"[A-Z0-9&._-]+")]
            frame = frame.drop_duplicates("SYMBOL")
            if frame.empty:
                raise ValueError("NSE EQ universe is empty")
            name_col = "NAME OF COMPANY" if "NAME OF COMPANY" in frame.columns else None
            return [
                (row["SYMBOL"], str(row[name_col]).strip() if name_col else row["SYMBOL"])
                for _, row in frame.iterrows()
            ]
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not download NSE EQ list: {last_error}")


def fetch_chart(symbol, period, interval, min_rows=50):
    url = YAHOO_CHART.format(requests.utils.quote(symbol, safe=""))
    params = {"range": period, "interval": interval, "events": "history"}
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if response.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            response.raise_for_status()
            chart = response.json().get("chart", {})
            if chart.get("error") or not chart.get("result"):
                return None
            result = chart["result"][0]
            quote = result["indicators"]["quote"][0]
            frame = pd.DataFrame({
                "date": pd.to_datetime(result["timestamp"], unit="s", utc=True),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
            }).dropna()
            frame = frame.sort_values("date").reset_index(drop=True)
            return frame if len(frame) >= min_rows else None
        except Exception:
            if attempt < 2:
                time.sleep(1 + attempt)
    return None


def classify_close_direction(frame):
    """Compare only the last two fully closed candles by CLOSE; no EMA is used."""
    if frame is None or len(frame) < 2:
        return "DATA NOT AVAILABLE"
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return "DATA NOT AVAILABLE"
    previous_close = float(closes.iloc[-2])
    latest_close = float(closes.iloc[-1])
    if latest_close > previous_close:
        return "UPTREND"
    if latest_close < previous_close:
        return "DOWNTREND"
    return "SIDEWAYS"


def keep_only_closed_daily_bars(frame, now):
    """Daily Yahoo bars are dated by session; today's bar is usable only after NSE close."""
    if frame is None or frame.empty:
        return frame
    local_dates = frame["date"].dt.tz_convert("Asia/Kolkata").dt.date
    today = now.date()
    include_today = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
    mask = (local_dates < today) | ((local_dates == today) & include_today)
    return frame.loc[mask].copy().reset_index(drop=True)


def make_period_bars(daily_frame, rule, now, timeframe):
    if daily_frame is None or daily_frame.empty:
        return None
    indexed = daily_frame.set_index("date")
    bars = indexed.resample(rule).agg({
        "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    if bars.empty:
        return bars

    local_period_dates = bars["date"].dt.tz_convert("Asia/Kolkata")
    if timeframe == "MONTHLY":
        # The current calendar month is never treated as a completed monthly candle.
        bars = bars.loc[
            (local_period_dates.dt.year < now.year)
            | ((local_period_dates.dt.year == now.year) & (local_period_dates.dt.month < now.month))
        ]
    elif timeframe == "WEEKLY":
        # Include this week's candle only after Friday's NSE session has closed.
        week_is_closed = now.weekday() > 4 or (now.weekday() == 4 and (now.hour > 15 or (now.hour == 15 and now.minute >= 30)))
        current_week = now.isocalendar()[:2]
        week_keys = local_period_dates.apply(lambda d: (d.isocalendar().year, d.isocalendar().week))
        if not week_is_closed:
            bars = bars.loc[week_keys != current_week]
    return bars.reset_index(drop=True)


def keep_only_closed_hourly_bars(frame, now):
    """Keep only completed 60-minute bars, including NSE's final 15:15-15:30 bar."""
    if frame is None or frame.empty:
        return frame
    local_starts = frame["date"].dt.tz_convert("Asia/Kolkata")
    completed = (local_starts + pd.Timedelta(hours=1)) <= now
    final_nse_bar = (
        (local_starts.dt.hour == 15) & (local_starts.dt.minute == 15)
        & (now.hour > 15 or (now.hour == 15 and now.minute >= 30))
    )
    return frame.loc[completed | final_nse_bar].copy().reset_index(drop=True)


def scan_symbol(item):
    symbol, company = item
    now = now_ist()
    daily_raw = fetch_chart(symbol, "5y", "1d", min_rows=20)
    if daily_raw is None:
        return {
            "symbol": symbol, "company": company,
            "MONTHLY": "DATA NOT AVAILABLE", "WEEKLY": "DATA NOT AVAILABLE",
            "DAILY": "DATA NOT AVAILABLE", "1 HOUR": "DATA NOT AVAILABLE",
        }

    daily_closed = keep_only_closed_daily_bars(daily_raw, now)
    weekly_closed = make_period_bars(daily_closed, "W-FRI", now, "WEEKLY")
    monthly_closed = make_period_bars(daily_closed, "ME", now, "MONTHLY")

    hourly_raw = fetch_chart(symbol, "730d", "60m", min_rows=2)
    hourly_closed = keep_only_closed_hourly_bars(hourly_raw, now)

    return {
        "symbol": symbol,
        "company": company,
        "MONTHLY": classify_close_direction(monthly_closed),
        "WEEKLY": classify_close_direction(weekly_closed),
        "DAILY": classify_close_direction(daily_closed),
        "1 HOUR": classify_close_direction(hourly_closed),
    }




def split_telegram_message(message, max_length=3500):
    chunks, current = [], ""
    for line in message.splitlines():
        while len(line) > max_length:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:max_length])
            line = line[max_length:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > max_length:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram not sent: bot token/chat ID secret missing.")
        return False
    chunks = split_telegram_message(message)
    for index, chunk in enumerate(chunks, 1):
        text_to_send = f"[Part {index}/{len(chunks)}]\n{chunk}" if len(chunks) > 1 else chunk
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text_to_send, "disable_web_page_preview": True},
                timeout=TIMEOUT,
            )
            if not response.ok or not response.json().get("ok"):
                print(f"Telegram error part {index}/{len(chunks)}: HTTP {response.status_code} {response.text[:400]}")
                return False
            print(f"Telegram part delivered: {index}/{len(chunks)}")
        except Exception as exc:
            print(f"Telegram delivery failed: {exc}")
            return False
        if index < len(chunks):
            time.sleep(1)
    return True


def main():
    started = now_ist()
    print(f"NSE MULTI-TIMEFRAME TREND SCANNER | {started:%Y-%m-%d %H:%M:%S %Z}")
    print("Trend rule: compare CLOSE of the last two fully closed candles only; higher = UPTREND, lower = DOWNTREND, equal = SIDEWAYS. No EMA.")
    print("Timeframes: Monthly, Weekly, Daily, 1 Hour. This scanner is separate from the Daily 6/6 swing scanner.")
    universe = get_nse_universe()
    print(f"NSE EQ symbols downloaded: {len(universe)}")
    results, errors = [], 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(scan_symbol, item): item[0] for item in universe}
        for count, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                errors += 1
                print(f"ERROR {symbol}: {exc}")
            if count % 100 == 0:
                print(f"Progress: {count}/{len(universe)} | scanned={len(results)} | errors={errors}")
    results.sort(key=lambda x: x["symbol"])
    # One consolidated row per stock: show all four timeframe directions together.
    for row in results:
        states = [row.get(tf, "DATA NOT AVAILABLE") for tf in ["MONTHLY", "WEEKLY", "DAILY", "1 HOUR"]]
        if all(state == "UPTREND" for state in states):
            row["ALIGNMENT"] = "4/4 UPTREND"
        elif all(state == "DOWNTREND" for state in states):
            row["ALIGNMENT"] = "4/4 DOWNTREND"
        elif any(state == "DATA NOT AVAILABLE" for state in states):
            row["ALIGNMENT"] = "INCOMPLETE DATA"
        else:
            row["ALIGNMENT"] = "MIXED / SIDEWAYS"

    output = pd.DataFrame(results, columns=["symbol", "company", "MONTHLY", "WEEKLY", "DAILY", "1 HOUR", "ALIGNMENT"])
    output.to_csv("nse_timeframe_trends.csv", index=False)

    all_up = [x["symbol"] for x in results if x.get("ALIGNMENT") == "4/4 UPTREND"]
    all_down = [x["symbol"] for x in results if x.get("ALIGNMENT") == "4/4 DOWNTREND"]

    # Final scanner output contains only stocks aligned in the same direction
    # across Monthly, Weekly, Daily and 1 Hour. Mixed/sideways/incomplete are excluded.
    aligned = [x for x in results if x.get("ALIGNMENT") in ("4/4 UPTREND", "4/4 DOWNTREND")]
    pd.DataFrame(
        aligned,
        columns=["symbol", "company", "MONTHLY", "WEEKLY", "DAILY", "1 HOUR", "ALIGNMENT"],
    ).to_csv("nse_timeframe_trends.csv", index=False)

    lines = [
        "NSE MULTI-TIMEFRAME TREND REPORT",
        f"Date: {now_ist():%d-%m-%Y %H:%M IST}",
        f"Universe: {len(universe)} NSE EQ symbols | scanned rows: {len(results)} | errors: {errors}",
        "Rule: only last two fully closed candle CLOSE values are compared; no EMA and no unfinished candles.",
        "Only stocks with all FOUR timeframes agreeing are shown. Mixed, sideways and incomplete-data stocks are excluded.",
        f"4/4 UPTREND (Monthly + Weekly + Daily + 1 Hour): {len(all_up)}",
        "Stocks: " + (", ".join(all_up) if all_up else "None"),
        "",
        f"4/4 DOWNTREND (Monthly + Weekly + Daily + 1 Hour): {len(all_down)}",
        "Stocks: " + (", ".join(all_down) if all_down else "None"),
        "",
        "CSV artifact contains only these 4/4 aligned UPTREND and DOWNTREND stocks.",
    ]
    message = "\n".join(lines)
    print(message)
    delivered = send_telegram(message)
    print(f"Telegram delivered: {delivered}")
    print(f"Finished: {now_ist():%Y-%m-%d %H:%M:%S %Z}; errors={errors}; rows={len(results)}")


if __name__ == "__main__":
    main()
