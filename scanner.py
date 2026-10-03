import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from bs4 import BeautifulSoup


# =========================================================
# SETTINGS
# =========================================================

SCREENER_URL = "https://www.screener.in/screens/4008468/tushar-dhande/"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}.NS"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Linux; Android 10) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0 Safari/537.36"
    )
}

MAX_WORKERS = 6


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        print("Telegram token missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("Telegram chat ID missing")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print(
            "Telegram status:",
            response.status_code
        )

        if response.ok:
            print("Telegram: SENT")
            return True

        print(
            "Telegram error:",
            response.text
        )

        return False

    except Exception as e:

        print(
            "Telegram exception:",
            e
        )

        return False


# =========================================================
# STAGE 1
# SCREENER FUNDAMENTAL STOCKS
# =========================================================

def get_screener_stocks():

    print("\n========================================")
    print("STAGE 1: FUNDAMENTAL SCREEN")
    print("========================================")

    session = requests.Session()
    session.headers.update(HEADERS)

    stocks = []
    seen = set()

    for page in range(1, 20):

        if page == 1:
            url = SCREENER_URL
        else:
            url = (
                SCREENER_URL
                + f"?page={page}"
            )

        try:

            response = session.get(
                url,
                timeout=30
            )

            print(
                f"Page {page}: "
                f"HTTP {response.status_code}"
            )

            if response.status_code != 200:
                break

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            rows = soup.select(
                "table.data-table tbody tr"
            )

            page_count = 0

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
                    r"/company/([^/]+)/",
                    href
                )

                if not match:
                    continue

                symbol = (
                    match.group(1)
                    .strip()
                    .upper()
                )

                if not symbol:
                    continue

                if symbol in seen:
                    continue

                seen.add(symbol)

                stocks.append({
                    "name": name,
                    "symbol": symbol
                })

                page_count += 1

            print(
                f"Page {page}: "
                f"{page_count} stocks"
            )

            if page_count == 0:
                break

        except Exception as e:

            print(
                f"Page {page} error:",
                e
            )

            break

    print()
    print(
        "Fundamental PASS:",
        len(stocks)
    )

    return stocks


# =========================================================
# SYMBOL CONVERSION
# =========================================================

def make_yahoo_symbol(symbol):

    symbol = (
        str(symbol)
        .strip()
        .upper()
    )

    # Remove exchange suffix if already present
    symbol = re.sub(
        r"\.(NS|BO)$",
        "",
        symbol
    )

    # Yahoo Finance uses hyphen for some symbols
    symbol = symbol.replace(
        "&",
        "%26"
    )

    return symbol + ".NS"


# =========================================================
# YAHOO PRICE DATA
# =========================================================

def get_price_data(symbol):

    try:

        yahoo_symbol = make_yahoo_symbol(
            symbol
        )

        url = YAHOO_URL.format(
            yahoo_symbol
        )

        response = requests.get(
            url,
            params={
                "range": "6mo",
                "interval": "1d",
                "events": "history"
            },
            headers=HEADERS,
            timeout=30
        )

        if response.status_code != 200:

            print(
                f"PRICE ERROR | "
                f"{symbol} | "
                f"Yahoo: {yahoo_symbol} | "
                f"HTTP {response.status_code}"
            )

            return None

        data = response.json()

        chart = data.get(
            "chart",
            {}
        )

        result = chart.get(
            "result"
        )

        if not result:

            return None

        quote = (
            result[0]
            .get("indicators", {})
            .get("quote", [{}])[0]
        )

        df = pd.DataFrame({

            "open": quote.get(
                "open",
                []
            ),

            "high": quote.get(
                "high",
                []
            ),

            "low": quote.get(
                "low",
                []
            ),

            "close": quote.get(
                "close",
                []
            ),

            "volume": quote.get(
                "volume",
                []
            )
        })

        df = df.dropna()

        if len(df) < 60:

            return None

        return df.reset_index(
            drop=True
        )

    except Exception as e:

        print(
            f"PRICE EXCEPTION | "
            f"{symbol} | {e}"
        )

        return None


# =========================================================
# TEST PRICE DATA
# =========================================================

def test_price_connection(
    fundamental_stocks
):

    print("\n========================================")
    print("PRICE DATA CONNECTION TEST")
    print("========================================")

    test_stocks = fundamental_stocks[:5]

    success = 0

    for stock in test_stocks:

        symbol = stock["symbol"]

        yahoo_symbol = make_yahoo_symbol(
            symbol
        )

        print()
        print(
            "Testing:",
            stock["name"]
        )

        print(
            "Screener symbol:",
            symbol
        )

        print(
            "Yahoo symbol:",
            yahoo_symbol
        )

        df = get_price_data(
            symbol
        )

        if df is not None:

            success += 1

            print(
                "PRICE DATA: OK"
            )

            print(
                "Rows:",
                len(df)
            )

            print(
                "Latest close:",
                round(
                    float(
                        df["close"].iloc[-1]
                    ),
                    2
                )
            )

        else:

            print(
                "PRICE DATA: FAILED"
            )

    print()
    print(
        "Price test:",
        success,
        "/",
        len(test_stocks),
        "working"
    )

    return success


