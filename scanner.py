import os
import urllib.parse
import urllib.request
import urllib.error

token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

message = "🟢 NSE Swing Scanner\n\nTelegram notification test successful! ✅"

url = f"https://api.telegram.org/bot{token}/sendMessage"

data = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": message
}).encode()

try:
    response = urllib.request.urlopen(url, data=data)
    print("SUCCESS:", response.read().decode())
except urllib.error.HTTPError as e:
    print("TELEGRAM ERROR:", e.read().decode())
    raise
