import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

# Separate positional scanner. It does not alter or import trend_scanner.py.
NSE_CSV_URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
]
NSE_HOME = "https://www.nseindia.com/"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}.NS"
TIMEOUT = 25
MAX_WORKERS = 10
MIN_DAILY_ROWS = 80
MIN_HOURLY_ROWS = 2
VOLUME_MULTIPLIER = 1.5
MIN_SCORE = 5
HOLDING_MIN_DAYS = 5
HOLDING_MAX_DAYS = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Accept": "application/json,text/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def now_ist():
    return datetime.now(ZoneInfo("Asia/Kolkata"))


def get_nse_universe():
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(NSE_HOME, timeout=TIMEOUT)
    except requests.RequestException:
        pass
    last_error = None
    for url in NSE_CSV_URLS:
        try:
            response = session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            frame = pd.read_csv(io.BytesIO(response.content))
            frame.columns = [str(c).strip().upper() for c in frame.columns]
            if "SYMBOL" not in frame.columns or "SERIES" not in frame.columns:
                raise ValueError("NSE EQ CSV missing SYMBOL/SERIES")
            frame["SYMBOL"] = frame["SYMBOL"].astype(str).str.strip()
            frame["SERIES"] = frame["SERIES"].astype(str).str.strip().str.upper()
            frame = frame[
                (frame["SERIES"] == "EQ")
                & frame["SYMBOL"].str.fullmatch(r"[A-Z0-9&._-]+")
            ].drop_duplicates("SYMBOL")
            if frame.empty:
                raise ValueError("NSE EQ universe is empty")
            name_col = "NAME OF COMPANY" if "NAME OF COMPANY" in frame.columns else None
            return [
                (row["SYMBOL"], str(row[name_col]).strip() if name_col else row["SYMBOL"])
                for _, row in frame.iterrows()
            ]
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not download NSE EQ list: {last_error}")


def fetch_chart(symbol, period, interval, min_rows=2):
    url = YAHOO_CHART.format(requests.utils.quote(symbol, safe=""))
    params = {"range": period, "interval": interval, "events": "history"}
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if response.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            response.raise_for_status()
            chart = response.json().get("chart", {})
            if chart.get("error") or not chart.get("result"):
                return None
            result = chart["result"][0]
            quote = result["indicators"]["quote"][0]
            frame = pd.DataFrame({
                "date": pd.to_datetime(result["timestamp"], unit="s", utc=True),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
            }).dropna(subset=["high", "low", "close"])
            frame = frame.sort_values("date").reset_index(drop=True)
            return frame if len(frame) >= min_rows else None
        except Exception:
            if attempt < 2:
                time.sleep(1 + attempt)
    return None


def closed_daily_bars(frame, now):
    if frame is None or frame.empty:
        return pd.DataFrame()
    local_dates = frame["date"].dt.tz_convert("Asia/Kolkata").dt.date
    # Before the NSE close, exclude today's still-forming daily candle.
    market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
    mask = (local_dates < now.date()) | ((local_dates == now.date()) & market_closed)
    return frame.loc[mask].copy().reset_index(drop=True)


def closed_hourly_bars(frame, now):
    if frame is None or frame.empty:
        return pd.DataFrame()
    local_starts = frame["date"].dt.tz_convert("Asia/Kolkata")
    completed = (local_starts + pd.Timedelta(hours=1)) <= now
    # NSE's final 15:15-15:30 bar is shorter than one hour.
    final_bar = (
        (local_starts.dt.hour == 15)
        & (local_starts.dt.minute == 15)
        & (now.hour > 15 or (now.hour == 15 and now.minute >= 30))
    )
    return frame.loc[completed | final_bar].copy().reset_index(drop=True)


def direction_up(frame, label):
    if frame is None or len(frame) < 2:
        return False, f"{label}: DATA N/A"
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return False, f"{label}: DATA N/A"
    passed = float(closes.iloc[-1]) > float(closes.iloc[-2])
    return passed, f"{label}: {'PASS' if passed else 'FAIL'}"


