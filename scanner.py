import urllib.request
import csv
import io

URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

req = urllib.request.Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

try:
    response = urllib.request.urlopen(req, timeout=30)
    data = response.read().decode("utf-8")

    reader = csv.DictReader(io.StringIO(data))

    stocks = []

    for row in reader:
        symbol = row.get("SYMBOL", "").strip()

        if symbol:
            stocks.append(symbol + ".NS")

    print("================================")
    print("NSE STOCK UNIVERSE TEST")
    print("================================")

    print("Total stocks found:", len(stocks))

    print("\nFirst 20 stocks:")

    for stock in stocks[:20]:
        print(stock)

    print("\n================================")
    print("NSE UNIVERSE DOWNLOAD SUCCESS")
    print("================================")

except Exception as e:
    print("NSE UNIVERSE ERROR:", e)
    raise