# =========================================================
# TECHNICAL ANALYSIS
# =========================================================

def technical_analysis(
    symbol,
    df
):

    close = df["close"]

    # -----------------------------------------------------
    # EMA 20
    # -----------------------------------------------------

    ema20 = (
        close
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )

    # -----------------------------------------------------
    # EMA 50
    # -----------------------------------------------------

    ema50 = (
        close
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

    # -----------------------------------------------------
    # RSI 14
    # -----------------------------------------------------

    delta = close.diff()

    gain = (
        delta
        .clip(lower=0)
        .ewm(
            alpha=1 / 14,
            adjust=False
        )
        .mean()
    )

    loss = (
        -delta
        .clip(upper=0)
        .ewm(
            alpha=1 / 14,
            adjust=False
        )
        .mean()
    )

    loss = loss.replace(
        0,
        pd.NA
    )

    rs = gain / loss

    rsi = (
        100
        - (
            100
            / (1 + rs)
        )
    )

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    average_volume20 = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    # -----------------------------------------------------
    # PREVIOUS 20 DAY HIGH
    # -----------------------------------------------------

    previous_20_high = (
        df["high"]
        .shift(1)
        .rolling(20)
        .max()
    )

    # -----------------------------------------------------
    # CURRENT VALUES
    # -----------------------------------------------------

    entry = float(
        close.iloc[-1]
    )

    current_ema20 = float(
        ema20.iloc[-1]
    )

    current_ema50 = float(
        ema50.iloc[-1]
    )

    current_rsi = float(
        rsi.iloc[-1]
    )

    current_volume = float(
        df["volume"].iloc[-1]
    )

    average_volume = float(
        average_volume20.iloc[-1]
    )

    resistance = float(
        previous_20_high.iloc[-1]
    )

    # -----------------------------------------------------
    # SIX FILTERS
    # -----------------------------------------------------

    # 1. TREND
    filter_1 = (
        entry
        > current_ema20
        > current_ema50
    )

    # 2. EMA
    filter_2 = (
        entry
        > current_ema20
    )

    # 3. RSI
    filter_3 = (
        55
        <= current_rsi
        <= 70
    )

    # 4. VOLUME
    filter_4 = (
        current_volume
        > average_volume * 1.5
    )

    # 5. RESISTANCE
    filter_5 = (
        entry
        >= resistance * 0.98
    )

    # 6. BREAKOUT
    filter_6 = (
        entry
        > resistance
    )

    all_pass = (
        filter_1
        and filter_2
        and filter_3
        and filter_4
        and filter_5
        and filter_6
    )

    return {

        "symbol": symbol,

        "entry": entry,

        "ema20": current_ema20,

        "ema50": current_ema50,

        "rsi": current_rsi,

        "volume": current_volume,

        "average_volume": average_volume,

        "volume_ratio": (
            current_volume
            / average_volume
            if average_volume > 0
            else 0
        ),

        "resistance": resistance,

        "f1": filter_1,
        "f2": filter_2,
        "f3": filter_3,
        "f4": filter_4,
        "f5": filter_5,
        "f6": filter_6,

        "all_pass": all_pass
    }


# =========================================================
# DIAGNOSTIC REPORT
# =========================================================

def diagnostic_report(
    results
):

    print("\n========================================")
    print("6-FILTER DIAGNOSTIC REPORT")
    print("========================================")

    total = len(results)

    print(
        "Valid price-data stocks:",
        total
    )

    if total == 0:

        print(
            "No valid price data received."
        )

        return

    # Individual filters

    f1 = sum(
        x["f1"]
        for x in results
    )

    f2 = sum(
        x["f2"]
        for x in results
    )

    f3 = sum(
        x["f3"]
        for x in results
    )

    f4 = sum(
        x["f4"]
        for x in results
    )

    f5 = sum(
        x["f5"]
        for x in results
    )

    f6 = sum(
        x["f6"]
        for x in results
    )

    print()
    print(
        "INDIVIDUAL FILTER PASS:"
    )

    print(
        "Filter 1 Trend      :",
        f1
    )

    print(
        "Filter 2 EMA        :",
        f2
    )

    print(
        "Filter 3 RSI        :",
        f3
    )

    print(
        "Filter 4 Volume     :",
        f4
    )

    print(
        "Filter 5 Resistance :",
        f5
    )

    print(
        "Filter 6 Breakout   :",
        f6
    )

    # Cumulative

    c1 = sum(
        x["f1"]
        for x in results
    )

    c2 = sum(
        x["f1"]
        and x["f2"]
        for x in results
    )

    c3 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        for x in results
    )

    c4 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        and x["f4"]
        for x in results
    )

    c5 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        and x["f4"]
        and x["f5"]
        for x in results
    )

    c6 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        and x["f4"]
        and x["f5"]
        and x["f6"]
        for x in results
    )

    print()
    print(
        "CUMULATIVE PASS:"
    )

    print(
        "Filter 1 only            :",
        c1
    )

    print(
        "Filter 1 + 2             :",
        c2
    )

    print(
        "Filter 1 + 2 + 3         :",
        c3
    )

    print(
        "Filter 1 + 2 + 3 + 4     :",
        c4
    )

    print(
        "Filter 1 + 2 + 3 + 4 + 5 :",
        c5
    )

    print(
        "ALL 6 FILTERS            :",
        c6
    )

    print(
        "========================================"
    )


