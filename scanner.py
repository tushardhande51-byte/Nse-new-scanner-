import urllib.request
import json
import math

symbol = "RELIANCE.NS"

url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=6mo&interval=1d"

req = urllib.request.Request(
    url,
    headers={"User-Agent": "Mozilla/5.0"}
)

response = urllib.request.urlopen(req, timeout=20)
data = json.loads(response.read().decode("utf-8"))

result = data["chart"]["result"][0]

closes = result["indicators"]["quote"][0]["close"]
volumes = result["indicators"]["quote"][0]["volume"]

# Remove missing values
prices = [x for x in closes if x is not None]
vols = [x for x in volumes if x is not None]

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

close = prices[-1]

ema20 = ema(prices, 20)
ema50 = ema(prices, 50)
rsi14 = rsi(prices, 14)

avg_volume20 = sum(vols[-21:-1]) / 20
volume_multiple = vols[-1] / avg_volume20

print("===== TECHNICAL DATA TEST =====")
print("Stock:", symbol)
print("Close:", round(close, 2))
print("EMA 20:", round(ema20, 2))
print("EMA 50:", round(ema50, 2))
print("RSI 14:", round(rsi14, 2))
print("Volume multiple:", round(volume_multiple, 2), "x")

print("\n===== FILTER TEST =====")
print("Trend:", close > ema20 > ema50)
print("EMA:", close > ema20)
print("RSI 55-70:", 55 <= rsi14 <= 70)
print("Volume > 1.5x:", volume_multiple > 1.5)
