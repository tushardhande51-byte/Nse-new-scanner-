import os
import re
import time
from datetime import datetime, timezone

import requests
import pandas as pd
from bs4 import BeautifulSoup

SCREENER_URL = "https://www.screener.in/screens/4008468/tushar-dhande/"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
VOLUME_LOOKBACK = 20
VOLUME_MULTIPLIER = 1.5
RESISTANCE_LOOKBACK = 20
RESISTANCE_TOLERANCE = 0.98

STOPLOSS_PCT = 0.05
TARGET_PCT = 0.10

REQUEST_TIMEOUT = 20
SLEEP_BETWEEN_REQUESTS = 0.15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    )
}


def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def test_internet(session):
    try:
        response = session.get("https://www.google.com", timeout=REQUEST_TIMEOUT)
        print(f"Internet test: HTTP {response.status_code}")
        return response.ok
    except Exception as exc:
        print(f"Internet test failed: {exc}")
        return False


def extract_symbol_from_row(row):
    link = row.find("a")
    if not link:
        return None, None

    name = link.get_text(" ", strip=True)
    href = link.get("href", "")

    match = re.search(r"/company/([^/]+)/", href)
    if match:
        slug = match.group(1).strip().upper()
    else:
        slug = None

    return name, slug


def get_screener_stocks(session):
    print("")
    print("========================================")
    print("STAGE 1 - SCREENER FUNDAMENTAL SCREEN")
    print("========================================")
    print(f"URL: {SCREENER_URL}")

    try:
        response = session.get(
            SCREENER_URL,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        print(f"Screener HTTP: {response.status_code}")

        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.select_one("table.data-table")

        if not table:
            print("Screener table not found.")
            return []

        stocks = []
        seen = set()

        for row in table.select("tbody tr"):
            name, symbol = extract_symbol_from_row(row)

            if not name or not symbol:
                continue

            key = symbol.upper()
            if key in seen:
                continue

            seen.add(key)
            stocks.append({
                "name": name,
                "symbol": key,
            })

        print(f"Fundamental stocks found: {len(stocks)}")
        return stocks

    except Exception as exc:
        print(f"Screener error: {exc}")
        return []


def prepare_nse_stocks(stocks):
    print("")
    print("========================================")
    print("PREPARING NSE SYMBOLS")
    print("========================================")

    valid = []
    skipped_numeric = []

    for item in stocks:
        symbol = item["symbol"].strip().upper()

        # Screener can expose BSE security codes such as 532015.
        # Yahoo Finance cannot use these directly as NSE tickers.
        if symbol.isdigit():
            skipped_numeric.append(symbol)
            print(f"SKIP BSE CODE: {symbol}")
            continue

        if not re.fullmatch(r"[A-Z0-9&._-]+", symbol):
            print(f"SKIP INVALID SYMBOL: {symbol}")
            continue

        item = dict(item)
        item["yahoo_symbol"] = f"{symbol}.NS"
        valid.append(item)

    print(f"Valid NSE-style symbols: {len(valid)}")
    print(f"Numeric BSE codes skipped: {len(skipped_numeric)}")
    return valid


def yahoo_chart_url(yahoo_symbol):
    return (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{yahoo_symbol}?range=1y&interval=1d&events=history"
    )


def get_price_data(session, yahoo_symbol):
    try:
        response = session.get(
            yahoo_chart_url(yahoo_symbol),
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            print(f"{yahoo_symbol} -> Yahoo HTTP {response.status_code}")
            return None

        payload = response.json()
        chart = payload.get("chart", {})
        result = chart.get("result")

        if not result:
            print(f"{yahoo_symbol} -> no Yahoo result")
            return None

        result = result[0]
        timestamps = result.get("timestamp", [])
        quote_list = result.get("indicators", {}).get("quote", [])

        if not timestamps or not quote_list:
            print(f"{yahoo_symbol} -> no OHLC data")
            return None

        quote = quote_list[0]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        })

        if df.empty:
            return None

        df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.drop(columns=["timestamp"])
        df = df.dropna(subset=["close", "high", "low", "volume"])
        df = df.sort_values("date").reset_index(drop=True)

        if len(df) < 100:
            print(f"{yahoo_symbol} -> insufficient data: {len(df)} rows")
            return None

        return df

    except Exception as exc:
        print(f"{yahoo_symbol} -> data error: {exc}")
        return None


