print("========================================")
print("STARTING NSE SWING SCANNER")
print("========================================")

import os
import sys
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup


# =========================================================
# SETTINGS
# =========================================================

SCREENER_URL = (
    "https://www.screener.in/screens/"
    "4008468/tushar-dhande/"
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


# =========================================================
# VERSION / BASIC TEST
# =========================================================

print(
    "Python:",
    sys.version.split()[0]
)

print(
    "Pandas:",
    pd.__version__
)

print(
    "Requests:",
    requests.__version__
)


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
            headers=HEADERS,
            timeout=15
        )

        print(
            "Google status:",
            r.status_code
        )

        if r.status_code == 200:

            print(
                "Internet: OK"
            )

            return True

        print(
            "Internet: FAILED"
        )

        return False

    except Exception as e:

        print(
            "Internet ERROR:",
            e
        )

        return False


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
            headers=HEADERS,
            timeout=20
        )

        print(
            "Screener status:",
            r.status_code
        )

        print(
            "Response length:",
            len(r.text)
        )

        if r.status_code == 200:

            print(
                "Screener: OK"
            )

            return True

        print(
            "Screener: FAILED"
        )

        return False

    except Exception as e:

        print(
            "Screener ERROR:",
            e
        )

        return False


# =========================================================
# GET FUNDAMENTAL STOCKS
# =========================================================

