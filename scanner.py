import urllib.request

url = "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=1mo&interval=1d"

req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0"
    }
)

try:
    response = urllib.request.urlopen(req, timeout=20)
    data = response.read().decode("utf-8")

    print("MARKET DATA SUCCESS")
    print(data[:2000])

except Exception as e:
    print("MARKET DATA ERROR:", e)
    raise
