import argparse
import io
import os
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://www.screener.in"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
}
session = requests.Session()
session.headers.update(HEADERS)

# User-approved 100-point weighting.
WEIGHTS = {
    "Sales growth 3Y": 15,
    "Profit growth 3Y": 15,
    "EPS growth 3Y": 10,
    "ROCE": 15,
    "ROE": 10,
    "Debt/Equity": 10,
    "P/E valuation": 10,
    "OPM": 5,
    "Positive 3Y FCF": 5,
    "Pledged holding": 3,
    "Promoter holding": 2,
}


def num(value):
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "").replace("₹", "")
    if s.lower() in ("", "-", "--", "nan", "none", "na", "n/a"):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(match.group()) if match else None


def table(soup, section_id):
    section = soup.find(id=section_id)
    if not section or not section.find("table"):
        return None
    try:
        return pd.read_html(io.StringIO(str(section.find("table"))))[0]
    except Exception:
        return None


def row_values(df, patterns):
    """Return values from the matching row, retaining table order."""
    if df is None or df.empty:
        return []
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip().lower()
        # Screener appends "+" to expandable rows (e.g. "Borrowings +" and
        # "Promoters +"). Normalize these labels before matching.
        label = label.replace("\\xa0", " ")
        label = re.sub(r"\\s*\\+\\s*$", "", label)
        label = re.sub(r"\\s+", " ", label).strip()
        if any(re.search(pattern, label) for pattern in patterns):
            return [num(value) for value in row.iloc[1:].tolist()]
    return []


def clean_series(values):
    return [value for value in values if value is not None]


def latest(values):
    clean = clean_series(values)
    return clean[-1] if clean else None


def cagr(values):
    # Screener annual statements are displayed oldest to newest.
    values = clean_series(values)
    if len(values) < 4 or values[-1] <= 0 or values[-4] <= 0:
        return None
    return ((values[-1] / values[-4]) ** (1 / 3) - 1) * 100


def ratio(soup, labels):
    for item in soup.select("#top-ratios li"):
        name = item.select_one(".name")
        value = item.select_one(".value")
        if name and value:
            label = name.get_text(" ", strip=True).lower()
            if any(term in label for term in labels):
                parsed = num(value.get_text(" ", strip=True))
                if parsed is not None:
                    return parsed
    ratios_table = table(soup, "ratios")
    return latest(row_values(ratios_table, [re.escape(term) for term in labels]))