def get_screener_stocks():

    print("\n========================================")
    print("GETTING FUNDAMENTAL STOCKS")
    print("========================================")

    stocks = []

    # Screener currently returns approximately
    # 151 stocks across these pages.

    for page in range(1, 20):

        try:

            if page == 1:

                url = SCREENER_URL

            else:

                url = (
                    SCREENER_URL
                    + f"?page={page}"
                )

            r = requests.get(
                url,
                headers=HEADERS,
                timeout=20
            )

            print(
                f"Page {page}: "
                f"HTTP {r.status_code}"
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

            if not rows:

                continue

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

                if not href:

                    continue

                # Extract Screener company slug
                #
                # Example:
                # /company/SPARC/
                #
                parts = href.split(
                    "/company/"
                )

                if len(parts) < 2:

                    continue

                symbol = (
                    parts[1]
                    .split("/")[0]
                    .strip()
                )

                if not symbol:

                    continue

                stocks.append({
                    "name": name,
                    "symbol": symbol
                })

        except Exception as e:

            print(
                f"Page {page} ERROR:",
                e
            )

    # -----------------------------------------------------
    # REMOVE DUPLICATES
    # -----------------------------------------------------

    unique = {}

    for stock in stocks:

        symbol = stock["symbol"]

        if symbol not in unique:

            unique[symbol] = stock

    stocks = list(
        unique.values()
    )

    print("\n========================================")
    print("FUNDAMENTAL RESULT")
    print("========================================")

    print(
        "Total fundamental stocks:",
        len(stocks)
    )

    print(
        "\nFirst 15 stocks:"
    )

    for stock in stocks[:15]:

        print(
            stock["symbol"],
            "|",
            stock["name"]
        )

    return stocks


# =========================================================
# PREPARE NSE SYMBOLS
# =========================================================

def prepare_nse_stocks(stocks):

    print("\n========================================")
    print("PREPARING NSE SYMBOLS")
    print("========================================")

    valid = []

    skipped = []

    for stock in stocks:

        symbol = (
            stock["symbol"]
            .strip()
            .upper()
        )

        # -------------------------------------------------
        # NUMERIC SYMBOL = BSE SECURITY CODE
        # -------------------------------------------------

        if symbol.isdigit():

            print(
                f"SKIP BSE CODE: {symbol}"
            )

            skipped.append(symbol)

            continue

        # -------------------------------------------------
        # VALID SYMBOL
        # -------------------------------------------------

        stock["nse_symbol"] = symbol

        valid.append(stock)

    print("\n----------------------------------------")

    print(
        "Fundamental stocks:",
        len(stocks)
    )

    print(
        "Valid NSE-style symbols:",
        len(valid)
    )

    print(
        "Skipped numeric BSE codes:",
        len(skipped)
    )

    print("----------------------------------------")

    return valid


# =========================================================
# YAHOO PRICE DATA
# =========================================================

def get_price_data(symbol):

    symbol = (
        symbol
        .strip()
        .upper()
    )

    # Remove exchange suffix if present

    if symbol.endswith(".NS"):

        symbol = symbol[:-3]

    if symbol.endswith(".BO"):

        symbol = symbol[:-3]

    # Never query numeric BSE code

    if symbol.isdigit():

        return None

    yahoo_symbol = (
        symbol + ".NS"
    )

    url = (
        "https://query1.finance.yahoo.com"
        "/v8/finance/chart/"
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
            headers=HEADERS,
            timeout=20
        )

        if r.status_code != 200:

            print(
                f"{symbol} -> "
                f"Yahoo HTTP "
                f"{r.status_code}"
            )

            return None

        data = r.json()

        chart = data.get(
            "chart",
            {}
        )

        result = chart.get(
            "result"
        )

        if not result:

            print(
                f"{symbol} -> "
                "Yahoo no result"
            )

            return None

        result = result[0]

        timestamps = result.get(
            "timestamp",
            []
        )

        indicators = result.get(
            "indicators",
            {}
        )

        quotes = indicators.get(
            "quote",
            []
        )

        if not timestamps:

            return None

        if not quotes:

            return None

        quote = quotes[0]

        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": quote.get(
                "open"
            ),
            "high": quote.get(
                "high"
            ),
            "low": quote.get(
                "low"
            ),
            "close": quote.get(
                "close"
            ),
            "volume": quote.get(
                "volume"
            )
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

        # Need enough history for
        # EMA50 + RSI + 20-day calculations

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
            f"Yahoo ERROR: {e}"
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

    if not test_stocks:

        print(
            "No stocks available for test."
        )

        return 0

    success = 0

    for stock in test_stocks:

        symbol = stock[
            "nse_symbol"
        ]

        print(
            f"\nTesting "
            f"{symbol} -> "
            f"{symbol}.NS"
        )

        df = get_price_data(
            symbol
        )

        if df is not None:

            success += 1

            latest_close = (
                df.iloc[-1]["close"]
            )

            print(
                f"OK | "
                f"Rows: {len(df)} | "
                f"Latest close: "
                f"₹{latest_close:.2f}"
            )

        else:

            print(
                "FAILED"
            )

        time.sleep(0.5)

    print(
        "\n----------------------------------------"
    )

    print(
        f"Price data test: "
        f"{success}/{len(test_stocks)}"
    )

    print(
        "----------------------------------------"
    )

    return success


# =========================================================
# TECHNICAL 6/6 CHECK
# =========================================================

