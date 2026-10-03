print("========================================")
print("STARTING NSE SWING SCANNER")
print("========================================")

import os
import sys
import time
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup

SCREENER_URL = "https://www.screener.in/screens/4008468/tushar-dhande/"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140 Safari/537.36"
    )
}


# =========================================================
# BASIC TEST
# =========================================================

print("Python version:", sys.version)
print("Pandas version:", pd.__version__)
print("Requests version:", requests.__version__)


# =========================================================
# INTERNET TEST
# =========================================================

def internet_test():

    print("\n========================================")
    print("INTERNET TEST")
    print("========================================")

    try:

        r = requests.get(
            "https://www.google.com",
            timeout=15,
            headers=HEADERS
        )

        print("Google status:", r.status_code)

    except Exception as e:

        print("Google FAILED:", e)


# =========================================================
# SCREENER TEST
# =========================================================

def screener_test():

    print("\n========================================")
    print("SCREENER TEST")
    print("========================================")

    try:

        r = requests.get(
            SCREENER_URL,
            timeout=20,
            headers=HEADERS
        )

        print("Screener status:", r.status_code)
        print("Screener response length:", len(r.text))

        return r.status_code == 200

    except Exception as e:

        print("Screener FAILED:", e)

        return False


# =========================================================
# GET FUNDAMENTAL STOCKS
# =========================================================

def get_screener_stocks():

    print("\n========================================")
    print("GETTING FUNDAMENTAL STOCKS")
    print("========================================")

    stocks = []

    for page in range(1, 20):

        try:

            if page == 1:
                url = SCREENER_URL
            else:
                url = SCREENER_URL + f"?page={page}"

            r = requests.get(
                url,
                timeout=20,
                headers=HEADERS
            )

            print(
                f"Screener page {page}: "
                f"status={r.status_code}"
            )

            if r.status_code != 200:
                continue

            soup = BeautifulSoup(
                r.text,
                "html.parser"
            )

            rows = soup.select(
                "table.data-table tbody tr"
            )

            for row in rows:

                link = row.select_one(
                    "a[href*='/company/']"
                )

                if not link:
                    continue

                name = link.get_text(
                    " ",
                    strip=True
                )

                href = link.get(
                    "href",
                    ""
                )

                match = re.search(
                    r"/company/([^/]+)",
                    href
                )

                if not match:
                    continue

                screener_symbol = match.group(1)

                stocks.append({
                    "name": name,
                    "symbol": screener_symbol,
                    "url": "https://www.screener.in" + href
                })

        except Exception as e:

            print(
                f"Screener page {page} ERROR:",
                e
            )

    # Remove duplicate symbols

    unique = {}

    for stock in stocks:

        key = stock["url"]

        if key not in unique:
            unique[key] = stock

    stocks = list(unique.values())

    print("\n========================================")
    print("FUNDAMENTAL RESULT")
    print("========================================")

    print(
        "Stocks found:",
        len(stocks)
    )

    for stock in stocks[:10]:

        print(
            stock["symbol"],
            "|",
            stock["name"]
        )

    return stocks


# =========================================================
# RESOLVE SCREENER SYMBOL
# =========================================================

def resolve_symbol(stock):

    """
    Screener URL ko open karke actual company page se
    symbol identify karta hai.

    Numeric BSE codes ko direct Yahoo me nahi bhejega.
    """

    symbol = stock["symbol"]

    # Already normal NSE-looking symbol
    if not symbol.isdigit():

        return symbol

    print(
        f"Resolving numeric code: {symbol}"
    )

    try:

        r = requests.get(
            stock["url"],
            timeout=15,
            headers=HEADERS
        )

        if r.status_code != 200:

            print(
                f"{symbol} -> Screener page HTTP "
                f"{r.status_code}"
            )

            return None

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        # Look for NSE links
        for a in soup.find_all("a"):

            href = a.get(
                "href",
                ""
            )

            text = a.get_text(
                " ",
                strip=True
            ).upper()

            if "NSE" not in text:
                continue

            # Try extracting symbol from NSE URL
            patterns = [
                r"/NSE:([A-Z0-9&-]+)",
                r"NSE%3A([A-Z0-9&-]+)",
                r"NSE:([A-Z0-9&-]+)"
            ]

            for pattern in patterns:

                match = re.search(
                    pattern,
                    href.upper()
                )

                if match:

                    resolved = match.group(1)

                    print(
                        f"{symbol} -> "
                        f"{resolved}"
                    )

                    return resolved

        # Try page text around NSE
        page_text = soup.get_text(
            " ",
            strip=True
        )

        match = re.search(
            r"NSE\s*[:\-]?\s*([A-Z][A-Z0-9&-]{1,20})",
            page_text.upper()
        )

        if match:

            resolved = match.group(1)

            print(
                f"{symbol} -> "
                f"{resolved}"
            )

            return resolved

        print(
            f"{symbol} -> NSE symbol not found"
        )

        return None

    except Exception as e:

        print(
            f"{symbol} -> resolve ERROR:",
            e
        )

        return None