def company(query):
    response = session.get(
        BASE + "/api/company/search/", params={"q": query}, timeout=30
    )
    response.raise_for_status()
    found = response.json()
    if not found:
        raise ValueError("Company not found on Screener.in")

    item = found[0]
    url = BASE + item["url"]
    page = session.get(url, timeout=30)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    heading = soup.select_one("h1")
    name = heading.get_text(" ", strip=True) if heading else item.get("name", query)
    symbol = item["url"].split("/company/")[-1].split("/")[0].upper()

    pl = table(soup, "profit-loss")
    bs = table(soup, "balance-sheet")
    cf = table(soup, "cash-flow")
    sh = table(soup, "shareholding")
    peers = table(soup, "peers")

    sales = cagr(row_values(pl, [r"^sales(?:\s*\+)?$"]))
    profit = cagr(row_values(pl, [r"^net profit(?:\s*\+)?$"]))
    eps = cagr(row_values(pl, [r"^eps(?:\s+in\s+rs)?$"]))
    roce = ratio(soup, ["roce"])
    roe = ratio(soup, ["roe"])

    # Debt/equity: use a published ratio when available; otherwise calculate
    # total borrowings divided by equity capital + reserves from the balance sheet.
    de = ratio(soup, ["debt to equity", "debt/equity", "debt-equity"])
    if de is None:
        borrowings = latest(row_values(bs, [r"^borrowings?$"]))
        equity_capital = latest(row_values(bs, [r"^equity capital$", r"^share capital$"]))
        reserves = latest(row_values(bs, [r"^reserves(?:\s*&\s*surplus)?$", r"^other equity$"]))
        if borrowings is not None and equity_capital is not None and reserves is not None:
            total_equity = equity_capital + reserves
            if total_equity > 0:
                de = borrowings / total_equity
        # Some Screener balance sheets expose total equity directly.
        if de is None:
            total_equity = latest(row_values(bs, [r"^total equity$"]))
            if borrowings is not None and total_equity is not None and total_equity > 0:
                de = borrowings / total_equity

    opm = latest(row_values(pl, [r"^opm(?:\s*%)?$"]))

    # FCF must be positive in each of the latest three reported years.
    fcf_rows = row_values(cf, [r"^free cash flow$"])
    fcf_series = clean_series(fcf_rows)
    if len(fcf_series) >= 3:
        fcf = all(value > 0 for value in fcf_series[-3:])
    else:
        cfo = clean_series(row_values(cf, [r"cash from operating activit"]))
        capex = clean_series(row_values(cf, [
            r"fixed assets purchased",
            r"purchase of fixed assets",
            r"capital expenditure",
        ]))
        fcf = None
        count = min(3, len(cfo), len(capex))
        if count == 3:
            fcf = all(cfo[-i] - abs(capex[-i]) > 0 for i in range(1, 4))

    # Shareholding: use latest quarter from the Promoters row.
    promoter = latest(row_values(sh, [r"^promoters?$"]))
    # Pledged percentage may be a top-ratio or a row in shareholding data.
    pledged = ratio(soup, ["pledged percentage", "pledged"])
    if pledged is None:
        pledged = latest(row_values(sh, [r"pledged"]))

    pe = ratio(soup, ["stock p/e", "price to earning", "p/e"])
    industry_pe = None
    if peers is not None and not peers.empty:
        pe_col = next(
            (i for i, column in enumerate(peers.columns) if "p/e" in str(column).lower()),
            None,
        )
        if pe_col is not None:
            peer_values = [
                num(value) for value in peers.iloc[:, pe_col].tolist()
            ]
            peer_values = [value for value in peer_values if value is not None and value > 0]
            if peer_values:
                industry_pe = sum(peer_values) / len(peer_values)

    # Estimated PEG is context only; it can NEVER make a high-P/E stock pass.
    estimated_peg = pe / eps if pe is not None and eps is not None and eps > 0 else None
    pe_pass = None
    if pe is not None and pe > 0:
        pe_pass = pe < 15 or (
            industry_pe is not None and industry_pe > 0 and pe < industry_pe
        )

    metrics = {
        "Sales growth 3Y": sales,
        "Profit growth 3Y": profit,
        "EPS growth 3Y": eps,
        "ROCE": roce,
        "ROE": roe,
        "Debt/Equity": de,
        "P/E valuation": pe_pass,
        "OPM": opm,
        "Positive 3Y FCF": fcf,
        "Pledged holding": pledged,
        "Promoter holding": promoter,
    }

    tests = {
        "Sales growth 3Y": lambda value: value > 15,
        "Profit growth 3Y": lambda value: value > 15,
        "EPS growth 3Y": lambda value: value > 15,
        "ROCE": lambda value: value > 15,
        "ROE": lambda value: value > 15,
        "Debt/Equity": lambda value: value < 0.5,
        "P/E valuation": lambda value: value is True,
        "OPM": lambda value: value > 10,
        "Positive 3Y FCF": lambda value: value is True,
        "Pledged holding": lambda value: value < 5,
        "Promoter holding": lambda value: value > 35,
    }

    detail = {}
    passed = 0
    known = 0
    earned_points = 0
    available_points = 0
    for key, check in tests.items():
        value = metrics[key]
        if value is None:
            detail[key] = "NA"
            continue
        known += 1
        available_points += WEIGHTS[key]
        is_pass = bool(check(value))
        detail[key] = "PASS" if is_pass else "FAIL"
        if is_pass:
            passed += 1
            earned_points += WEIGHTS[key]

    # Normalize only across known weighted criteria, but require high coverage
    # before a company can enter the Top 5.
    score = round(earned_points / available_points * 100) if available_points else 0
    coverage = round(available_points / 100 * 100)
    return {
        "symbol": symbol,
        "company": name,
        "score": score,
        "passed": passed,
        "known": known,
        "coverage": coverage,
        "earned_points": earned_points,
        "available_points": available_points,
        "metrics": metrics,
        "detail": detail,
        "pe": pe,
        "industry_pe": industry_pe,
        "estimated_peg": estimated_peg,
        "url": url,
    }


