import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from bs4 import BeautifulSoup


# =========================================================
# SETTINGS
# =========================================================

SCREENER_URL = (
    "https://www.screener.in/screens/"
    "4008468/tushar-dhande/"
)

YAHOO_URL = (
    "https://query1.finance.yahoo.com/"
    "v8/finance/chart/{}.NS"
)

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

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

    print()
    print("==========================================")
    print("     STAGE 1: FUNDAMENTAL SCREEN")
    print("==========================================")

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    stocks = []

    for page in range(1, 20):

        if page == 1:

            url = SCREENER_URL

        else:

            url = (
                SCREENER_URL +
                f"?page={page}"
            )

        try:

            response = session.get(
                url,
                timeout=30
            )

            print(
                f"Page {page}: HTTP "
                f"{response.status_code}"
            )

            if response.status_code != 200:

                print(
                    "Screener request failed"
                )

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

                        "name":
                            name,

                        "symbol":
                            symbol,

                        "key":
                            key

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
# YAHOO DAILY DATA
# =========================================================

def get_price_data(symbol):

    try:

        url = YAHOO_URL.format(
            symbol
        )

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

            "open":
                quote.get(
                    "open",
                    []
                ),

            "high":
                quote.get(
                    "high",
                    []
                ),

            "low":
                quote.get(
                    "low",
                    []
                ),

            "close":
                quote.get(
                    "close",
                    []
                ),

            "volume":
                quote.get(
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
# STAGE 2
# TECHNICAL 6/6
# =========================================================

def technical_analysis(
    symbol,
    df
):

    close = df["close"]

    # -----------------------------------------
    # EMA 20
    # -----------------------------------------

    ema20 = (
        close
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )

    # -----------------------------------------
    # EMA 50
    # -----------------------------------------

    ema50 = (
        close
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

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

    rs = (
        gain /
        loss.replace(
            0,
            pd.NA
        )
    )

    rsi = (
        100 -
        (
            100 /
            (1 + rs)
        )
    )

    # -----------------------------------------
    # 20 DAY AVERAGE VOLUME
    # -----------------------------------------

    avg_volume20 = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    # -----------------------------------------
    # PREVIOUS 20 DAY RESISTANCE
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

    # =================================================
    # SIX FILTERS
    # =================================================

    # 1. Trend
    filter_1 = (
        entry >
        current_ema20 >
        current_ema50
    )

    # 2. EMA
    filter_2 = (
        entry >
        current_ema20
    )

    # 3. RSI
    filter_3 = (
        55 <=
        current_rsi <=
        70
    )

    # 4. Volume
    filter_4 = (
        current_volume >
        average_volume * 1.5
    )

    # 5. Resistance proximity
    filter_5 = (
        entry >=
        resistance * 0.98
    )

    # 6. Breakout
    filter_6 = (
        entry >
        resistance
    )

    filters = [
        filter_1,
        filter_2,
        filter_3,
        filter_4,
        filter_5,
        filter_6
    ]

    # STRICT 6/6
    if not all(filters):

        return None

    # =================================================
    # TRADE LEVELS
    # =================================================

    # Entry = current close
    entry_price = entry

    # Stoploss = 5% below entry
    stop_loss = (
        entry_price * 0.95
    )

    # Target = +10%
    target = (
        entry_price * 1.10
    )

    return {

        "symbol":
            symbol,

        "entry":
            round(
                entry_price,
                2
            ),

        "sl":
            round(
                stop_loss,
                2
            ),

        "target":
            round(
                target,
                2
            ),

        "rsi":
            round(
                current_rsi,
                2
            ),

        "resistance":
            round(
                resistance,
                2
            ),

        "volume_ratio":
            round(
                current_volume /
                average_volume,
                2
            ),

        "filters":
            "6/6"

    }


# =========================================================
# TELEGRAM FINAL ALERT
# =========================================================

def send_final_results(
    results
):

    print()
    print("==========================================")
    print(
        "FINAL TECHNICAL 6/6:",
        len(results)
    )
    print("==========================================")

    if not results:

        message = (
            "🔔 NSE SWING SCANNER\n\n"
            "Fundamental stocks scanned.\n\n"
            "❌ Technical 6/6 PASS: 0\n\n"
            "Aaj koi stock 6/6 technical "
            "filters pass nahi hua."
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

        message += (

            f"{i}. {x['symbol']}\n"

            f"Entry: ₹{x['entry']:.2f}\n"

            f"Stoploss: ₹{x['sl']:.2f}\n"

            f"Target: ₹{x['target']:.2f}\n"

            f"RSI: {x['rsi']:.2f}\n"

            f"Volume: {x['volume_ratio']:.2f}x\n"

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
    print("==========================================")
    print("       NSE SWING SCANNER")
    print("       FUNDAMENTAL + TECHNICAL")
    print("==========================================")

    # -----------------------------------------
    # STEP 1
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
            "Fundamental screen returned 0 stocks."
        )

        return

    # -----------------------------------------
    # STEP 2
    # -----------------------------------------

    print()
    print("==========================================")
    print("     STAGE 2: TECHNICAL 6/6")
    print("==========================================")

    print(
        "Stocks to analyse:",
        len(fundamental_stocks)
    )

    final_results = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {

            executor.submit(
                get_price_data,
                stock["symbol"]
            ):
                stock

            for stock
            in fundamental_stocks
            if stock["symbol"]
        }

        for future in as_completed(
            futures
        ):

            completed += 1

            stock = futures[
                future
            ]

            df = future.result()

            if df is not None:

                result = (
                    technical_analysis(
                        stock["symbol"],
                        df
                    )
                )

                if result:

                    result["name"] = (
                        stock["name"]
                    )

                    final_results.append(
                        result
                    )

            if (
                completed % 25 == 0
                or
                completed ==
                len(futures)
            ):

                print(
                    f"Technical progress: "
                    f"{completed}/"
                    f"{len(futures)} | "
                    f"6/6 PASS: "
                    f"{len(final_results)}"
                )

    # -----------------------------------------
    # FINAL
    # -----------------------------------------

    print()

    for x in final_results:

        print(
            f"{x['symbol']} | "
            f"Entry ₹{x['entry']:.2f} | "
            f"SL ₹{x['sl']:.2f} | "
            f"Target ₹{x['target']:.2f} | "
            f"RSI {x['rsi']:.2f} | "
            f"Volume {x['volume_ratio']:.2f}x | "
            f"6/6"
        )

    send_final_results(
        final_results
    )

    print()
    print("==========================================")
    print(
        "FINAL BUY COUNT:",
        len(final_results)
    )
    print("==========================================")


if __name__ == "__main__":
    main()
