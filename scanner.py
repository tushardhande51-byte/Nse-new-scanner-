import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote


# =========================================================
# SETTINGS
# =========================================================

SCREENER_QUERY = """
Market Capitalization > 500
AND Market Capitalization < 20000
AND Price to Earning < 15
AND Debt to equity < 0.5
AND Sales growth 5Years > 15
AND Profit growth 5Years > 20
AND Average return on capital employed 5Years > 15
AND Average return on equity 5Years > 15
AND Promoter holding > 50
AND PEG Ratio < 1
AND Pledged percentage < 1
"""

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 "
        "(Linux; Android 10) "
        "AppleWebKit/537.36 "
        "Chrome/154.0 Safari/537.36"
}


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID missing")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print(
            "Telegram status:",
            response.status_code
        )

        if response.ok:
            print("Telegram: SENT")
            return True

        print(
            "Telegram error:",
            response.text
        )

        return False

    except Exception as e:

        print(
            "Telegram exception:",
            e
        )

        return False


# =========================================================
# SCREENER
# =========================================================

def get_fundamental_stocks():

    print()
    print("==========================================")
    print("     FUNDAMENTAL 11/11 SCANNER")
    print("==========================================")

    print()
    print("Applying 11 fundamental filters...")

    query = " ".join(
        SCREENER_QUERY.split()
    )

    encoded_query = quote(
        query
    )

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    stocks = []

    # Screener results are paginated.
    # Read pages until no more companies are found.
    for page in range(1, 20):

        url = (
            "https://www.screener.in/screen/raw/"
            f"?query={encoded_query}"
            f"&page={page}"
        )

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

                print(
                    "Screener request failed."
                )

                break

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            page_stocks = []

            # Company links
            for link in soup.select(
                "a[href*='/company/']"
            ):

                name = link.get_text(
                    " ",
                    strip=True
                )

                href = link.get(
                    "href",
                    ""
                )

                if not name:
                    continue

                if "/company/" not in href:
                    continue

                # Avoid duplicate names
                if name not in stocks:
                    page_stocks.append(
                        name
                    )

            # Remove duplicates within page
            page_stocks = list(
                dict.fromkeys(
                    page_stocks
                )
            )

            print(
                f"Page {page}: "
                f"{len(page_stocks)} stocks"
            )

            if not page_stocks:
                break

            for name in page_stocks:

                if name not in stocks:
                    stocks.append(
                        name
                    )

        except Exception as e:

            print(
                "Screener error:",
                e
            )

            break

    return stocks


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def send_results(stocks):

    if not stocks:

        message = (
            "🔔 NSE FUNDAMENTAL SCANNER\n\n"
            "11/11 FILTER PASS: 0\n\n"
            "Aaj koi stock 11 fundamental "
            "filters pass nahi hua."
        )

        send_telegram(
            message
        )

        return

    message = (
        "🔔 NSE FUNDAMENTAL SCANNER\n\n"
        "✅ 11/11 FILTER PASS\n\n"
    )

    for i, stock in enumerate(
        stocks,
        start=1
    ):

        message += (
            f"{i}. {stock}\n"
        )

    message += (
        f"\n📊 Total PASS: "
        f"{len(stocks)}\n\n"
        "Next Step:\n"
        "In stocks par 6 technical "
        "filters lagaye jayenge."
    )

    send_telegram(
        message
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("==========================================")
    print("       NSE FUNDAMENTAL SCANNER")
    print("       STAGE 1")
    print("==========================================")

    print()
    print("11 FILTERS:")
    print("1. Market Cap > 500 Cr")
    print("2. Market Cap < 20,000 Cr")
    print("3. P/E < 15")
    print("4. Debt/Equity < 0.5")
    print("5. Sales Growth 5Y > 15%")
    print("6. Profit Growth 5Y > 20%")
    print("7. Average ROCE 5Y > 15%")
    print("8. Average ROE 5Y > 15%")
    print("9. Promoter Holding > 50%")
    print("10. PEG Ratio < 1")
    print("11. Pledged Percentage < 1%")

    stocks = get_fundamental_stocks()

    print()
    print("==========================================")
    print(
        "TOTAL FUNDAMENTAL PASS:",
        len(stocks)
    )
    print("==========================================")

    for i, stock in enumerate(
        stocks,
        start=1
    ):

        print(
            f"{i}. {stock}"
        )

    # Send names to Telegram
    send_results(
        stocks
    )

    print()
    print("==========================================")
    print("STAGE 1 COMPLETE")
    print("==========================================")


if __name__ == "__main__":
    main()