# =========================================================
# PREPARE NSE SYMBOLS
# =========================================================

def prepare_nse_stocks(stocks):

    print("\n========================================")
    print("PREPARING NSE SYMBOLS")
    print("========================================")

    valid = []

    skipped = 0

    for i, stock in enumerate(
        stocks,
        start=1
    ):

        original = stock["symbol"]

        # Normal Screener symbol
        if not original.isdigit():

            stock["nse_symbol"] = original

            valid.append(stock)

            continue

        # Numeric BSE code
        resolved = resolve_symbol(
            stock
        )

        if resolved:

            stock["nse_symbol"] = resolved

            valid.append(stock)

        else:

            skipped += 1

        # Avoid hitting Screener too quickly
        time.sleep(0.15)

    print("\n----------------------------------------")
    print(
        "Valid NSE stocks:",
        len(valid)
    )
    print(
        "Skipped unresolved:",
        skipped
    )
    print("----------------------------------------")

    return valid


# =========================================================
# YAHOO PRICE DATA
# =========================================================

def get_price_data(symbol):

    yahoo_symbol = symbol.upper()

    if yahoo_symbol.endswith(".NS"):
        yahoo_symbol = yahoo_symbol[:-3]

    if yahoo_symbol.endswith(".BO"):
        yahoo_symbol = yahoo_symbol[:-3]

    # Reject numeric BSE codes
    if yahoo_symbol.isdigit():

        print(
            f"{symbol} -> numeric code skipped"
        )

        return None

    yahoo_symbol += ".NS"

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + yahoo_symbol
    )

    params = {
        "range": "6mo",
        "interval": "1d"
    }

    try:

        r = requests.get(
            url,
            params=params,
            timeout=20,
            headers=HEADERS
        )

        if r.status_code != 200:

            print(
                f"{symbol} -> "
                f"{yahoo_symbol} -> "
                f"Yahoo HTTP {r.status_code}"
            )

            return None

        data = r.json()

        result = (
            data
            .get("chart", {})
            .get("result")
        )

        if not result:

            print(
                f"{symbol} -> "
                f"{yahoo_symbol} -> "
                "No Yahoo result"
            )

            return None

        result = result[0]

        timestamps = result.get(
            "timestamp",
            []
        )

        quote = (
            result
            .get("indicators", {})
            .get("quote", [])
        )

        if not timestamps or not quote:

            return None

        quote = quote[0]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume")
        })

        df["date"] = pd.to_datetime(
            df["timestamp"],
            unit="s"
        )

        df = df.dropna(
            subset=[
                "close",
                "high",
                "volume"
            ]
        )

        if len(df) < 60:

            print(
                f"{symbol} -> "
                f"Only {len(df)} rows"
            )

            return None

        return df

    except Exception as e:

        print(
            f"{symbol} -> "
            f"PRICE ERROR:",
            e
        )

        return None


# =========================================================
# PRICE DATA TEST
# =========================================================

def price_data_test(stocks):

    print("\n========================================")
    print("PRICE DATA TEST")
    print("========================================")

    test_stocks = stocks[:5]

    success = 0

    for stock in test_stocks:

        symbol = stock["nse_symbol"]

        print(
            f"\nTesting {symbol}..."
        )

        df = get_price_data(
            symbol
        )

        if df is not None:

            success += 1

            latest = df.iloc[-1]["close"]

            print(
                f"OK | Rows: {len(df)} | "
                f"Latest close: {latest}"
            )

        else:

            print("FAILED")

        time.sleep(0.5)

    print("\n----------------------------------------")
    print(
        f"Price data test: "
        f"{success}/{len(test_stocks)}"
    )
    print("----------------------------------------")

    return success


# =========================================================
# TECHNICAL 6/6
# =========================================================

