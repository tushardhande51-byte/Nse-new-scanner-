import requests
import pandas as pd
import numpy as np
import time
import math

CAPITAL = 30000
RISK_PER_TRADE = CAPITAL * 0.01
MAX_STOP_DISTANCE = 0.08

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

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

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

    # Previous 20-day high, excluding today's candle
    previous_20_high = float(df["high"].iloc[-21:-1].max())

    # Recent 10-day swing low, excluding today's candle
    swing_low = float(df["low"].iloc[-11:-1].min())

    # 6 technical filters
    trend_ok = entry > ema20_now > ema50_now
    ema_ok = entry > ema20_now
    rsi_ok = 55 <= rsi_now <= 70
    volume_ok = volume_multiple >= 1.5
    breakout_ok = entry > previous_20_high

    # Price must be close to breakout/resistance
    resistance_ok = (
        entry >= previous_20_high * 0.98
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

    # -----------------------------
    # RISK MANAGEMENT
    # -----------------------------

    # SL 1% below recent swing low
    stop_loss = swing_low * 0.99

    # Maximum allowed SL distance = 8%
    stop_distance = (entry - stop_loss) / entry

    # If support-based SL is too far away, reject trade
    if stop_distance > MAX_STOP_DISTANCE:
        return None

    if stop_loss >= entry:
        return None

    risk_per_share = entry - stop_loss

    if risk_per_share <= 0:
        return None

    # Quantity according to ₹300 max risk
    quantity = math.floor(RISK_PER_TRADE / risk_per_share)

    if quantity < 1:
        return None

    actual_risk = quantity * risk_per_share

    # Absolute protection: risk can NEVER exceed ₹300
    if actual_risk > RISK_PER_TRADE:
        return None

    target1 = entry + (risk_per_share * 2)
    target2 = entry + (risk_per_share * 3)

    breakout_percent = (
        (entry - previous_20_high)
        / previous_20_high
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
        "stop_distance": round(stop_distance * 100, 2)
    }


print("================================")
print("NSE 6/6 RISK-MANAGED SCANNER")
print("================================")
print("Capital: ₹", CAPITAL)
print("Max risk/trade: ₹", RISK_PER_TRADE)
print("Max SL distance:", MAX_STOP_DISTANCE * 100, "%")
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
print("FINAL TRADE SETUPS:", len(signals))
print("--------------------------------")

for symbol, setup in signals:

    print(
        f"{symbol} | "
        f"Entry: {setup['entry']} | "
        f"SL: {setup['sl']} | "
        f"T1: {setup['target1']} | "
        f"T2: {setup['target2']} | "
        f"Qty: {setup['quantity']} | "
        f"Risk: {setup['risk']} | "
        f"SL%: {setup['stop_distance']}%"
    )
