import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup


# =========================================================
# SETTINGS
# =========================================================

NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{}.NS"
)

SCREENER_URL = (
    "https://www.screener.in/screens/4008468/tushar-dhande/"
)

CAPITAL = float(
    os.getenv("CAPITAL", "30000")
)

RISK_PCT = float(
    os.getenv("RISK_PCT", "1")
)

SL_PCT = float(
    os.getenv("SL_PCT", "5")
)

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

TELEGRAM_TEST = (
    os.getenv("TELEGRAM_TEST", "0") == "1"
)

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 "
        "(Linux; Android 10) "
        "AppleWebKit/537.36 "
        "Chrome/154.0 Safari/537.36"
}

MAX_WORKERS = 12


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

    try:

        url = (
            "https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )

        if response.ok:

            print("Telegram: SENT")

            return True

        print(
            "Telegram FAILED:",
            response.status_code,
            response.text
        )

        return False

    except Exception as e:

        print(
            "Telegram ERROR:",
            e
        )

        return False


# =========================================================
# NSE UNIVERSE
# =========================================================

def get_nse_universe():

    print()
    print(
        "STEP 1: Downloading current NSE universe..."
    )

    response = requests.get(
        NSE_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    df = pd.read_csv(
        StringIO(response.text)
    )

    df.columns = [
        str(c).strip().upper()
        for c in df.columns
    ]

    if "SYMBOL" not in df.columns:

        raise RuntimeError(
            "NSE CSV me SYMBOL column nahi mila"
        )

    # Only normal equity series
    if "SERIES" in df.columns:

        df = df[
            df["SERIES"]
            .astype(str)
            .str.upper()
            .eq("EQ")
        ]

    df = df[
        df["SYMBOL"].notna()
    ].copy()

    df["SYMBOL"] = (
        df["SYMBOL"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    if "NAME OF COMPANY" in df.columns:

        df["NAME"] = (
            df["NAME OF COMPANY"]
            .astype(str)
            .str.strip()
        )

    else:

        df["NAME"] = df["SYMBOL"]

    df = df.drop_duplicates(
        "SYMBOL"
    )

    stocks = df[
        ["SYMBOL", "NAME"]
    ].to_dict("records")

    print(
        f"NSE EQ stocks found: {len(stocks)}"
    )

    return stocks


# =========================================================
# YAHOO DAILY DATA
# =========================================================

def get_yahoo_data(symbol):

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
            timeout=15
        )

        if response.status_code != 200:

            return (
                symbol,
                None
            )

        data = response.json()

        result = (
            data
            .get("chart", {})
            .get("result")
        )

        if not result:

            return (
                symbol,
                None
            )

        quote = (
            result[0]
            .get("indicators", {})
            .get("quote", [{}])[0]
        )

        df = pd.DataFrame({

            "open":
                quote.get("open", []),

            "high":
                quote.get("high", []),

            "low":
                quote.get("low", []),

            "close":
                quote.get("close", []),

            "volume":
                quote.get("volume", [])

        })

        df = df.dropna()

        if len(df) < 60:

            return (
                symbol,
                None
            )

        return (
            symbol,
            df.reset_index(drop=True)
        )

    except Exception:

        return (
            symbol,
            None
        )


# =========================================================
# TECHNICAL 6/6
# =========================================================

def technical_scan(
    symbol,
    df
):

    close = df["close"]

    # EMA
    ema20 = (
        close
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )

    ema50 = (
        close
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

    # RSI 14
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

    # Volume
    avg_volume20 = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    # Previous 20-day resistance
    previous_20_high = (
        df["high"]
        .shift(1)
        .rolling(20)
        .max()
    )

    last_close = float(
        close.iloc[-1]
    )

    last_ema20 = float(
        ema20.iloc[-1]
    )

    last_ema50 = float(
        ema50.iloc[-1]
    )

    last_rsi = float(
        rsi.iloc[-1]
    )

    last_volume = float(
        df["volume"].iloc[-1]
    )

    last_avg_volume = float(
        avg_volume20.iloc[-1]
    )

    resistance = float(
        previous_20_high.iloc[-1]
    )

    # =====================================================
    # SIX FILTERS
    # =====================================================

    filter_1 = (
        last_close >
        last_ema20 >
        last_ema50
    )

    filter_2 = (
        last_close >
        last_ema20
    )

    filter_3 = (
        55 <=
        last_rsi <=
        70
    )

    filter_4 = (
        last_volume >
        last_avg_volume * 1.5
    )

    filter_5 = (
        last_close >=
        resistance * 0.98
    )

    filter_6 = (
        last_close >
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

    # =====================================================
    # TRADE SETUP
    # =====================================================

    entry = last_close

    # 5% stop loss
    stop_loss = (
        entry *
        (
            1 -
            SL_PCT / 100
        )
    )

    risk_per_share = (
        entry -
        stop_loss
    )

    # Capital based risk
    risk_money = (
        CAPITAL *
        RISK_PCT /
        100
    )

    quantity = int(
        risk_money //
        risk_per_share
    )

    if quantity < 1:

        return None

    actual_risk = (
        quantity *
        risk_per_share
    )

    # 1:2
    target_1 = (
        entry *
        (
            1 +
            (SL_PCT * 2) /
            100
        )
    )

    # 1:3
    target_2 = (
        entry *
        (
            1 +
            (SL_PCT * 3) /
            100
        )
    )

    rvol = (
        last_volume /
        last_avg_volume
    )

    return {

        "symbol":
            symbol,

        "entry":
            round(
                entry,
                2
            ),

        "sl":
            round(
                stop_loss,
                2
            ),

        "t1":
            round(
                target_1,
                2
            ),

        "t2":
            round(
                target_2,
                2
            ),

        "qty":
            quantity,

        "risk":
            round(
                actual_risk,
                2
            ),

        "rsi":
            round(
                last_rsi,
                2
            ),

        "rvol":
            round(
                rvol,
                2
            ),

        "filters":
            "6/6"
    }


# =========================================================
# SCREENER FUNDAMENTAL LIST
# =========================================================

def normalize_name(text):

    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(text).upper()
    )


def get_screener_names():

    print()
    print(
        "STEP 2: Reading Screener fundamental screen..."
    )

    names = []

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    for page in range(
        1,
        11
    ):

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
                timeout=20
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            found = 0

            for link in soup.select(
                "table.data-table "
                "tbody tr "
                "a[href*='/company/']"
            ):

                name = link.get_text(
                    " ",
                    strip=True
                )

                if not name:

                    continue

                normalized = (
                    normalize_name(name)
                )

                existing = {
                    normalize_name(x)
                    for x in names
                }

                if normalized not in existing:

                    names.append(
                        name
                    )

                    found += 1

            print(
                f"Screener page {page}: "
                f"{found} stocks"
            )

            if found == 0:

                break

            time.sleep(
                0.3
            )

        except Exception as e:

            print(
                "Screener error:",
                e
            )

            break

    print(
        "Screener stocks found:",
        len(names)
    )

    return names


# =========================================================
# FUNDAMENTAL NAME MATCH
# =========================================================

def fundamental_match(
    company_name,
    screener_names
):

    a = normalize_name(
        company_name
    )

    if not a:

        return False

    normalized_names = [
        normalize_name(x)
        for x in screener_names
    ]

    # Exact match
    if a in normalized_names:

        return True

    # Very conservative fuzzy match
    best = max(
        (
            SequenceMatcher(
                None,
                a,
                b
            ).ratio()
            for b in normalized_names
        ),
        default=0
    )

    return best >= 0.92


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print(
        "=========================================="
    )

    print(
        "     NSE SWING SCANNER"
    )

    print(
        "     FULL NSE UNIVERSE"
    )

    print(
        "=========================================="
    )

    print(
        f"Capital      : ₹{CAPITAL:,.0f}"
    )

    print(
        f"Risk         : {RISK_PCT}%"
    )

    print(
        f"Stop Loss    : {SL_PCT}%"
    )

    print(
        f"Target 1     : {SL_PCT * 2}%"
    )

    print(
        f"Target 2     : {SL_PCT * 3}%"
    )

    print(
        "=========================================="
    )

    # -----------------------------------------------------
    # 1. FULL NSE UNIVERSE
    # -----------------------------------------------------

    universe = (
        get_nse_universe()
    )

    # -----------------------------------------------------
    # 2. FUNDAMENTAL SCREEN
    # -----------------------------------------------------

    screener_names = (
        get_screener_names()
    )

    # -----------------------------------------------------
    # 3. TECHNICAL SCAN
    # -----------------------------------------------------

    print()
    print(
        "STEP 3: Technical 6/6 scan..."
    )

    technical_candidates = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {

            executor.submit(
                get_yahoo_data,
                stock["SYMBOL"]
            ):
                stock

            for stock in universe
        }

        for future in as_completed(
            futures
        ):

            completed += 1

            stock = futures[
                future
            ]

            symbol, df = (
                future.result()
            )

            if df is not None:

                result = (
                    technical_scan(
                        symbol,
                        df
                    )
                )

                if result:

                    result[
                        "name"
                    ] = stock["NAME"]

                    result[
                        "fundamental"
                    ] = fundamental_match(
                        stock["NAME"],
                        screener_names
                    )

                    technical_candidates.append(
                        result
                    )

            if (
                completed % 250 == 0
                or
                completed == len(
                    universe
                )
            ):

                print(
                    f"Progress: "
                    f"{completed}/"
                    f"{len(universe)} | "
                    f"6/6 candidates: "
                    f"{len(technical_candidates)}"
                )

    # -----------------------------------------------------
    # 4. FINAL FUNDAMENTAL CONFIRMATION
    # -----------------------------------------------------

    final_candidates = [

        x

        for x in technical_candidates

        if x["fundamental"]

    ]

    print()
    print(
        "=========================================="
    )

    print(
        "TECHNICAL 6/6:",
        len(
            technical_candidates
        )
    )

    print(
        "FINAL CANDIDATES:",
        len(
            final_candidates
        )
    )

    print(
        "=========================================="
    )

    # -----------------------------------------------------
    # 5. PRINT FINAL RESULTS
    # -----------------------------------------------------

    for x in final_candidates:

        print()

        print(
            f"{x['symbol']} | "
            f"Entry ₹{x['entry']:.2f} | "
            f"SL ₹{x['sl']:.2f} | "
            f"T1 ₹{x['t1']:.2f} | "
            f"T2 ₹{x['t2']:.2f} | "
            f"Qty {x['qty']} | "
            f"Risk ₹{x['risk']:.2f} | "
            f"RSI {x['rsi']:.2f} | "
            f"RVOL {x['rvol']:.2f}"
        )

    # -----------------------------------------------------
    # 6. TELEGRAM BUY ALERT
    # -----------------------------------------------------

    if final_candidates:

        message = (
            "🚨 NSE SWING SCANNER BUY\n\n"
        )

        for x in final_candidates:

            message += (

                f"📈 {x['symbol']}\n"

                f"Entry: ₹{x['entry']:.2f}\n"

                f"SL: ₹{x['sl']:.2f} "
                f"(-{SL_PCT:.0f}%)\n"

                f"T1: ₹{x['t1']:.2f} "
                f"(+{SL_PCT * 2:.0f}%)\n"

                f"T2: ₹{x['t2']:.2f} "
                f"(+{SL_PCT * 3:.0f}%)\n"

                f"Qty: {x['qty']}\n"

                f"Risk: ₹{x['risk']:.2f}\n"

                f"RSI: {x['rsi']:.2f}\n"

                f"RVOL: {x['rvol']:.2f}\n\n"
            )

        send_telegram(
            message
        )

    # -----------------------------------------------------
    # 7. TELEGRAM TEST
    # -----------------------------------------------------

    if TELEGRAM_TEST:

        test_message = (

            "✅ NSE Scanner Telegram TEST\n\n"

            f"NSE Universe: "
            f"{len(universe)} stocks\n"

            f"Technical 6/6: "
            f"{len(technical_candidates)}\n"

            f"Final Candidates: "
            f"{len(final_candidates)}\n\n"

            f"Capital: "
            f"₹{CAPITAL:,.0f}\n"

            f"Risk: "
            f"{RISK_PCT}%\n"

            f"SL: "
            f"{SL_PCT}%\n"

            f"T1: "
            f"{SL_PCT * 2}%\n"

            f"T2: "
            f"{SL_PCT * 3}%"
        )

        send_telegram(
            test_message
        )

    print()
    print(
        "=========================================="
    )

    print(
        "FINAL BUY COUNT:",
        len(
            final_candidates
        )
    )

    print(
        "=========================================="
    )


if __name__ == "__main__":

    main()
