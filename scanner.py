import requests
import pandas as pd
import numpy as np
import time
import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# SETTINGS
# ============================================================

SCREENER_URL = "https://www.screener.in/screens/4008468/tushar-dhande/"

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}.NS"

CAPITAL_RISK = 300

SCREENER_PAGES = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0.0.0 Mobile Safari/537.36"
    )
}


# ============================================================
# 1. GET STOCKS FROM YOUR SCREENER
# ============================================================

def get_screener_companies():

    print("--------------------------------")
    print("STEP 1: Reading Screener")
    print("--------------------------------")

    companies = []

    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, SCREENER_PAGES + 1):

        url = SCREENER_URL

        if page > 1:
            url += f"?page={page}"

        try:

            response = session.get(
                url,
                timeout=30
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            page_count = 0

            for row in soup.select("tr"):

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

                if name and href:

                    item = {
                        "name": name,
                        "url": "https://www.screener.in" + href
                    }

                    if not any(
                        x["url"] == item["url"]
                        for x in companies
                    ):
                        companies.append(item)
                        page_count += 1

            print(
                f"Screener page {page}: "
                f"{page_count} stocks"
            )

            if page_count == 0:
                break

            time.sleep(0.5)

        except Exception as e:

            print(
                f"Screener page {page} error: {e}"
            )

    print(
        f"TOTAL FUNDAMENTAL STOCKS: {len(companies)}"
    )

    return companies


# ============================================================
# 2. GET NSE SYMBOL FROM SCREENER COMPANY PAGE
# ============================================================

def get_nse_symbol(company):

    name = company["name"]
    url = company["url"]

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        html = response.text

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        # Look for NSE: SYMBOL
        patterns = [
            r"NSE:\s*([A-Z0-9&._-]+)",
            r"NSE\s*:\s*([A-Z0-9&._-]+)"
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text
            )

            if match:

                symbol = match.group(1).strip()

                # Remove unwanted punctuation
                symbol = symbol.rstrip(".,;:")

                return {
                    "name": name,
                    "symbol": symbol
                }

        return None

    except Exception as e:

        print(
            f"NSE symbol error: {name} | {e}"
        )

        return None


# ============================================================
# 3. GET ALL NSE SYMBOLS
# ============================================================

def get_nse_symbols(companies):

    print("--------------------------------")
    print("STEP 2: Finding NSE Symbols")
    print("--------------------------------")

    results = []

    # Parallel requests
    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                get_nse_symbol,
                company
            )
            for company in companies
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:

                    results.append(result)

            except Exception:
                pass

    # Remove duplicates
    unique = {}

    for item in results:

        symbol = item["symbol"]

        if symbol:
            unique[symbol] = item

    results = list(unique.values())

    print(
        f"NSE SYMBOLS FOUND: {len(results)}"
    )

    return results


# ============================================================
# 4. GET YAHOO HISTORICAL DATA
# ============================================================

