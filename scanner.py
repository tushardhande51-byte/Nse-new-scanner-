import requests
import pandas as pd
import numpy as np
import time
import math
SCREENER_URL = "https://www.screener.in/screens/4008468/tushar-dhande/"

def get_fundamental_stocks():
    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(SCREENER_URL, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    stocks = []

    for row in soup.select("tr"):
        link = row.select_one("a[href*='/company/']")
        if link:
            name = link.get_text(strip=True)
            if name and name not in stocks:
                stocks.append(name)

    print(f"Fundamental stocks from Screener: {len(stocks)}")

    return stocks
CAPITAL = 30000
RISK_PER_TRADE = CAPITAL * 0.01

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_universe():
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    df = pd.read_csv(pd.io.common.StringIO(r.text))

    symbols = []

    for s in df["SYMBOL"].dropna():
        symbols.append(str(s).strip() + ".NS")

    return symbols


def get_data(symbol):

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?range=6mo&interval=1d"
    )

    r = requests.get(url, headers=HEADERS, timeout=15)

    if r.status_code != 200:
        return None

    data = r.json()

    result = data.get("chart", {}).get("result")

    if not result:
        return None

    result = result[0]

    timestamps = result.get("timestamp")
    quote = result.get("indicators", {}).get("quote", [{}])[0]

    if not timestamps:
        return None

    df = pd.DataFrame({
        "date": pd.to_datetime(timestamps, unit="s"),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "volume": quote.get("volume")
    })

    df = df.dropna().reset_index(drop=True)

    return df


def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

    return rsi


def check_setup(df):

    if len(df) < 60:
        return None

    close = df["close"]

    ema20 = close.ewm(
        span=20,
        adjust=False
    ).mean()

    ema50 = close.ewm(
        span=50,
        adjust=False
    ).mean()

    rsi = calculate_rsi(close)

    volume_avg20 = df["volume"].rolling(20).mean()

    entry = float(close.iloc[-1])

    ema20_now = float(ema20.iloc[-1])
    ema50_now = float(ema50.iloc[-1])

    rsi_now = float(rsi.iloc[-1])

    volume_now = float(df["volume"].iloc[-1])
    volume_avg = float(volume_avg20.iloc[-1])

    if volume_avg <= 0:
        return None

    volume_multiple = volume_now / volume_avg

    # Previous 20-day resistance
    previous_20_high = float(
        df["high"].iloc[-21:-1].max()
    )

    # Recent 10-day support
    support_10 = float(
        df["low"].iloc[-11:-1].min()
    )

    # Recent 20-day support
    support_20 = float(
        df["low"].iloc[-21:-1].min()
    )

    # --------------------------------
    # 6/6 TECHNICAL FILTERS
    # --------------------------------

    trend_ok = entry > ema20_now > ema50_now

    ema_ok = entry > ema20_now

    rsi_ok = 55 <= rsi_now <= 70

    volume_ok = volume_multiple >= 1.5

    resistance_ok = (
        entry >= previous_20_high * 0.98
    )

    breakout_ok = (
        entry > previous_20_high
    )

    filters = [
        trend_ok,
        ema_ok,
        rsi_ok,
        volume_ok,
        resistance_ok,
        breakout_ok
    ]

    if sum(filters) != 6:
        return None

    # --------------------------------
    # IMPROVED STOP LOSS
    # --------------------------------

    # Use the stronger/higher support
    support = max(
        support_10,
        support_20
    )

    # SL 1% below support
    stop_loss = support * 0.99

    if stop_loss >= entry:
        return None

    risk_per_share = entry - stop_loss

    if risk_per_share <= 0:
        return None

    # --------------------------------
    # QUANTITY
    # --------------------------------

    quantity = math.floor(
        RISK_PER_TRADE / risk_per_share
    )

    # Cannot take even 1 share within ₹300 risk
    if quantity < 1:
        return None

    actual_risk = quantity * risk_per_share

    # Absolute risk protection
    if actual_risk > RISK_PER_TRADE:
        return None

    # --------------------------------
    # TARGETS
    # --------------------------------

    target1 = entry + (
        risk_per_share * 2
    )

    target2 = entry + (
        risk_per_share * 3
    )

    breakout_percent = (
        (entry - previous_20_high)
        / previous_20_high
    ) * 100

    stop_distance = (
        (entry - stop_loss)
        / entry
    ) * 100

    return {
        "entry": round(entry, 2),
        "sl": round(stop_loss, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "quantity": quantity,
        "risk": round(actual_risk, 2),
        "rsi": round(rsi_now, 2),
        "volume_multiple": round(volume_multiple, 2),
        "breakout_percent": round(breakout_percent, 2),
        "stop_distance": round(stop_distance, 2),
        "support": round(support, 2)
    }


print("================================")
print("NSE 6/6 SWING SCANNER")
print("================================")

print("Capital: ₹", CAPITAL)
print("Max risk/trade: ₹", RISK_PER_TRADE)
print()

symbols = get_universe()

print("Universe:", len(symbols))
print()

signals = []
errors = 0

for i, symbol in enumerate(symbols, 1):

    try:

        df = get_data(symbol)

        if df is None:
            errors += 1
            continue

        setup = check_setup(df)

        if setup:

            signals.append(
                (symbol, setup)
            )

            print("🟢 6/6 TRADE SETUP")
            print("Stock:", symbol)
            print("Entry:", setup["entry"])
            print("Support:", setup["support"])
            print("SL:", setup["sl"])
            print("Target 1:", setup["target1"])
            print("Target 2:", setup["target2"])
            print("Quantity:", setup["quantity"])
            print("Risk:", setup["risk"])
            print("SL distance:", setup["stop_distance"], "%")
            print("RSI:", setup["rsi"])
            print("Volume:", setup["volume_multiple"], "x")
            print("Breakout:", setup["breakout_percent"], "%")
            print()

    except Exception:
        errors += 1

    if i % 100 == 0:
        print(
            f"Progress: {i} / {len(symbols)}"
        )

    time.sleep(0.25)


print()
print("================================")
print("SCAN COMPLETE")
print("================================")

print("Processed:", len(symbols))
print("Errors:", errors)
print()

print(
    "FINAL TRADE SETUPS:",
    len(signals)
)

print("--------------------------------")

for symbol, setup in signals:

    print(
        f"{symbol} | "
        f"Entry: {setup['entry']} | "
        f"Support: {setup['support']} | "
        f"SL: {setup['sl']} | "
        f"T1: {setup['target1']} | "
        f"T2: {setup['target2']} | "
        f"Qty: {setup['quantity']} | "
        f"Risk: {setup['risk']}"
    )
