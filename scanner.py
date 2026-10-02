import urllib.request

url = "https://www.nseindia.com/api/marketStatus"

req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9"
    }
)

try:
    response = urllib.request.urlopen(req, timeout=20)
    data = response.read().decode("utf-8")
    print("NSE CONNECTION SUCCESS")
    print(data[:1000])
except Exception as e:
    print("NSE CONNECTION ERROR:", e)
    raise