def technical_check(df):

    try:

        df = df.copy()

        # =================================================
        # EMA20
        # =================================================

        df["EMA20"] = (
            df["close"]
            .ewm(
                span=20,
                adjust=False
            )
            .mean()
        )

        # =================================================
        # EMA50
        # =================================================

        df["EMA50"] = (
            df["close"]
            .ewm(
                span=50,
                adjust=False
            )
            .mean()
        )

        # =================================================
        # RSI14
        # =================================================

        delta = (
            df["close"]
            .diff()
        )

        gain = (
            delta
            .clip(lower=0)
        )

        loss = (
            -delta
            .clip(upper=0)
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

        # =================================================
        # 20-DAY AVERAGE VOLUME
        # =================================================

        df["VOL20"] = (
            df["volume"]
            .rolling(20)
            .mean()
        )

        # =================================================
        # PREVIOUS 20-DAY HIGH
        # =================================================

        df["PREV20HIGH"] = (
            df["high"]
            .shift(1)
            .rolling(20)
            .max()
        )

        latest = df.iloc[-1]

        close = latest[
            "close"
        ]

        ema20 = latest[
            "EMA20"
        ]

        ema50 = latest[
            "EMA50"
        ]

        rsi = latest[
            "RSI"
        ]

        volume = latest[
            "volume"
        ]

        vol20 = latest[
            "VOL20"
        ]

        prev20high = latest[
            "PREV20HIGH"
        ]

        values = [
            close,
            ema20,
            ema50,
            rsi,
            volume,
            vol20,
            prev20high
        ]

        if any(
            pd.isna(x)
            for x in values
        ):

            return False, None

        # =================================================
        # 6 FILTERS
        # =================================================

        # FILTER 1
        # Trend:
        # Close > EMA20 > EMA50

        filter1 = (
            close >
            ema20 >
            ema50
        )

        # FILTER 2
        # EMA:
        # Close > EMA20

        filter2 = (
            close >
            ema20
        )

        # FILTER 3
        # RSI:
        # 55 to 70

        filter3 = (
            55 <=
            rsi <=
            70
        )

        # FILTER 4
        # Volume:
        # Today > 1.5x 20-day average

        filter4 = (
            volume >
            vol20 * 1.5
        )

        # FILTER 5
        # Resistance:
        # Within 2% of previous 20-day high

        filter5 = (
            close >=
            prev20high * 0.98
        )

        # FILTER 6
        # Breakout:
        # Close above previous 20-day high

        filter6 = (
            close >
            prev20high
        )

        # =================================================
        # FINAL 6/6
        # =================================================

        passed = all([
            filter1,
            filter2,
            filter3,
            filter4,
            filter5,
            filter6
        ])

        if not passed:

            return False, None

        # =================================================
        # TRADE LEVELS
        # =================================================

        entry = float(
            close
        )

        stoploss = (
            entry * 0.95
        )

        target = (
            entry * 1.10
        )

        result = {

            "entry": entry,

            "stoploss": stoploss,

            "target": target,

            "rsi": float(rsi)

        }

        return True, result

    except Exception as e:

        print(
            "Technical ERROR:",
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
            "ERROR: "
            "TELEGRAM_BOT_TOKEN missing"
        )

        return

    if not TELEGRAM_CHAT_ID:

        print(
            "ERROR: "
            "TELEGRAM_CHAT_ID missing"
        )

        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
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

    # -----------------------------------------------------
    # INTERNET
    # -----------------------------------------------------

    if not internet_test():

        print(
            "\nSTOP: Internet unavailable."
        )

        return

    # -----------------------------------------------------
    # SCREENER
    # -----------------------------------------------------

    if not screener_test():

        print(
            "\nSTOP: Screener unavailable."
        )

        return

    # -----------------------------------------------------
    # FUNDAMENTAL STAGE
    # -----------------------------------------------------

    stocks = (
        get_screener_stocks()
    )

    if not stocks:

        print(
            "\nSTOP: "
            "No fundamental stocks found."
        )

        return

    print(
        "\nFundamental stocks:",
        len(stocks)
    )

    # -----------------------------------------------------
    # PREPARE NSE SYMBOLS
    # -----------------------------------------------------

    stocks = (
        prepare_nse_stocks(
            stocks
        )
    )

    if not stocks:

        print(
            "\nSTOP: "
            "No NSE-style symbols found."
        )

        return

    print(
        "\nStocks entering technical stage:",
        len(stocks)
    )

    # -----------------------------------------------------
    # PRICE TEST
    # -----------------------------------------------------

    price_success = (
        price_data_test(
            stocks
        )
    )

    if price_success == 0:

        print(
            "\n========================================"
        )

        print(
            "STOP: "
            "NO PRICE DATA"
        )

        print(
            "========================================"
        )

        send_telegram(
            "NSE SWING SCANNER\n\n"
            "⚠️ Price data unavailable.\n"
            "Technical scan did not start."
        )

        return

    # -----------------------------------------------------
    # TECHNICAL STAGE
    # -----------------------------------------------------

    print(
        "\n============
