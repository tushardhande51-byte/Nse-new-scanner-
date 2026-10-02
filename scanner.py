import urllib.request
import json
import csv
import io
import time

UNIVERSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"


# =========================
# GET NSE STOCK UNIVERSE
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
# GET STOCK DATA
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

    closes = [
        x for x in quote["close"]
        if x is not None
    ]

    volumes = [
        x for x in quote["volume"]
        if x is not None
    ]

    if len(closes) < 60 or len(volumes) < 60:
        return None

    return closes, volumes


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
# 6/6 ANALYSIS
# =========================

def analyze(symbol):

    data = get_data(symbol)

    if data is None:
        return None

    closes, volumes = data

    close = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi14 = rsi(closes, 14)

    avg_volume20 = (
        sum(volumes[-21:-1]) / 20
    )

    if avg_volume20 <= 0:
        return None

    volume_multiple = (
        volumes[-1] / avg_volume20
    )

    previous_20_high = max(
        closes[-21:-1]
    )

    previous_50_high = max(
        closes[-51:-1]
    )

    # FILTER 1
    f1 = close > ema20 > ema50

    # FILTER 2
    f2 = close > ema20

    # FILTER 3
    f3 = 55 <= rsi14 <= 70

    # FILTER 4
    f4 = volume_multiple > 1.5

    # FILTER 5
    near_20 = (
        close >= previous_20_high * 0.97
    )

    near_50 = (
        close >= previous_50_high * 0.97
    )

    f5 = near_20 or near_50

    # FILTER 6
    f6 = (
        close > previous_20_high
        and volume_multiple > 1.5
    )

    score = sum([
        f1,
        f2,
        f3,
        f4,
        f5,
        f6
    ])

    return {
        "symbol": symbol,
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "volume": volume_multiple,
        "resistance": previous_20_high,
        "score": score
    }


# =========================
# MAIN SCANNER
# =========================

print("================================")
print("NSE 6/6 FULL UNIVERSE SCANNER")
print("================================")

stocks = get_universe()

print("Universe size:", len(stocks))
print()

signals = []

processed = 0
errors = 0

for symbol in stocks:

    try:

        result = analyze(symbol)

        processed += 1

        if result is not None:

            if result["score"] == 6:

                signals.append(result)

                print(
                    "🟢 6/6:",
                    result["symbol"],
                    "| Close:",
                    round(result["close"], 2),
                    "| RSI:",
                    round(result["rsi"], 2),
                    "| Volume:",
                    round(result["volume"], 2),
                    "x"
                )

        if processed % 50 == 0:

            print(
                "Progress:",
                processed,
                "/",
                len(stocks)
            )

        # Small delay to reduce request pressure
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
# FINAL RESULT
# =========================

print()
print("================================")
print("SCAN COMPLETE")
print("================================")

print("Stocks processed:", processed)
print("Errors:", errors)

print()
print("FINAL 6/6 SIGNALS:", len(signals))

print("--------------------------------")

if signals:

    for x in signals:

        print(
            "🟢",
            x["symbol"],
            "| Score: 6/6",
            "| Close:",
            round(x["close"], 2),
            "| RSI:",
            round(x["rsi"], 2),
            "| Vol:",
            round(x["volume"], 2),
            "x",
            "| Resistance:",
            round(x["resistance"], 2)
        )

else:

    print("No 6/6 signals found.")

print("================================")
