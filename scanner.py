import os
import re
import requests
from bs4 import BeautifulSoup


SCREENER_URL = "https://www.screener.in/screens/4008468/tushar-dhande/"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0 Mobile Safari/537.36"
    )
}


def send_telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("Telegram status:", r.status_code)

        if r.ok:
            print("Telegram: SENT")
            return True

        print("Telegram error:", r.text)
        return False

    except Exception as e:
        print("Telegram exception:", e)
        return False


def get_screener_stocks():

    print()
    print("==========================================")
    print("     SCREENER FUNDAMENTAL SCREEN")
    print("==========================================")

    session = requests.Session()
    session.headers.update(HEADERS)

    stocks = []

    # Read multiple result pages
    for page in range(1, 20):

        if page == 1:
            url = SCREENER_URL
        else:
            url = SCREENER_URL + f"?page={page}"

        try:

            response = session.get(
                url,
                timeout=30
            )

            print(
                f"Page {page}: HTTP "
                f"{response.status_code}"
            )

            if response.status_code != 200:
                print("Screener request failed")
                break

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            page_count = 0

            # Screener result table
            rows = soup.select(
                "table.data-table tbody tr"
            )

            for row in rows:

                link = row.select_one(
                    "a[href*='/company/']"
                )

                if not link:
                    continue

                name = link.get_text(
                    " ",
                    strip=True
                )

                href = link.get(
                    "href",
                    ""
                )

                # Extract NSE symbol from company URL
                match = re.search(
                    r"/company/([^/]+)/",
                    href
                )

                symbol = (
                    match.group(1)
                    if match
                    else ""
                )

                if not name:
                    continue

                key = (
                    symbol
                    if symbol
                    else name
                )

                if not any(
                    x["key"] == key
                    for x in stocks
                ):

                    stocks.append({
                        "name": name,
                        "symbol": symbol,
                        "key": key
                    })

                    page_count += 1

            print(
                f"Page {page}: "
                f"{page_count} stocks"
            )

            if page_count == 0:
                break

        except Exception as e:

            print(
                f"Page {page} error:",
                e
            )

            break

    return stocks


def send_results(stocks):

    print()
    print("==========================================")
    print(
        "FUNDAMENTAL PASS:",
        len(stocks)
    )
    print("==========================================")

    if not stocks:

        send_telegram(
            "🔔 NSE FUNDAMENTAL SCANNER\n\n"
            "⚠️ No stocks received from Screener.\n\n"
            "Please check the Screener screen."
        )

        return

    # Telegram has message-size limits,
    # so split into several messages.
    chunk_size = 40

    for start in range(
        0,
        len(stocks),
        chunk_size
    ):

        chunk = stocks[
            start:start + chunk_size
        ]

        message = (
            "🔔 NSE FUNDAMENTAL SCREEN\n\n"
            "✅ FUNDAMENTAL PASS\n\n"
        )

        for i, stock in enumerate(
            chunk,
            start=start + 1
        ):

            message += (
                f"{i}. {stock['name']}\n"
            )

        message += (
            f"\nTotal PASS: {len(stocks)}"
        )

        if start + chunk_size >= len(stocks):

            message += (
                "\n\n➡️ Next step: "
                "6 technical filters"
            )

        send_telegram(
            message
        )


def main():

    print()
    print("==========================================")
    print("       NSE FUNDAMENTAL SCANNER")
    print("       STAGE 1")
    print("==========================================")

    stocks = get_screener_stocks()

    print()
    print("Stocks received from Screener:",
          len(stocks))

    for i, stock in enumerate(
        stocks,
        start=1
    ):

        print(
            f"{i}. {stock['name']}"
        )

    send_results(
        stocks
    )

    print()
    print("==========================================")
    print("STAGE 1 COMPLETE")
    print("==========================================")


if __name__ == "__main__":
    main()