def technical_check(df):

    try:

        df = df.copy()

        # 1. EMA20
        df["EMA20"] = (
            df["close"]
            .ewm(
                span=20,
                adjust=False
            )
            .mean()
        )

        # EMA50
        df["EMA50"] = (
            df["close"]
            .ewm(
                span=50,
                adjust=False
            )
            .mean()
        )

        # 2. RSI14

        delta = df["close"].diff()

        gain = delta.clip(
            lower=0
        )

        loss = -delta.clip(
            upper=0
        )

        avg_gain = (
            gain
            .rolling(14)
            .mean()
        )

        avg_loss = (
            loss
            .rolling(14)
            .mean()
        )

        rs = (
            avg_gain /
            avg_loss
        )

        df["RSI"] = (
            100 -
            (
                100 /
                (1 + rs)
            )
        )

        # 3. Volume

        df["VOL20"] = (
            df["volume"]
            .rolling(20)
            .mean()
        )

        # 4. Previous 20 day high

        df["PREV20HIGH"] = (
            df["high"]
            .shift(1)
            .rolling(20)
            .max()
        )

        latest = df.iloc[-1]

        close = latest["close"]

        ema20 = latest["EMA20"]

        ema50 = latest["EMA50"]

        rsi = latest["RSI"]

        volume = latest["volume"]

        vol20 = latest["VOL20"]

        prev20high = latest["PREV20HIGH"]

        if any(
            pd.isna(x)
            for x in [
                close,
                ema20,
                ema50,
                rsi,
                volume,
                vol20,
                prev20high
            ]
        ):

            return False, None

        # =================================================
        # SIX FILTERS
        # =================================================

        # FILTER 1
        trend = (
            close >
            ema20 >
            ema50
        )

        # FILTER 2
        ema = (
            close >
            ema20
        )

        # FILTER 3
        rsi_filter = (
            55 <= rsi <= 70
        )

        # FILTER 4
        volume_filter = (
            volume >
            vol20 * 1.5
        )

        # FILTER 5
        resistance = (
            close >=
            prev20high * 0.98
        )

        # FILTER 6
        breakout = (
            close >
            prev20high
        )

        passed = all([
            trend,
            ema,
            rsi_filter,
            volume_filter,
            resistance,
            breakout
        ])

        if not passed:

            return False, None

        # Trade levels

        entry = float(close)

        stoploss = (
            entry * 0.95
        )

        target = (
            entry * 1.10
        )

        return True, {
            "entry": entry,
            "stoploss": stoploss,
            "target": target,
            "rsi": float(rsi)
        }

    except Exception as e:

        print(
            "Technical error:",
            e
        )

        return False, None


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    print("\n========================================")
    print("TELEGRAM")
    print("========================================")

    if not TELEGRAM_BOT_TOKEN:

        print(
            "TELEGRAM_BOT_TOKEN missing"
        )

        return

    if not TELEGRAM_CHAT_ID:

        print(
            "TELEGRAM_CHAT_ID missing"
        )

        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        r = requests.post(
            url,
            data=payload,
            timeout=20
        )

        print(
            "Telegram status:",
            r.status_code
        )

        print(
            "Telegram response:",
            r.text[:300]
        )

    except Exception as e:

        print(
            "Telegram ERROR:",
            e
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print("\n========================================")
    print("NSE SWING SCANNER STARTED")
    print("========================================")

    internet_test()

    if not screener_test():

        print(
            "STOP: Screener connection failed."
        )

        return

    # Stage 1
    stocks = get_screener_stocks()

    if not stocks:

        print(
            "STOP: No fundamental stocks."
        )

        return

    print(
        f"\nFundamental stocks: {len(stocks)}"
    )

    # Convert to valid NSE symbols
    stocks = prepare_nse_stocks(
        stocks
    )

    if not stocks:

        print(
            "STOP: No valid NSE symbols."
        )

        return

    # Price test
    success = price_data_test(
        stocks
    )

    if success == 0:

        print("\n========================================")
        print("STOP")
        print("========================================")

        print(
            "NO PRICE DATA RECEIVED."
        )

        send_telegram(
            "NSE Swing Scanner\n\n"
            "⚠️ Price data unavailable.\n"
            "Technical scan could not start."
        )

        return

    # =====================================================
    # TECHNICAL SCAN
    # =====================================================

    print("\n========================================")
    print("STARTING TECHNICAL 6/6 SCAN")
    print("========================================")

    final_results = []

    checked = 0

    for stock in stocks:

        checked += 1

        symbol = stock["nse_symbol"]

        print(
            f"[{checked}/{len(stocks)}] "
            f"{symbol}"
        )

        df = get_price_data(
            symbol
        )

        if df is None:

            continue

        passed, result = technical_check(
            df
        )

        if passed:

            print(
                f">>> {symbol} "
                f"6/6 PASS"
            )

            final_results.append({
                "symbol": symbol,
                "name": stock["name"],
                **result
            })

        time.sleep(0.25)

    # =====================================================
    # FINAL RESULT
    # =====================================================

    print("\n========================================")
    print("FINAL TECHNICAL 6/6")
    print("========================================")

    print(
        "FINAL BUY COUNT:",
        len(final_results)
    )

    if final_results:

        message = (
            "🚀 NSE SWING SCANNER\n\n"
            "6/6 TECHNICAL PASS\n\n"
        )

        for stock in final_results:

            message += (
                f"📌 {stock['symbol']}\n"
                f"Entry: ₹{stock['entry']:.2f}\n"
                f"Stoploss: ₹{stock['stoploss']:.2f}\n"
                f"Target: ₹{stock['target']:.2f}\n\n"
            )

    else:

        message = (
            "NSE SWING SCANNER\n\n"
            "No stock passed all 6 "
            "technical filters today."
        )

    send_telegram(message)

    print("\n========================================")
    print("SCANNER FINISHED")
    print("========================================")


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