# =========================================================
# TELEGRAM FINAL RESULT
# =========================================================

def send_final_results(
    results
):

    print("\n========================================")
    print("FINAL TECHNICAL RESULTS")
    print("========================================")

    if not results:

        message = (
            "🔔 NSE SWING SCANNER\n\n"
            "Fundamental screen: PASS\n"
            "Technical 6/6: 0\n\n"
            "Aaj koi stock 6/6 "
            "technical filters pass nahi hua."
        )

        send_telegram(
            message
        )

        return

    message = (
        "🚨 NSE SWING SCANNER\n\n"
        "✅ FUNDAMENTAL + TECHNICAL 6/6\n\n"
    )

    for i, x in enumerate(
        results,
        start=1
    ):

        entry = x["entry"]

        stoploss = (
            entry * 0.95
        )

        target = (
            entry * 1.10
        )

        message += (
            f"{i}. {x['symbol']}\n"
            f"Entry: ₹{entry:.2f}\n"
            f"Stoploss: ₹{stoploss:.2f}\n"
            f"Target: ₹{target:.2f}\n"
            f"RSI: {x['rsi']:.2f}\n"
            f"Volume: "
            f"{x['volume_ratio']:.2f}x\n"
            f"Filter: 6/6\n\n"
        )

    message += (
        f"Total Final Stocks: "
        f"{len(results)}"
    )

    send_telegram(
        message
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("========================================")
    print("NSE SWING SCANNER")
    print("========================================")

    # -----------------------------------------------------
    # STAGE 1
    # -----------------------------------------------------

    fundamental_stocks = (
        get_screener_stocks()
    )

    if not fundamental_stocks:

        print(
            "No fundamental stocks found."
        )

        send_telegram(
            "⚠️ NSE Scanner\n\n"
            "Fundamental screen returned 0 stocks."
        )

        return

    # -----------------------------------------------------
    # PRICE CONNECTION TEST
    # -----------------------------------------------------

    working_price_test = (
        test_price_connection(
            fundamental_stocks
        )
    )

    if working_price_test == 0:

        print()
        print(
            "❌ PRICE DATA CONNECTION FAILED"
        )

        print(
            "Technical scan stopped."
        )

        send_telegram(
            "⚠️ NSE SWING SCANNER\n\n"
            "Fundamental stocks found, "
            "but price-data connection failed.\n\n"
            "Technical scan stopped."
        )

        return

    # -----------------------------------------------------
    # STAGE 2
    # -----------------------------------------------------

    print()
    print("========================================")
    print("STAGE 2: TECHNICAL 6/6")
    print("========================================")

    print(
        "Stocks to analyse:",
        len(fundamental_stocks)
    )

    results = []

    completed = 0

    futures = {}

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        for stock in fundamental_stocks:

            symbol = stock["symbol"]

            future = executor.submit(
                get_price_data,
                symbol
            )

            futures[future] = stock

        total = len(futures)

        for future in as_completed(
            futures
        ):

            completed += 1

            stock = futures[future]

            try:

                df = future.result()

                if df is not None:

                    result = (
                        technical_analysis(
                            stock["symbol"],
                            df
                        )
                    )

                    result["name"] = (
                        stock["name"]
                    )

                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    "Analysis error:",
                    stock["symbol"],
                    e
                )

            if (
                completed % 25 == 0
                or completed == total
            ):

                six_pass = sum(
                    x["all_pass"]
                    for x in results
                )

                print(
                    f"Technical progress: "
                    f"{completed}/{total} "
                    f"| 6/6 PASS: "
                    f"{six_pass}"
                )

    # -----------------------------------------------------
    # DIAGNOSTIC
    # -----------------------------------------------------

    diagnostic_report(
        results
    )

    # -----------------------------------------------------
    # FINAL 6/6
    # -----------------------------------------------------

    final_results = [
        x
        for x in results
        if x["all_pass"]
    ]

    print()
    print("========================================")
  
