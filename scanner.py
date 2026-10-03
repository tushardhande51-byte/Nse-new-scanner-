import urllib.request
import json
import csv
import io
import time
import math

UNIVERSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

CAPITAL = 30000
RISK_PERCENT = 0.01
MAX_RISK = CAPITAL * RISK_PERCENT


# =========================
# NSE UNIVERSE
# =========================

def get_universe():

    req = urllib.request.Request(
        UNIVERSE_URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    response = urllib.request.urlopen(req, timeout=30)
    data = response.read().decode("utf-8")

    reader = csv.DictReader(io.StringIO(data))

    stocks = []

    for row in reader:

        symbol = row.get("SYMBOL", "").strip()

        if symbol:
            stocks.append(symbol + ".NS")

    return stocks


# =========================
# MARKET DATA
# =========================

def get_data(symbol):

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?range=6mo&interval=1d"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    response = urllib.request.urlopen(req, timeout=20)

    data = json.loads(
        response.read().decode("utf-8")
    )

    result = data["chart"]["result"][0]

    quote = result["indicators"]["quote"][0]

    opens = [
        x for x in quote["open"]
        if x is not None
    ]

    highs = [
        x for x in quote["high"]
        if x is not None
    ]

    lows = [
        x for x in quote["low"]
        if x is not None
    ]

    closes = [
        x for x in quote["close"]
        if x is not None
    ]

    volumes = [
        x for x in quote["volume"]
        if x is not None
    ]

    if len(closes) < 60:
        return None

    return opens, highs, lows, closes, volumes


# =========================
# EMA
# =========================

def ema(values, period):

    multiplier = 2 / (period + 1)

    value = sum(values[:period]) / period

    for price in values[period:]:

        value = (
            (price - value) * multiplier
            + value
        )

    return value


# =========================
# RSI
# =========================

def rsi(values, period=14):

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# =========================
# ANALYZE STOCK
# =========================

def analyze(symbol):

    data = get_data(symbol)

    if data is None:
        return None

    opens, highs, lows, closes, volumes = data

    close = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi14 = rsi(closes, 14)

    avg_volume20 = sum(
        volumes[-21:-1]
    ) / 20

    if avg_volume20 <= 0:
        return None

    volume_multiple = (
        volumes[-1] / avg_volume20
    )

    previous_20_high = max(
        highs[-21:-1]
    )

    previous_50_high = max(
        highs[-51:-1]
    )

    # =========================
    # 6 FILTERS
    # =========================

    f1 = close > ema20 > ema50

    f2 = close > ema20

    f3 = 55 <= rsi14 <= 70

    f4 = volume_multiple > 1.5

    near20 = close >= previous_20_high * 0.97
    near50 = close >= previous_50_high * 0.97

    f5 = near20 or near50

    f6 = (
        close > previous_20_high
        and volume_multiple > 1.5
    )

    score = sum([
        f1, f2, f3, f4, f5, f6
    ])

    if score != 6:
        return None

    # =========================
    # ENTRY
    # =========================

    entry = close

    # Recent 10-day swing low
    swing_low = min(
        lows[-11:-1]
    )

    # Small safety buffer below support
    stop_loss = swing_low * 0.99

    risk_per_share = entry - stop_loss

    if risk_per_share <= 0:
        return None

    # =========================
    # POSITION SIZE
    # =========================

    quantity = math.floor(
        MAX_RISK / risk_per_share
    )

    if quantity < 1:
        quantity = 1

    actual_risk = (
        risk_per_share * quantity
    )

    # =========================
    # TARGETS
    # =========================

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

    return {
        "symbol": symbol,
        "entry": entry,
        "sl": stop_loss,
        "target1": target1,
        "target2": target2,
        "quantity": quantity,
        "risk_share": risk_per_share,
        "actual_risk": actual_risk,
        "rsi": rsi14,
        "volume": volume_multiple,
        "breakout": breakout_percent
    }


# =========================
# MAIN
# =========================

print("================================")
print("NSE 6/6 TRADE SETUP SCANNER")
print("================================")

print("Capital: ₹", CAPITAL)
print("Max risk/trade: ₹", MAX_RISK)
print()

stocks = get_universe()

print("Universe:", len(stocks))
print()

signals = []

processed = 0
errors = 0

for symbol in stocks:

    try:

        result = analyze(symbol)

        processed += 1

        if result:

            signals.append(result)

            print()
            print("🟢 6/6 TRADE SETUP")
            print("Stock:", result["symbol"])
            print("Entry:", round(result["entry"], 2))
            print("SL:", round(result["sl"], 2))
            print("Target 1:", round(result["target1"], 2))
            print("Target 2:", round(result["target2"], 2))
            print("Quantity:", result["quantity"])
            print(
                "Risk:",
                round(result["actual_risk"], 2)
            )
            print(
                "RSI:",
                round(result["rsi"], 2)
            )
            print(
                "Volume:",
                round(result["volume"], 2),
                "x"
            )
            print(
                "Breakout:",
                round(result["breakout"], 2),
                "%"
            )

        if processed % 100 == 0:

            print(
                "Progress:",
                processed,
                "/",
                len(stocks)
            )

        time.sleep(0.5)

    except Exception as e:

        errors += 1

        print(
            "ERROR:",
            symbol,
            "|",
            str(e)
        )

        continue


# =========================
# FINAL
# =========================

print()
print("================================")
print("SCAN COMPLETE")
print("================================")

print("Processed:", processed)
print("Errors:", errors)

print()
print("FINAL TRADE SETUPS:", len(signals))

print("--------------------------------")

for x in signals:

    print(
        x["symbol"],
        "| Entry:",
        round(x["entry"], 2),
        "| SL:",
        round(x["sl"], 2),
        "| T1:",
        round(x["target1"], 2),
        "| T2:",
        round(x["target2"], 2),
        "| Qty:",
        x["quantity"],
        "| Risk:",
        round(x["actual_risk"], 2)
    )

print("================================")
