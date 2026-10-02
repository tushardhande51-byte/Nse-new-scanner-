import os
import urllib.parse

client_id = os.environ["FYERS_CLIENT_ID"]
redirect_uri = "http://127.0.0.1:5000/callback"

params = {
    "client_id": client_id,
    "redirect_uri": redirect_uri,
    "response_type": "code",
    "state": "nse_scanner"
}

url = "https://api-t1.fyers.in/api/v3/generate-authcode?" + urllib.parse.urlencode(params)

print("FYERS LOGIN URL:")
print(url)