def fmt(value, suffix=""):
    return "NA" if value is None else f"{value:.2f}{suffix}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks", required=True)
    args = parser.parse_args()
    stocks = list(dict.fromkeys(
        item.strip() for item in re.split(r"[,;\n]+", args.stocks) if item.strip()
    ))
    if len(stocks) > 100:
        raise SystemExit(
            f"Maximum 100 companies per run; received {len(stocks)}. "
            "Separate names with commas, semicolons, or new lines."
        )

    analysed = []
    errors = []
    print(f"FUNDAMENTAL-ONLY ANALYSIS | Input: {len(stocks)}")
    for stock in stocks:
        try:
            result = company(stock)
            analysed.append(result)
            print(
                f"Analysed {stock}: {result['passed']}/11 passed | "
                f"weighted score {result['score']}/100 | "
                f"data coverage {result['coverage']}%"
            )
        except Exception as exc:
            errors.append((stock, str(exc)))
            print(f"ERROR {stock}: {exc}")
        time.sleep(0.7)

    analysed.sort(
        key=lambda item: (
            item["score"], item["coverage"], item["passed"], item["known"]
        ),
        reverse=True,
    )
    eligible = [
        item for item in analysed
        if item["known"] >= 9 and item["coverage"] >= 75
    ]

    lines = [
        "TOP 5 FUNDAMENTAL STOCKS",
        f"Input: {len(stocks)} | Analysed: {len(analysed)} | Errors: {len(errors)}",
        f"Eligible (at least 9/11 metrics and 75% weighted data coverage): {len(eligible)}",
        "Fundamental ranking only. No technical analysis or intraday signal.",
        "Score = weighted PASS points / available weighted points; NA is never PASS.",
        "Weights: Sales 15, Profit 15, EPS 10, ROCE 15, ROE 10, D/E 10, P/E 10, OPM 5, FCF 5, Pledge 3, Promoter 2.",
        "P/E PASS only when P/E < 15 OR P/E is below peer average. Estimated PEG is informational only.",
        "",
    ]

    for rank, item in enumerate(eligible[:5], 1):
        metric = item["metrics"]
        lines += [
            f"{rank}. {item['symbol']} - {item['company']}",
            f"Weighted score {item['score']}/100 | Passed {item['passed']}/11 | Data {item['known']}/11 | Coverage {item['coverage']}%",
            f"Sales CAGR {fmt(metric['Sales growth 3Y'], '%')} | Profit CAGR {fmt(metric['Profit growth 3Y'], '%')} | EPS CAGR {fmt(metric['EPS growth 3Y'], '%')}",
            f"ROCE {fmt(metric['ROCE'], '%')} | ROE {fmt(metric['ROE'], '%')} | D/E {fmt(metric['Debt/Equity'])} | OPM {fmt(metric['OPM'], '%')}",
            f"3Y FCF positive: {metric['Positive 3Y FCF']} | Promoter {fmt(metric['Promoter holding'], '%')} | Pledged {fmt(metric['Pledged holding'], '%')}",
            f"P/E {fmt(item['pe'])} | Peer P/E {fmt(item['industry_pe'])} | Estimated PEG (info only) {fmt(item['estimated_peg'])}",
            "Checks: " + " | ".join(
                f"{key}: {value}" for key, value in item["detail"].items()
            ),
            f"Source: {item['url']}",
            "",
        ]

    if not eligible:
        lines += [
            "NO RELIABLE TOP 5: no company met the minimum data coverage rule.",
            "Check the Screener pages/data availability; do not treat missing metrics as PASS.",
            "",
        ]
    if errors:
        lines += ["NOT ANALYSED:"] + [
            f"{stock}: {error}" for stock, error in errors
        ]
    lines += [
        "NA metrics are excluded from score and shown as missing; they are not counted as passed.",
        "D/E is calculated only when borrowings and equity components are available.",
        "Fundamental quality does not guarantee intraday liquidity, volatility, or profit.",
    ]

    report = "\n".join(lines)
    print(report)
    with open("fundamental_top5_report.txt", "w", encoding="utf-8") as file:
        file.write(report)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram not sent: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID GitHub secrets are missing.")
    else:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": report[:3900],
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload))
        print("Telegram delivered successfully.")

    pd.DataFrame([
        {
            "Rank": rank,
            "Symbol": item["symbol"],
            "Company": item["company"],
            "WeightedScore": item["score"],
            "Passed": item["passed"],
            "DataAvailable": item["known"],
            "CoveragePercent": item["coverage"],
            **item["metrics"],
            "PE": item["pe"],
            "PeerPE": item["industry_pe"],
            "EstimatedPEGInfoOnly": item["estimated_peg"],
            "ScreenerURL": item["url"],
        }
        for rank, item in enumerate(eligible[:5], 1)
    ]).to_csv("fundamental_top5.csv", index=False)


if __name__ == "__main__":
    main()