def calculate_rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))

    # Handle periods with no losses.
    rsi = rsi.fillna(100)
    return rsi


def add_indicators(df):
    data = df.copy()

    data["ema20"] = data["close"].ewm(
        span=EMA_FAST,
        adjust=False,
    ).mean()

    data["ema50"] = data["close"].ewm(
        span=EMA_SLOW,
        adjust=False,
    ).mean()

    data["rsi14"] = calculate_rsi(data["close"], RSI_PERIOD)

    data["volume_avg20"] = data["volume"].rolling(
        VOLUME_LOOKBACK
    ).mean()

    # Previous 20-day high excludes today's candle.
    data["previous_20_high"] = data["high"].shift(1).rolling(
        RESISTANCE_LOOKBACK
    ).max()

    return data


def check_six_filters(df):
    if df is None or len(df) < 100:
        return None

    data = add_indicators(df)
    latest = data.iloc[-1]

    required = [
        latest["close"],
        latest["ema20"],
        latest["ema50"],
        latest["rsi14"],
        latest["volume"],
        latest["volume_avg20"],
        latest["previous_20_high"],
    ]

    if any(pd.isna(value) for value in required):
        return None

    close = float(latest["close"])
    ema20 = float(latest["ema20"])
    ema50 = float(latest["ema50"])
    rsi = float(latest["rsi14"])
    volume = float(latest["volume"])
    volume_avg20 = float(latest["volume_avg20"])
    previous_20_high = float(latest["previous_20_high"])

    filters = {
        "Trend": close > ema20 and ema20 > ema50,
        "EMA": close > ema20,
        "RSI": 55 <= rsi <= 70,
        "Volume": volume > volume_avg20 * VOLUME_MULTIPLIER,
        "Resistance": close >= previous_20_high * RESISTANCE_TOLERANCE,
        "Breakout": close > previous_20_high,
    }

    passed = sum(filters.values())

    if passed != 6:
        return {
            "passed": passed,
            "filters": filters,
            "close": close,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "volume": volume,
            "volume_avg20": volume_avg20,
            "previous_20_high": previous_20_high,
        }

    entry = close
    stoploss = entry * (1 - STOPLOSS_PCT)
    target = entry * (1 + TARGET_PCT)

    return {
        "passed": 6,
        "filters": filters,
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "volume": volume,
        "volume_avg20": volume_avg20,
        "previous_20_high": previous_20_high,
        "entry": entry,
        "stoploss": stoploss,
        "target": target,
    }


def price_data_test(session, stocks, count=5):
    print("")
    print("========================================")
    print("PRICE DATA TEST")
    print("========================================")

    if not stocks:
        print("No valid stocks to test.")
        return 0

    test_stocks = stocks[:count]
    success = 0

    for item in test_stocks:
        symbol = item["yahoo_symbol"]
        df = get_price_data(session, symbol)

        if df is not None and not df.empty:
            success += 1
            print(f"{symbol} -> OK ({len(df)} rows)")
        else:
            print(f"{symbol} -> FAILED")

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    print(f"Price data test: {success}/{len(test_stocks)}")
    return success


