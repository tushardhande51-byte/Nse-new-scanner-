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
        "Chrome/154.0 Safari/537.36"
    )
}

MAX_WORKERS = 8


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

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("Telegram status:", response.status_code)

        if response.ok:
            print("Telegram: SENT")
            return True

        print("Telegram error:", response.text)
        return False

    except Exception as e:
        print("Telegram exception:", e)
        return False


# =========================================================
# STAGE 1
# SCREENER FUNDAMENTAL STOCKS
# =========================================================

def get_screener_stocks():

    print("\n========================================")
    print("STAGE 1: FUNDAMENTAL SCREEN")
    print("========================================")
    print("Screener URL:", SCREENER_URL)

    session = requests.Session()
    session.headers.update(HEADERS)

    stocks = []

    for page in range(1, 20):

        if page == 1:
            url = SCREENER_URL
        else:
            url = SCREENER_URL + f"?page={page}"

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
                print("Screener request failed")
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

                symbol = (
                    match.group(1)
                    if match
                    else ""
                )

                if not name:
                    continue

                key = (
                    symbol
                    if symbol
                    else name
                )

                if not any(
                    x["key"] == key
                    for x in stocks
                ):

                    stocks.append({
                        "name": name,
                        "symbol": symbol,
                        "key": key
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

    print("\nFundamental PASS:", len(stocks))

    return stocks


# =========================================================
# PRICE DATA
# =========================================================

def get_price_data(symbol):

    try:

        url = YAHOO_URL.format(symbol)

        response = requests.get(
            url,
            params={
                "range": "4mo",
                "interval": "1d",
                "events": "history"
            },
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:
            return None

        data = response.json()

        result = (
            data
            .get("chart", {})
            .get("result")
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

    except Exception:
        return None


# =========================================================
# TECHNICAL ANALYSIS
# =========================================================

def technical_analysis(symbol, df):

    close = df["close"]

    # -----------------------------------------
    # EMA
    # -----------------------------------------

    ema20 = close.ewm(
        span=20,
        adjust=False
    ).mean()

    ema50 = close.ewm(
        span=50,
        adjust=False
    ).mean()

    # -----------------------------------------
    # RSI 14
    # -----------------------------------------

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

    rs = gain / loss.replace(
        0,
        pd.NA
    )

    rsi = (
        100
        - (
            100
            / (1 + rs)
        )
    )

    # -----------------------------------------
    # VOLUME
    # -----------------------------------------

    avg_volume20 = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    # -----------------------------------------
    # PREVIOUS 20 DAY HIGH
    # -----------------------------------------

    previous_20_high = (
        df["high"]
        .shift(1)
        .rolling(20)
        .max()
    )

    # -----------------------------------------
    # CURRENT VALUES
    # -----------------------------------------

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
        avg_volume20.iloc[-1]
    )

    resistance = float(
        previous_20_high.iloc[-1]
    )

    # =====================================================
    # 6 TECHNICAL FILTERS
    # =====================================================

    # FILTER 1
    # Trend:
    # Close > EMA20 > EMA50

    filter_1 = (
        entry
        > current_ema20
        > current_ema50
    )

    # FILTER 2
    # EMA:
    # Close > EMA20

    filter_2 = (
        entry
        > current_ema20
    )

    # FILTER 3
    # RSI:
    # 55 - 70

    filter_3 = (
        55
        <= current_rsi
        <= 70
    )

    # FILTER 4
    # Volume:
    # Today > 20 day average × 1.5

    filter_4 = (
        current_volume
        > average_volume * 1.5
    )

    # FILTER 5
    # Resistance:
    # Entry within 2% of previous 20 day high

    filter_5 = (
        entry
        >= resistance * 0.98
    )

    # FILTER 6
    # Breakout:
    # Current close > previous 20 day high

    filter_6 = (
        entry
        > resistance
    )

    filters = [
        filter_1,
        filter_2,
        filter_3,
        filter_4,
        filter_5,
        filter_6
    ]

    # =====================================================
    # RETURN COMPLETE DIAGNOSTIC DATA
    # =====================================================

    return {
        "symbol": symbol,

        "entry": entry,

        "ema20": current_ema20,

        "ema50": current_ema50,

        "rsi": current_rsi,

        "volume": current_volume,

        "avg_volume": average_volume,

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

        "all_pass": all(filters)
    }


# =========================================================
# DIAGNOSTIC REPORT
# =========================================================

def print_diagnostic_report(all_results):

    print("\n")
    print("========================================")
    print("6-FILTER DIAGNOSTIC REPORT")
    print("========================================")

    total = len(all_results)

    print(
        f"Valid price-data stocks: {total}"
    )

    if total == 0:
        print(
            "No valid price data received."
        )
        return

    # -----------------------------------------
    # Individual filter counts
    # -----------------------------------------

    f1_count = sum(
        x["f1"]
        for x in all_results
    )

    f2_count = sum(
        x["f2"]
        for x in all_results
    )

    f3_count = sum(
        x["f3"]
        for x in all_results
    )

    f4_count = sum(
        x["f4"]
        for x in all_results
    )

    f5_count = sum(
        x["f5"]
        for x in all_results
    )

    f6_count = sum(
        x["f6"]
        for x in all_results
    )

    print("\nINDIVIDUAL FILTER PASS:")

    print(
        f"Filter 1 Trend       : "
        f"{f1_count}"
    )

    print(
        f"Filter 2 EMA         : "
        f"{f2_count}"
    )

    print(
        f"Filter 3 RSI         : "
        f"{f3_count}"
    )

    print(
        f"Filter 4 Volume      : "
        f"{f4_count}"
    )

    print(
        f"Filter 5 Resistance  : "
        f"{f5_count}"
    )

    print(
        f"Filter 6 Breakout    : "
        f"{f6_count}"
    )

    # -----------------------------------------
    # CUMULATIVE COUNTS
    # -----------------------------------------

    c1 = sum(
        x["f1"]
        for x in all_results
    )

    c2 = sum(
        x["f1"]
        and x["f2"]
        for x in all_results
    )

    c3 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        for x in all_results
    )

    c4 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        and x["f4"]
        for x in all_results
    )

    c5 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        and x["f4"]
        and x["f5"]
        for x in all_results
    )

    c6 = sum(
        x["f1"]
        and x["f2"]
        and x["f3"]
        and x["f4"]
        and x["f5"]
        and x["f6"]
        for x in all_results
    )

    print("\nCUMULATIVE PASS:")

    print(
        f"Filter 1 only              : {c1}"
    )

    print(
        f"Filter 1 + 2               : {c2}"
    )

    print(
        f"Filter 1 + 2 + 3           : {c3}"
    )

    print(
        f"Filter 1 + 2 + 3 + 4       : {c4}"
    )

    print(
        f"Filter 1 + 2 + 3 + 4 + 5   : {c5}"
    )

    print(
        f"ALL 6 FILTERS              : {c6}"
    )

    print(
        "\n========================================"
    )