def get_yahoo_data(symbol):

    try:

        url = YAHOO_URL.format(symbol)

        response = requests.get(
            url,
            headers=HEADERS,
            params={
                "range": "6mo",
                "interval": "1d"
            },
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        result = data.get(
            "chart",
            {}
        ).get(
            "result"
        )

        if not result:
            return None

        result = result[0]

        timestamps = result.get(
            "timestamp"
        )

        indicators = result.get(
            "indicators",
            {}
        )

        quote = indicators.get(
            "quote",
            [{}]
        )[0]

        if not timestamps:
            return None

        df = pd.DataFrame({

            "Date": pd.to_datetime(
                timestamps,
                unit="s"
            ),

            "Open": quote.get(
                "open"
            ),

            "High": quote.get(
                "high"
            ),

            "Low": quote.get(
                "low"
            ),

            "Close": quote.get(
                "close"
            ),

            "Volume": quote.get(
                "volume"
            )
        })

        df = df.dropna(
            subset=[
                "Close",
                "High",
                "Low",
                "Volume"
            ]
        )

        if len(df) < 60:
            return None

        return df

    except Exception as e:

        return None


# ============================================================
# 5. RSI
# ============================================================

def calculate_rsi(
    close,
    period=14
):

    delta = close.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi


# ============================================================
# 6. TECHNICAL 6/6 FILTER
# ============================================================

def technical_scan(
    symbol,
    df
):

    try:

        # EMA
        df["EMA20"] = (
            df["Close"]
            .ewm(
                span=20,
                adjust=False
            )
            .mean()
        )

        df["EMA50"] = (
            df["Close"]
            .ewm(
                span=50,
                adjust=False
            )
            .mean()
        )

        # RSI
        df["RSI14"] = calculate_rsi(
            df["Close"],
            14
        )

        # Volume average
        df["Volume20"] = (
            df["Volume"]
            .rolling(20)
            .mean()
        )

        # Previous 20-day high
        df["Previous20High"] = (
            df["High"]
            .shift(1)
            .rolling(20)
            .max()
        )

        # Support
        df["Low10"] = (
            df["Low"]
            .rolling(10)
            .min()
        )

        df["Low20"] = (
            df["Low"]
            .rolling(20)
            .min()
        )

        last = df.iloc[-1]

        entry = float(
            last["Close"]
        )

        ema20 = float(
            last["EMA20"]
        )

        ema50 = float(
            last["EMA50"]
        )

        rsi = float(
            last["RSI14"]
        )

        volume = float(
            last["Volume"]
        )

        volume20 = float(
            last["Volume20"]
        )

        previous20high = float(
            last["Previous20High"]
        )

        # ====================================================
        # 6 FILTERS
        # ====================================================

        filter1_trend = (
            entry > ema20
            and ema20 > ema50
        )

        filter2_ema = (
            entry > ema20
        )

        filter3_rsi = (
            55 <= rsi <= 70
        )

        filter4_volume = (
            volume >
            volume20 * 1.5
        )

        filter5_resistance = (
            entry >=
            previous20high * 0.98
        )

        filter6_breakout = (
            entry >
            previous20high
        )

        filters = [
            filter1_trend,
            filter2_ema,
            filter3_rsi,
            filter4_volume,
            filter5_resistance,
            filter6_breakout
        ]

        passed = sum(
            filters
        )

        if passed != 6:
            return None

        # ====================================================
        # TRADE SETUP
        # ====================================================

        support = max(
            float(last["Low10"]),
            float(last["Low20"])
        )

        sl = support * 0.99

        risk_per_share = (
            entry - sl
        )

        if risk_per_share <= 0:
            return None

        quantity = int(
            CAPITAL_RISK /
            risk_per_share
        )

        if quantity < 1:
            return None

        actual_risk = (
            risk_per_share *
            quantity
        )

        if actual_risk > CAPITAL_RISK:
            return None

        # 1:2
        t1 = (
            entry +
            risk_per_share * 2
        )

        # 1:3
        t2 = (
            entry +
            risk_per_share * 3
        )

        return {

            "symbol": symbol,

            "entry": round(
                entry,
                2
            ),

            "support": round(
                support,
                2
            ),

            "sl": round(
                sl,
                2
            ),

            "t1": round(
                t1,
                2
            ),

            "t2": round(
                t2,
                2
            ),

            "qty": quantity,

            "risk": round(
                actual_risk,
                2
            ),

            "rsi": round(
                rsi,
                2
            ),

            "volume_ratio": round(
                volume / volume20,
                2
            )
        }

    except Exception:

        return None


# ============================================================
# 7. SCAN ALL FUNDAMENTAL STOCKS
# ============================================================

def run_scan(nse_stocks):

    print("--------------------------------")
    print("STEP 3: TECHNICAL 6/6 SCAN")
    print("--------------------------------")

    setups = []

    total = len(nse_stocks)

    for index, item in enumerate(
        nse_stocks,
        start=1
    ):

        symbol = item["symbol"]

        print(
            f"[{index}/{total}] {symbol}"
        )

        df = get_yahoo_data(
            symbol
        )

        if df is None:
            continue

        result = technical_scan(
            symbol,
            df
        )

        if result:

            setups.append(
                result
            )

        # Small delay
        time.sleep(0.15)

    return setups


# ============================================================
# 8. FINAL OUTPUT
# ============================================================

def print_results(setups):

    print()
    print("================================")
    print("FINAL TRADE SETUPS")
    print("================================")

    if not setups:

        print(
            "NO STOCK PASSED ALL 6 FILTERS"
        )

        print(
            "Fundamental filter: Screener"
        )

        print(
            "Technical filter: 6/6"
        )

        print(
            "Risk per trade: Rs.300"
        )

        return

    print(
        f"FINAL TRADE SETUPS: {len(setups)}"
    )

    print("--------------------------------")

    for x in setups:

        print(
            f"{x['symbol']} | "
            f"Entry: {x['entry']} | "
            f"Support: {x['support']} | "
            f"SL: {x['sl']} | "
            f"T1: {x['t1']} | "
            f"T2: {x['t2']} | "
            f"Qty: {x['qty']} | "
            f"Risk: {x['risk']} | "
            f"RSI: {x['rsi']} | "
            f"Vol: {x['volume_ratio']}x"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("================================")
    print("NSE SWING SCANNER")
    print("================================")

    # 1. Screener fundamental universe
    companies = get_screener_companies()

    if not companies:

        print(
            "ERROR: Screener se stocks nahi mile."
        )

        raise SystemExit(1)

    # 2. Convert Screener companies
    #    into NSE symbols
    nse_stocks = get_nse_symbols(
        companies
    )

    if not nse_stocks:

        print(
            "ERROR: NSE symbols nahi mile."
        )

        raise SystemExit(1)

    # 3. Technical scan
    setups = run_scan(
        nse_stocks
    )

    # 4. Final result
    print_results(
        setups
    )


if __name__ == "__main__":
    main()