def scan_stocks(session, stocks):
    print("")
    print("========================================")
    print("STAGE 2 - TECHNICAL 6/6 SCAN")
    print("========================================")

    results = []
    total = len(stocks)

    for index, item in enumerate(stocks, start=1):
        name = item["name"]
        symbol = item["symbol"]
        yahoo_symbol = item["yahoo_symbol"]

        print(f"[{index}/{total}] {symbol}")

        df = get_price_data(session, yahoo_symbol)

        if df is None:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            continue

        result = check_six_filters(df)

        if result is None:
            print(f"{symbol} -> insufficient indicator data")
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            continue

        print(
            f"{symbol} -> {result['passed']}/6 "
            f"(RSI {result['rsi']:.2f})"
        )

        if result["passed"] == 6:
            results.append({
                "name": name,
                "symbol": symbol,
                "entry": result["entry"],
                "stoploss": result["stoploss"],
                "target": result["target"],
                "rsi": result["rsi"],
            })

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    return results


def format_price(value):
    return f"â‚¹{value:,.2f}"


def build_telegram_message(results):
    today = datetime.now(timezone.utc).strftime("%d-%m-%Y")

    lines = [
        "ðŸš€ NSE SWING SCANNER",
        "",
        f"Date: {today}",
        "Fundamental: Screener",
        "Technical: 6/6 filters",
        "",
    ]

    if not results:
        lines.extend([
            "âŒ No 6/6 stock found.",
            "",
            "Filters:",
            "1. Close > EMA20 > EMA50",
            "2. Close > EMA20",
            "3. RSI 55-70",
            "4. Volume > 20D average Ã— 1.5",
            "5. Near previous 20D resistance",
            "6. Breakout above previous 20D high",
        ])
        return "\n".join(lines)

    lines.append(f"âœ… FINAL BUY COUNT: {len(results)}")
    lines.append("")

    for number, item in enumerate(results, start=1):
        lines.extend([
            f"{number}. {item['symbol']} - {item['name']}",
            f"Entry: {format_price(item['entry'])}",
            f"Stoploss: {format_price(item['stoploss'])}",
            f"Target: {format_price(item['target'])}",
            f"RSI: {item['rsi']:.2f}",
            "",
        ])

    return "\n".join(lines)


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are not configured.")
        print("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        print(f"Telegram HTTP: {response.status_code}")

        if response.ok:
            print("Telegram message sent successfully.")
            return True

        print(f"Telegram error: {response.text}")
        return False

    except Exception as exc:
        print(f"Telegram send error: {exc}")
        return False


def print_final_report(results):
    print("")
    print("========================================")
    print("FINAL TECHNICAL REPORT")
    print("========================================")

    if not results:
        print("No 6/6 stock found.")
        return

    print(f"FINAL BUY COUNT: {len(results)}")
    print("")

    for number, item in enumerate(results, start=1):
        print(f"{number}. {item['symbol']} - {item['name']}")
        print(f"   Entry    : {format_price(item['entry'])}")
        print(f"   Stoploss : {format_price(item['stoploss'])}")
        print(f"   Target   : {format_price(item['target'])}")
        print(f"   RSI      : {item['rsi']:.2f}")
        print("")


def main():
    print("========================================")
    print("NSE SWING SCANNER")
    print("========================================")
    print("Strategy: Fundamental + Technical 6/6")
    print("Timeframe: Daily")
    print("Capital calculation: OFF")
    print("Quantity calculation: OFF")
    print("Risk calculation: OFF")
    print("")

    session = get_session()

    if not test_internet(session):
        print("Internet connection failed. Stopping.")
        return

    fundamental_stocks = get_screener_stocks(session)

    if not fundamental_stocks:
        print("No fundamental stocks found. Stopping.")
        return

    nse_stocks = prepare_nse_stocks(fundamental_stocks)

    if not nse_stocks:
        print("No valid NSE symbols available. Stopping.")
        return

    test_success = price_data_test(session, nse_stocks, count=5)

    if test_success == 0:
        print("")
        print("No Yahoo price data available for the test symbols.")
        print("Technical scan stopped.")
        return

    results = scan_stocks(session, nse_stocks)

    print_final_report(results)

    telegram_message = build_telegram_message(results)
    send_telegram(telegram_message)

    print("")
    print("========================================")
    print("SCAN COMPLETED")
    print("========================================")


if __name__ == "__main__":
    main()