def add_month_week_bars(daily):
    indexed = daily.set_index("date")
    weekly = indexed.resample("W-FRI").agg({
        "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    monthly = indexed.resample("ME").agg({
        "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    now = now_ist()
    # Resample labels are period ends; remove any current incomplete period.
    weekly_local = weekly["date"].dt.tz_convert("Asia/Kolkata")
    week_closed = now.weekday() > 4 or (
        now.weekday() == 4 and (now.hour > 15 or (now.hour == 15 and now.minute >= 30))
    )
    if not week_closed:
        current_week = (now.isocalendar().year, now.isocalendar().week)
        keys = weekly_local.apply(lambda d: (d.isocalendar().year, d.isocalendar().week))
        weekly = weekly.loc[keys != current_week].reset_index(drop=True)
    monthly_local = monthly["date"].dt.tz_convert("Asia/Kolkata")
    monthly = monthly.loc[
        (monthly_local.dt.year < now.year)
        | ((monthly_local.dt.year == now.year) & (monthly_local.dt.month < now.month))
    ].reset_index(drop=True)
    return monthly, weekly


def evaluate_symbol(item):
    symbol, company = item
    now = now_ist()
    daily_raw = fetch_chart(symbol, "5y", "1d", MIN_DAILY_ROWS)
    if daily_raw is None:
        return {"symbol": symbol, "company": company, "error": "daily history unavailable"}
    daily = closed_daily_bars(daily_raw, now)
    if len(daily) < 25:
        return {"symbol": symbol, "company": company, "error": "not enough completed daily candles"}

    monthly, weekly = add_month_week_bars(daily)
    monthly_ok, monthly_note = direction_up(monthly, "MONTHLY")
    weekly_ok, weekly_note = direction_up(weekly, "WEEKLY")

    daily_close = pd.to_numeric(daily["close"], errors="coerce")
    ema20 = daily_close.ewm(span=20, adjust=False).mean()
    daily_ok = float(daily_close.iloc[-1]) > float(ema20.iloc[-1])

    hourly_raw = fetch_chart(symbol, "730d", "60m", MIN_HOURLY_ROWS)
    hourly = closed_hourly_bars(hourly_raw, now)
    hourly_ok, hourly_note = direction_up(hourly, "1H")

    previous_20_high = float(daily["high"].shift(1).tail(20).max())
    breakout_ok = float(daily["close"].iloc[-1]) > previous_20_high

    volumes = pd.to_numeric(daily["volume"], errors="coerce")
    avg_volume = float(volumes.shift(1).tail(20).mean())
    latest_volume = float(volumes.iloc[-1]) if pd.notna(volumes.iloc[-1]) else None
    rvol = latest_volume / avg_volume if latest_volume is not None and avg_volume > 0 else None
    volume_ok = rvol is not None and rvol >= VOLUME_MULTIPLIER

    checks = {
        "MONTHLY": monthly_ok,
        "WEEKLY": weekly_ok,
        "DAILY": daily_ok,
        "1H": hourly_ok,
        "BREAKOUT_20D": breakout_ok,
        "VOLUME_1_5X": volume_ok,
    }
    score = sum(bool(v) for v in checks.values())
    # Weekly and daily trend are mandatory even though the overall threshold is 5/6.
    eligible = score >= MIN_SCORE and weekly_ok and daily_ok

    latest = daily.iloc[-1]
    close = float(latest["close"])
    high = float(latest["high"])
    low = float(latest["low"])
    tr = pd.concat([
        daily["high"] - daily["low"],
        (daily["high"] - daily["close"].shift()).abs(),
        (daily["low"] - daily["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr14 = float(tr.rolling(14).mean().iloc[-1])
    entry = high * 1.001
    # Conservative structural stop: below both signal-day low and 1.5 ATR support.
    stop = min(low, close - 1.5 * atr14) if pd.notna(atr14) and atr14 > 0 else low
    risk = entry - stop
    t1 = entry + 2 * risk if risk > 0 else None
    t2 = entry + 3 * risk if risk > 0 else None
    risk_pct = (risk / entry * 100) if entry > 0 and risk > 0 else None

    failed = [name for name, passed in checks.items() if not passed]
    return {
        "symbol": symbol,
        "company": company,
        "score": f"{score}/6",
        "score_num": score,
        "MONTHLY": "PASS" if monthly_ok else "FAIL",
        "WEEKLY": "PASS" if weekly_ok else "FAIL",
        "DAILY": "PASS" if daily_ok else "FAIL",
        "1H": "PASS" if hourly_ok else "FAIL",
        "BREAKOUT_20D": "PASS" if breakout_ok else "FAIL",
        "VOLUME_1_5X": "PASS" if volume_ok else "FAIL",
        "relative_volume": round(rvol, 2) if rvol is not None else None,
        "signal_date": str(pd.Timestamp(latest["date"]).tz_convert("Asia/Kolkata").date()),
        "signal_close": round(close, 2),
        "entry_trigger": round(entry, 2),
        "stop_loss": round(stop, 2),
        "target_1_2R": round(t1, 2) if t1 is not None else None,
        "target_2_3R": round(t2, 2) if t2 is not None else None,
        "risk_pct": round(risk_pct, 2) if risk_pct is not None else None,
        "eligible": eligible,
        "failed_checks": ",".join(failed) if failed else "NONE",
        "monthly_note": monthly_note,
        "weekly_note": weekly_note,
        "hourly_note": hourly_note,
    }


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram not sent: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing.")
        return False
    lines = message.splitlines()
    chunks, current = [], ""
    for line in lines:
        candidate = line if not current else current + "\n" + line
        if len(candidate) > 3500:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for i, chunk in enumerate(chunks, 1):
        body = f"[Part {i}/{len(chunks)}]\n{chunk}" if len(chunks) > 1 else chunk
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": body, "disable_web_page_preview": True},
                timeout=TIMEOUT,
            )
            if not response.ok or not response.json().get("ok"):
                print(f"Telegram error: {response.status_code} {response.text[:300]}")
                return False
        except Exception as exc:
            print(f"Telegram delivery failed: {exc}")
            return False
        time.sleep(1)
    return True


def main():
    started = now_ist()
    print(f"NSE POSITIONAL SCANNER | {started:%d-%m-%Y %H:%M:%S IST}")
    print("LONG only | Holding 5-20 trading days | Minimum 5/6 | Weekly and Daily mandatory")
    universe = get_nse_universe()
    print(f"NSE EQ symbols: {len(universe)}")
    results = []
    errors = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(evaluate_symbol, item): item[0] for item in universe}
        for count, future in enumerate(as_completed(futures), 1):
            try:
                row = future.result()
                results.append(row)
                if row.get("error"):
                    errors += 1
            except Exception as exc:
                errors += 1
                results.append({"symbol": futures[future], "error": str(exc)})
            if count % 100 == 0:
                print(f"Progress: {count}/{len(universe)} | errors={errors}")

    valid = [x for x in results if "score_num" in x]
    eligible = [x for x in valid if x.get("eligible")]
    # Rank by score first, then relative volume, then lower planned risk.
    eligible.sort(
        key=lambda x: (
            x.get("score_num", 0),
            x.get("relative_volume") or 0,
            -(x.get("risk_pct") or 999),
        ),
        reverse=True,
    )
    for rank, row in enumerate(eligible, 1):
        row["rank"] = rank
    # Presentation buckets only: eligibility and ranking logic are unchanged.
    normal_risk = [x for x in eligible if x.get("risk_pct") is not None and x["risk_pct"] <= 10.0]
    high_risk = [x for x in eligible if x.get("risk_pct") is not None and x["risk_pct"] > 10.0]
    risk_unavailable = [x for x in eligible if x.get("risk_pct") is None]
    top5 = normal_risk[:5]
    remaining_normal = normal_risk[5:]

    columns = [
        "rank", "symbol", "company", "score", "MONTHLY", "WEEKLY", "DAILY", "1H",
        "BREAKOUT_20D", "VOLUME_1_5X", "relative_volume", "signal_date",
        "signal_close", "entry_trigger", "stop_loss", "target_1_2R", "target_2_3R",
        "risk_pct", "failed_checks", "eligible",
    ]
    pd.DataFrame(results).reindex(columns=columns).to_csv("nse_positional_signals.csv", index=False)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "📈 आज के TOP 5 POSITIONAL STOCKS",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📅 {started:%d %b %Y} | Market Closed (EOD)",
        f"🔎 Scanned: {len(universe)} NSE stocks | Eligible: {len(eligible)}",
        f"✅ Normal Risk: {len(normal_risk)} | 🚨 High Risk: {len(high_risk)}",
        "",
        "🏆 TOP 5 WATCHLIST",
        "Entry trigger par fresh confirmation ke baad hi consider karein.",
        "",
    ]
    if top5:
        for i, x in enumerate(top5, 1):
            lines.extend([
                f"{i}. {x['symbol']}  |  {x['score']}  |  Volume {x.get('relative_volume', 'N/A')}x",
                f"   Entry ₹{x['entry_trigger']}  |  SL ₹{x['stop_loss']}",
                f"   T1 ₹{x['target_1_2R']}  |  T2 ₹{x['target_2_3R']}  |  Risk {x.get('risk_pct', 'N/A')}%",
                "",
            ])
    else:
        lines.append("Aaj koi normal-risk eligible stock nahi mila. No forced picks.")
        lines.append("")

    lines.extend(["📋 OTHER STOCKS | Shortlist"])
    if remaining_normal:
        lines.append("  ".join(
            f"{x['symbol']} ({x['score']})" for x in remaining_normal
        ))
    else:
        lines.append("Top 5 ke alawa koi normal-risk stock nahi.")

    lines.extend(["", "🚨 HIGH RISK ALERT | Risk >10%"])
    if high_risk:
        for x in high_risk:
            lines.append(f"• {x['symbol']} | {x['score']} | Risk {x['risk_pct']}%")
    else:
        lines.append("Aaj koi high-risk eligible stock nahi.")

    if risk_unavailable:
        lines.extend(["", "⚠️ Risk calculate nahi ho paya: " + ", ".join(x["symbol"] for x in risk_unavailable)])

    lines.extend([
        "",
        f"⚠️ Data note: {errors} stocks ka data unavailable/incomplete tha; verify live price, volume and chart before entry.",
        "🎯 Targets 2R/3R model par based hain; guaranteed returns nahi. Position size apne risk ke hisaab se rakhein.",
        "📎 Full details: nse_positional_signals.csv",
    ])
    message = "\n".join(lines)
    print(message)
    print(f"Telegram delivered: {send_telegram(message)}")
    print(f"Finished: {now_ist():%d-%m-%Y %H:%M:%S IST}")


if __name__ == "__main__":
    main()