# =========================================================
# TELEGRAM FINAL RESULTS
# =========================================================

def send_final_results(results):

    print("\n========================================")
    print("FINAL TECHNICAL RESULTS")
    print("========================================")

    if not results:

        message = (
            "🔔 NSE SWING SCANNER\n\n"
            "Fundamental stocks scanned: 151\n\n"
            "❌ Technical 6/6 PASS: 0\n\n"
            "Diagnostic report GitHub Actions "
            "logs me available hai."
        )

        send_telegram(message)

        return

    message = (
        "🚨 NSE SWING SCANNER\n\n"
        "✅ FUNDAMENTAL + TECHNICAL 6/6\n\n"
    )

    for i, x in enumerate(
        results,
        start=1
    ):

        message += (

            f"{i}. {x['symbol']}\n"

            f"Entry: "
            f"₹{x['entry']:.2f}\n"

            f"Stoploss: "
            f"₹{x['entry'] * 0.95:.2f}\n"

            f"Target: "
            f"₹{x['entry'] * 1.10:.2f}\n"

            f"RSI: "
            f"{x['rsi']:.2f}\n"

            f"Volume: "
            f"{x['volume_ratio']:.2f}x\n"

            f"Filter: 6/6\n\n"
        )

    message += (
        f"Total Final Stocks: "
        f"{len(results)}"
    )

    send_telegram(message)


# =========================================================
# MAIN
# =========================================================

def main():

    print("\n")
    print("========================================")
    print("NSE SWING SCANNER")
    print("========================================")

    # -----------------------------------------
    # STAGE 1
    # -----------------------------------------

    fundamental_stocks = (
        get_screener_stocks()
    )

    if not fundamental_stocks:

        print(
            "No fundamental stocks found."
        )

        send_telegram(
            "⚠️ NSE Scanner\n\n"
            "Fundamental screen returned "
            "0 stocks."
        )

        return

    # -----------------------------------------
    # STAGE 2
    # -----------------------------------------

    print("\n")
    print("========================================")
    print("STAGE 2: TECHNICAL 6/6")
    print("========================================")

    print(
        "Stocks to analyse:",
        len(fundamental_stocks)
    )

    all_results = []

    completed = 0

    futures_map = {}

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        for stock in fundamental_stocks:

            symbol = stock["symbol"]

            if not symbol:
                continue

            future = executor.submit(
                get_price_data,
                symbol
            )

            futures_map[future] = stock

        total_jobs = len(
            futures_map
        )

        for future in as_completed(
            futures_map
        ):

            completed += 1

            stock = futures_map[
                future
            ]

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

                    all_results.append(
                        result
                    )

            except Exception as e:

                print(
                    "Technical error:",
                    stock["symbol"],
                    e
                )

            if (
                completed % 25 == 0
                or completed == total_jobs
            ):

                six_count = sum(
                    x["all_pass"]
                    for x in all_results
                )

                print(
                    f"Technical progress: "
                    f"{completed}/{total_jobs} "
                    f"| 6/6 PASS: {six_count}"
                )

    # -----------------------------------------
    # DIAGNOSTIC REPORT
    # -----------------------------------------

    print_diagnostic_report(
        all_results
    )

    # -----------------------------------------
    # FINAL 6/6 STOCKS
    # -----------------------------------------

    final_results = [
        x
        for x in all_results
        if x["all_pass"]
    ]

    print("\n")
    print("========================================")
    print(
        "FINAL TECHNICAL 6/6:",
        len(final_results)
    )
    print("========================================")

    for x in final_results:

        print(
            f"{x['symbol']} | "
            f"Entry ₹{x['entry']:.2f} | "
            f"SL ₹{x['entry'] * 0.95:.2f} | "
            f"Target ₹{x['entry'] * 1.10:.2f} | "
            f"RSI {x['rsi']:.2f} | "
            f"Volume {x['volume_ratio']:.2f}x"
        )

    # -----------------------------------------
    # TELEGRAM
    # -----------------------------------------

    send_final_results(
        final_results
    )

    print(
        "\nFINAL BUY COUNT:",
        len(final_results)
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
