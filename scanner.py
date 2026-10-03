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

    for page in range(1, 11):

        url = SCREENER_URL

        if page > 1:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}page={page}"

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

            # Screener result table
            for row in soup.select(
                "table.data-table tbody tr"
            ):

                link = row.select_one(
                    "td.text a"
                )

                if not link:
                    link = row.select_one(
                        "a[href*='/company/']"
                    )

                if not link:
                    continue

                href = link.get(
                    "href",
                    ""
                ).strip()

                name = link.get_text(
                    " ",
                    strip=True
                )

                if not href or not name:
                    continue

                # ----------------------------------------
                # IMPORTANT:
                # Extract symbol directly from URL
                # ----------------------------------------

                match = re.search(
                    r"/company/([^/]+)/",
                    href
                )

                if not match:
                    continue

                symbol = match.group(1).upper()

                # Skip numeric BSE IDs
                if symbol.isdigit():
                    continue

                # Clean Screener URL variants
                symbol = symbol.replace(
                    "-",
                    ""
                )

                item = {
                    "name": name,
                    "symbol": symbol
                }

                if not any(
                    x["symbol"] == symbol
                    for x in companies
                ):

                    companies.append(
                        item
                    )

                    page_count += 1

            print(
                f"Screener page {page}: "
                f"{page_count} NSE candidates"
            )

            # If this page has no rows,
            # stop pagination
            if page_count == 0:
                break

            time.sleep(0.5)

        except Exception as e:

            print(
                f"Screener page {page} error: {e}"
            )

    print("--------------------------------")
    print(
        f"FUNDAMENTAL STOCKS FOUND: "
        f"{len(companies)}"
    )
    print("--------------------------------")

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
    print("STEP 2: Matching NSE Symbols")
    print("--------------------------------")

    # NSE equity list
    NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

    try:

        response = requests.get(
            NSE_URL,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        from io import StringIO

        nse_df = pd.read_csv(
            StringIO(response.text)
        )

        print(
            f"NSE equity list: {len(nse_df)} stocks"
        )

    except Exception as e:

        print(
            f"NSE list error: {e}"
        )

        return []

    # --------------------------------------------------------
    # Name cleaning
    # --------------------------------------------------------

    def clean_name(name):

        name = str(name).upper()

        replacements = [
            " LIMITED",
            " LTD",
            " LIMITED.",
            " LTD.",
            " INDIA",
            " INDIAN",
            " CORPORATION",
            " CORP",
            " COMPANY",
            " CO.",
            " PVT",
            " PRIVATE",
            " SERVICES",
            " SERVICE",
            " INDUSTRIES",
            " INDUSTRY",
            " ENTERPRISES",
            " ENTERPRISE",
            " HOLDINGS"
        ]

        for word in replacements:
            name = name.replace(
                word,
                ""
            )

        name = re.sub(
            r"[^A-Z0-9]",
            "",
            name
        )

        return name

    # --------------------------------------------------------
    # Prepare NSE names
    # --------------------------------------------------------

    nse_items = []

    for _, row in nse_df.iterrows():

        symbol = str(
            row.get(
                "SYMBOL",
                ""
            )
        ).strip()

        company_name = str(
            row.get(
                "NAME OF COMPANY",
                ""
            )
        ).strip()

        if not symbol or not company_name:
            continue

        nse_items.append(
            {
                "symbol": symbol,
                "name": company_name,
                "clean": clean_name(company_name)
            }
        )

    # --------------------------------------------------------
    # Matching
    # --------------------------------------------------------

    from difflib import SequenceMatcher

    results = []

    for company in companies:

        screener_name = company["name"]

        screener_clean = clean_name(
            screener_name
        )

        matched_symbol = None
        matched_name = None
        best_score = 0

        # --------------------------------------------
        # FIRST: exact cleaned-name match
        # --------------------------------------------

        for item in nse_items:

            if screener_clean == item["clean"]:

                matched_symbol = item["symbol"]
                matched_name = item["name"]
                best_score = 1.0

                break

        # --------------------------------------------
        # SECOND: partial match
        # --------------------------------------------

        if not matched_symbol:

            for item in nse_items:

                a = screener_clean
                b = item["clean"]

                if len(a) >= 6 and len(b) >= 6:

                    if (
                        a in b
                        or b in a
                    ):

                        score = (
                            min(len(a), len(b))
                            /
                            max(len(a), len(b))
                        )

                        if score > best_score:

                            best_score = score
                            matched_symbol = item["symbol"]
                            matched_name = item["name"]

        # --------------------------------------------
        # THIRD: fuzzy matching
        # --------------------------------------------

        if not matched_symbol:

            for item in nse_items:

                score = SequenceMatcher(
                    None,
                    screener_clean,
                    item["clean"]
                ).ratio()

                if score > best_score:

                    best_score = score
                    matched_symbol = item["symbol"]
                    matched_name = item["name"]

        # --------------------------------------------
        # Accept only reasonably strong match
        # --------------------------------------------

        if (
            matched_symbol
            and best_score >= 0.72
        ):

            results.append(
                {
                    "name": screener_name,
                    "symbol": matched_symbol
                }
            )

            print(
                f"MATCH: {screener_name} "
                f"-> {matched_symbol} "
                f"({best_score:.2f})"
            )

        else:

            print(
                f"SKIP: {screener_name} "
                f"(No reliable NSE match)"
            )

    # --------------------------------------------------------
    # Remove duplicates
    # --------------------------------------------------------

    unique = {}

    for item in results:

        symbol = item["symbol"]

        if symbol:
            unique[symbol] = item

    results = list(
        unique.values()
    )

    print("--------------------------------")
    print(
        f"FUNDAMENTAL STOCKS: {len(companies)}"
    )

    print(
        f"NSE SYMBOLS MATCHED: {len(results)}"
    )

    print("--------------------------------")

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
