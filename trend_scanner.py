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


def classify_trend(frame):
    """EMA trend: UP = Close > EMA20 > EMA50; DOWN = Close < EMA20 < EMA50."""
    if frame is None or len(frame) < 55:
        return "DATA NOT AVAILABLE"
    close = frame["close"]
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    last_close = close.iloc[-1]
    if pd.isna(ema20) or pd.isna(ema50) or pd.isna(last_close):
        return "DATA NOT AVAILABLE"
    if last_close > ema20 > ema50:
        return "UPTREND"
    if last_close < ema20 < ema50:
        return "DOWNTREND"
    return "SIDEWAYS"


def scan_symbol(item):
    symbol, company = item
    daily_history = fetch_chart(symbol, "5y", "1d", min_rows=100)
    if daily_history is None:
        return {
            "symbol": symbol, "company": company,
            "MONTHLY": "DATA NOT AVAILABLE", "WEEKLY": "DATA NOT AVAILABLE",
            "DAILY": "DATA NOT AVAILABLE", "1 HOUR": "DATA NOT AVAILABLE",
        }
    indexed = daily_history.set_index("date")
    weekly = indexed.resample("W-FRI").agg({
        "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    monthly = indexed.resample("ME").agg({
        "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    hourly = fetch_chart(symbol, "730d", "60m", min_rows=55)
    return {
        "symbol": symbol,
        "company": company,
        "MONTHLY": classify_trend(monthly),
        "WEEKLY": classify_trend(weekly),
        "DAILY": classify_trend(daily_history),
        "1 HOUR": classify_trend(hourly),
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
    print("Trend rule: UP = Close > EMA20 > EMA50; DOWN = Close < EMA20 < EMA50; otherwise SIDEWAYS.")
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
    output = pd.DataFrame(results)
    output.to_csv("nse_timeframe_trends.csv", index=False)

    lines = [
        "NSE MULTI-TIMEFRAME TREND REPORT",
        f"Date: {now_ist():%d-%m-%Y %H:%M IST}",
        f"Universe: {len(universe)} NSE EQ symbols | scanned rows: {len(results)} | errors: {errors}",
        "Trend definition: UPTREND = Close > EMA20 > EMA50; DOWNTREND = Close < EMA20 < EMA50; otherwise SIDEWAYS.",
        "Note: current latest candle is used; trend can change as candles update.",
        "Full stock-wise report: download nse_timeframe_trends.csv from the GitHub Actions artifact.",
        "",
    ]
    for timeframe in ["MONTHLY", "WEEKLY", "DAILY", "1 HOUR"]:
        up = [x["symbol"] for x in results if x.get(timeframe) == "UPTREND"]
        down = [x["symbol"] for x in results if x.get(timeframe) == "DOWNTREND"]
        side = [x["symbol"] for x in results if x.get(timeframe) == "SIDEWAYS"]
        missing = sum(1 for x in results if x.get(timeframe) == "DATA NOT AVAILABLE")
        lines.extend([
            f"{timeframe}: UP {len(up)} | DOWN {len(down)} | SIDEWAYS {len(side)} | DATA N/A {missing}",
            "UPTREND stocks (first 30): " + (", ".join(up[:30]) if up else "None"),
            "DOWNTREND stocks (first 30): " + (", ".join(down[:30]) if down else "None"),
            "",
        ])
    message = "\n".join(lines)
    print(message)
    delivered = send_telegram(message)
    print(f"Telegram delivered: {delivered}")
    print(f"Finished: {now_ist():%Y-%m-%d %H:%M:%S %Z}; errors={errors}; rows={len(results)}")


if __name__ == "__main__":
    main()
