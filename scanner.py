import urllib.request
import json
import time

STOCKS = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "LT.NS",
    "AXISBANK.NS"
]

def get_data(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=6mo&interval=1d"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    response = urllib.request.urlopen(req, timeout=20)
    data = json.loads(response.read().decode("utf-8"))

    result = data["chart"]["result"][0]
    q = result["indicators"]["quote"][0]

    closes = [x for x in q["close"] if x is not None]
    volumes = [x for x in q["volume"] if x is not None]

    return closes, volumes


def ema(values, period):
    multiplier = 2 / (period + 1)
    value = sum(values[:period]) / period

    for price in values[period:]:
        value = (price - value) * multiplier + value

    return value


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
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


print("================================")
print("NSE 6/6 SWING SCANNER TEST")
print("================================")

signals = []

for symbol in STOCKS:

    try:
        closes, volumes = get_data(symbol)

        close = closes[-1]

        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)

        rsi14 = rsi(closes, 14)

        avg_volume20 = sum(volumes[-21:-1]) / 20
        volume_multiple = volumes[-1] / avg_volume20

        previous_20_high = max(closes[-21:-1])
        previous_50_high = max(closes[-51:-1])

        f1 = close > ema20 > ema50
        f2 = close > ema20
        f3 = 55 <= rsi14 <= 70
        f4 = volume_multiple > 1.5

        near20 = close >= previous_20_high * 0.97
        near50 = close >= previous_50_high * 0.97

        f5 = near20 or near50
        f6 = close > previous_20_high and volume_multiple > 1.5

        score = sum([f1, f2, f3, f4, f5, f6])

        print(
            symbol,
            "| Score:", score, "/6",
            "| Close:", round(close, 2),
            "| RSI:", round(rsi14, 1),
            "| Vol:", round(volume_multiple, 2), "x"
        )

        if score == 6:
            signals.append(symbol)

        time.sleep(1)

    except Exception as e:
        print(symbol, "| ERROR:", e)

print("\n================================")
print("FINAL 6/6 SIGNALS")
print("================================")

if signals:
    for stock in signals:
        print("🟢", stock)
else:
    print("No 6/6 signals found.")

print("================================")
