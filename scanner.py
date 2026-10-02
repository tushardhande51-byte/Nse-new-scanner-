import urllib.request
import json

symbol = "RELIANCE.NS"

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


close = closes[-1]
previous_close = closes[-2]

ema20 = ema(closes, 20)
ema50 = ema(closes, 50)

rsi14 = rsi(closes, 14)

avg_volume20 = sum(volumes[-21:-1]) / 20
volume_multiple = volumes[-1] / avg_volume20

# Previous 20-day high, excluding today's candle
previous_20_high = max(closes[-21:-1])

# Previous 50-day high
previous_50_high = max(closes[-51:-1])

# -------------------------
# 6 FILTERS
# -------------------------

filter1_trend = close > ema20 > ema50

filter2_ema = close > ema20

filter3_rsi = 55 <= rsi14 <= 70

filter4_volume = volume_multiple > 1.5

# Price is within 3% of important resistance
near_20_resistance = close >= previous_20_high * 0.97
near_50_resistance = close >= previous_50_high * 0.97

filter5_resistance = near_20_resistance or near_50_resistance

# Breakout above previous 20-day high
filter6_breakout = close > previous_20_high and volume_multiple > 1.5

filters = [
    filter1_trend,
    filter2_ema,
    filter3_rsi,
    filter4_volume,
    filter5_resistance,
    filter6_breakout
]

score = sum(filters)

print("================================")
print("NSE SWING SCANNER - TECH TEST")
print("================================")

print("Stock:", symbol)
print("Close:", round(close, 2))
print("EMA20:", round(ema20, 2))
print("EMA50:", round(ema50, 2))
print("RSI14:", round(rsi14, 2))
print("Volume:", round(volume_multiple, 2), "x")
print("20D Resistance:", round(previous_20_high, 2))
print("50D Resistance:", round(previous_50_high, 2))

print("\n----------- FILTERS -----------")

print("1 Trend:", filter1_trend)
print("2 EMA:", filter2_ema)
print("3 RSI 55-70:", filter3_rsi)
print("4 Volume >1.5x:", filter4_volume)
print("5 Near Resistance:", filter5_resistance)
print("6 Breakout:", filter6_breakout)

print("\n==============================")
print("FINAL SCORE:", score, "/ 6")

if score == 6:
    print("🟢 BUY SIGNAL - ALL 6 FILTERS PASS")
else:
    print("🔴 NO SIGNAL - 6/6 NOT COMPLETE")
print("==============================")
