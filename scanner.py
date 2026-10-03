print("========================================")
print("STARTING NSE SWING SCANNER")
print("========================================")

import os
import sys
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

SCREENER_URL = "https://www.screener.in/screens/4008468/tushar-dhande/"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# =========================================================
# 1. BASIC TEST
# =========================================================

print("Python version:", sys.version)
print("Pandas version:", pd.__version__)
print("Requests version:", requests.__version__)


# =========================================================
# 2. INTERNET TEST
# =========================================================

def internet_test():
    print("\n========================================")
    print("INTERNET TEST")
    print("========================================")

    try:
        r = requests.get(
            "https://www.google.com",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        print("Google status:", r.status_code)

    except Exception as e:
        print("Google FAILED:", e)


# =========================================================
# 3. SCREENER TEST
# =========================================================

def screener_test():
    print("\n========================================")
    print("SCREENER TEST")
    print("========================================")

    try:
        r = requests.get(
            SCREENER_URL,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        print("Screener status:", r.status_code)
        print("Screener response length:", len(r.text))

        if r.status_code == 200:
            print("SCREENER: OK")
            return True

        print("SCREENER: FAILED")
        return False

    except Exception as e:
        print("Screener FAILED:", e)
        return False


# =========================================================
# 4. GET FUNDAMENTAL STOCKS
# =========================================================

def get_screener_stocks():

    print("\n========================================")
    print("GETTING FUNDAMENTAL STOCKS")
    print("========================================")

    stocks = []

    for page in range(1, 20):

        try:

            url = SCREENER_URL

            if page > 1:
                url = SCREENER_URL + f"?page={page}"

            r = requests.get(
                url,
                timeout=20,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            print(
                f"Screener page {page}: "
                f"status={r.status_code}"
            )

            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")

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

                href = link.get("href", "")

                if "/company/" not in href:
                    continue

                symbol = href.split("/company/")[1].split("/")[0]

                if symbol:

                    stocks.append({
                        "name": name,
                        "symbol": symbol
                    })

        except Exception as e:

            print(
                f"Screener page {page} ERROR:",
                e
            )

    # Remove duplicates

    unique = {}

    for stock in stocks:

        symbol = stock["symbol"]

        if symbol not in unique:
            unique[symbol] = stock

    stocks = list(unique.values())

    print("\n========================================")
    print("FUNDAMENTAL RESULT")
    print("========================================")
    print("Stocks found:", len(stocks))

    if stocks:

        print("\nFirst 10 stocks:")

        for stock in stocks[:10]:

            print(
                stock["symbol"],
                "|",
                stock["name"]
            )

    return stocks


# =========================================================
# 5. YAHOO PRICE DATA
# =========================================================

def get_price_data(symbol):

    yahoo_symbol = symbol

    if yahoo_symbol.endswith(".NS"):
        yahoo_symbol = yahoo_symbol[:-3]

    if yahoo_symbol.endswith(".BO"):
        yahoo_symbol = yahoo_symbol[:-3]

    yahoo_symbol = yahoo_symbol + ".NS"

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
            headers={
                "User-Agent":
                "Mozilla/5.0"
            }
        )

        if r.status_code != 200:

            print(
                f"{symbol} -> Yahoo HTTP {r.status_code}"
            )

            return None

        data = r.json()

        result = data.get("chart", {}).get("result")

        if not result:

            print(
                f"{symbol} -> No Yahoo result"
            )

            return None

        result = result[0]

        timestamps = result.get(
            "timestamp",
            []
        )

        quote = result.get(
            "indicators",
            {}
        ).get(
            "quote",
            []
        )

        if not timestamps or not quote:

            print(
                f"{symbol} -> Empty price data"
            )

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
                f"{symbol} -> Only {len(df)} rows"
            )

            return None

        return df

    except Exception as e:

        print(
            f"{symbol} -> PRICE ERROR:",
            e
        )

        return None


# =========================================================
# 6. PRICE DATA TEST
# =========================================================

def price_data_test(stocks):

    print("\n========================================")
    print("PRICE DATA TEST")
    print("========================================")

    test_stocks = stocks[:5]

    success = 0

    for stock in test_stocks:

        symbol = stock["symbol"]

        print(
            f"\nTesting {symbol}..."
        )

        df = get_price_data(symbol)

        if df is not None:

            success += 1

            latest = df.iloc[-1]["close"]

            print(
                f"OK | Rows: {len(df)} | "
                f"Latest close: {latest}"
            )

        else:

            print("FAILED")

        time.sleep(1)

    print("\n----------------------------------------")
    print(
        f"Price data test: "
        f"{success}/{len(test_stocks)}"
    )
    print("----------------------------------------")

    return success


# =========================================================
# 7. TECHNICAL 6/6
# =========================================================

def technical_check(df):

    try:

        df = df.copy()

        # EMA

        df["EMA20"] = (
            df["close"]
            .ewm(span=20, adjust=False)
            .mean()
        )

        df["EMA50"] = (
            df["close"]
            .ewm(span=50, adjust=False)
            .mean()
        )

        # RSI

        delta = df["close"].diff()

        gain = delta.clip(lower=0)

        loss = -delta.clip(upper=0)

        avg_gain = (
            gain.rolling(14)
            .mean()
        )

        avg_loss = (
            loss.rolling(14)
            .mean()
        )

        rs = avg_gain / avg_loss

        df["RSI"] = (
            100 -
            (100 / (1 + rs))
        )

        # Volume average

        df["VOL20"] = (
            df["volume"]
            .rolling(20)
            .mean()
        )

        # Previous 20-day high

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

        if pd.isna(
            ema20
        ) or pd.isna(
            ema50
        ) or pd.isna(
            rsi
        ) or pd.isna(
            vol20
        ) or pd.isna(
            prev20high
        ):

            return False, None

        # -------------------------------------------------
        # 6 FILTERS
        # -------------------------------------------------

        filter1 = (
            close >
            ema20 >
            ema50
        )

        filter2 = (
            close >
            ema20
        )

        filter3 = (
            55 <= rsi <= 70
        )

        filter4 = (
            volume >
            vol20 * 1.5
        )

        filter5 = (
            close >=
            prev20high * 0.98
        )

        filter6 = (
            close >
            prev20high
        )

        passed = (
            filter1 and
            filter2 and
            filter3 and
            filter4 and
            filter5 and
            filter6
        )

        if not passed:
            return False, None

        entry = float(close)

        stoploss = entry * 0.95

        target = entry * 1.10

        result = {
            "entry": entry,
            "stoploss": stoploss,
            "target": target,
            "rsi": float(rsi)
        }

        return True, result

    except Exception as e:

        print(
            "Technical error:",
            e
        )

        return False, None


# =========================================================
# 8. TELEGRAM
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
        f"https://api.telegram.org/"
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
# 9. MAIN SCANNER
# =========================================================

def main():

    print("\n========================================")
    print("NSE SWING SCANNER STARTED")
    print("========================================")

    internet_test()

    if not screener_test():

        print(
            "\nSTOP: Screener connection failed."
        )

        return

    stocks = get_screener_stocks()

    if not stocks:

        print(
            "\nSTOP: No fundamental stocks found."
        )

        return

    print(
        f"\nStocks to analyse: {len(stocks)}"
    )

    # Price data test

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
        print(
            "Technical scan NOT started."
        )

        send_telegram(
            "NSE Swing Scanner\n\n"
            "⚠️ Price data unavailable.\n"
            "Technical scan could not start."
        )

        return

    # -----------------------------------------------------
    # Technical scan
    # -----------------------------------------------------

    print("\n========================================")
    print("STARTING TECHNICAL 6/6 SCAN")
    print("========================================")

    final_results = []

    checked = 0

    for stock in stocks:

        symbol = stock["symbol"]

        checked += 1

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

            final_results.append({
                "symbol": symbol,
                "name": stock["name"],
                **result
            })

            print(
                ">>> 6/6 PASS"
            )

        time.sleep(0.2)

    # -----------------------------------------------------
    # FINAL RESULT
    # -----------------------------------------------------

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
                f"Target: ₹{stock['target']:.2f}\n"
                f"RSI: {stock['rsi']:.2f}\n\n"
            )

    else:

        message = (
            "NSE SWING SCANNER\n\n"
            "No stock passed all 6 technical filters today."
        )

    send_telegram(message)

    print("\n========================================")
    print("SCANNER FINISHED")
    print("========================================")


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
