import urllib.request

url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"

req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/"
    }
)

try:
    response = urllib.request.urlopen(req, timeout=20)
    data = response.read().decode("utf-8")

    print("NIFTY 500 DATA SUCCESS")
    print(data[:2000])

except Exception as e:
    print("NIFTY 500 DATA ERROR:", e)
    raise
