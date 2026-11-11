import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

NSE_CSV_URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
]
NSE_HOME = "https://www.nseindia.com/"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}.NS"
TIMEOUT = 25
MAX_WORKERS = 10
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
                raise ValueError("NSE CSV missing SYMBOL/SERIES")
            frame["SYMBOL"] = frame["SYMBOL"].astype(str).str.strip()
            frame["SERIES"] = frame["SERIES"].astype(str).str.strip().str.upper()
            frame = frame[(frame["SERIES"] == "EQ") & frame["SYMBOL"].str.fullmatch(r"[A-Z0-9&._-]+")]
            frame = frame.drop_duplicates("SYMBOL")
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


def fetch_chart(symbol, period, interval, min_rows=50):
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
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume"),
            }).dropna()
            frame = frame.sort_values("date").reset_index(drop=True)
            return frame if len(frame) >= min_rows else None
        except Exception:
            if attempt < 2:
                time.sleep(1 + attempt)
    return None


def classify_close_direction(frame):
    """Compare only the last two fully closed candles by CLOSE; no EMA is used."""
    if frame is None or len(frame) < 2:
        return "DATA NOT AVAILABLE"
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return "DATA NOT AVAILABLE"
    previous_close = float(closes.iloc[-2])
    latest_close = float(closes.iloc[-1])
    if latest_close > previous_close:
        return "UPTREND"
    if latest_close < previous_close:
        return "DOWNTREND"
    return "SIDEWAYS"


def keep_only_closed_daily_bars(frame, now):
    """Daily Yahoo bars are dated by session; today's bar is usable only after NSE close."""
    if frame is None or frame.empty:
        return frame
    local_dates = frame["date"].dt.tz_convert("Asia/Kolkata").dt.date
    today = now.date()
    include_today = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
    mask = (local_dates < today) | ((local_dates == today) & include_today)
    return frame.loc[mask].copy().reset_index(drop=True)


def make_period_bars(daily_frame, rule, now, timeframe):
    if daily_frame is None or daily_frame.empty:
        return None
    indexed = daily_frame.set_index("date")
    bars = indexed.resample(rule).agg({
        "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    if bars.empty:
        return bars

    local_period_dates = bars["date"].dt.tz_convert("Asia/Kolkata")
    if timeframe == "MONTHLY":
        # The current calendar month is never treated as a completed monthly candle.
        bars = bars.loc[
            (local_period_dates.dt.year < now.year)
            | ((local_period_dates.dt.year == now.year) & (local_period_dates.dt.month < now.month))
        ]
    elif timeframe == "WEEKLY":
        # Include this week's candle only after Friday's NSE session has closed.
        week_is_closed = now.weekday() > 4 or (now.weekday() == 4 and (now.hour > 15 or (now.hour == 15 and now.minute >= 30)))
        current_week = now.isocalendar()[:2]
        week_keys = local_period_dates.apply(lambda d: (d.isocalendar().year, d.isocalendar().week))
        if not week_is_closed:
            bars = bars.loc[week_keys != current_week]
    return bars.reset_index(drop=True)


def keep_only_closed_hourly_bars(frame, now):
    """Keep only completed 60-minute bars, including NSE's final 15:15-15:30 bar."""
    if frame is None or frame.empty:
        return frame
    local_starts = frame["date"].dt.tz_convert("Asia/Kolkata")
    completed = (local_starts + pd.Timedelta(hours=1)) <= now
    final_nse_bar = (
        (local_starts.dt.hour == 15) & (local_starts.dt.minute == 15)
        & (now.hour > 15 or (now.hour == 15 and now.minute >= 30))
    )
    return frame.loc[completed | final_nse_bar].copy().reset_index(drop=True)


def scan_symbol(item):
    symbol, company = item
    now = now_ist()
    daily_raw = fetch_chart(symbol, "5y", "1d", min_rows=20)
    if daily_raw is None:
        return {
            "symbol": symbol, "company": company,
            "MONTHLY": "DATA NOT AVAILABLE", "WEEKLY": "DATA NOT AVAILABLE",
            "DAILY": "DATA NOT AVAILABLE", "1 HOUR": "DATA NOT AVAILABLE",
        }

    daily_closed = keep_only_closed_daily_bars(daily_raw, now)
    weekly_closed = make_period_bars(daily_closed, "W-FRI", now, "WEEKLY")
    monthly_closed = make_period_bars(daily_closed, "ME", now, "MONTHLY")

    hourly_raw = fetch_chart(symbol, "730d", "60m", min_rows=2)
    hourly_closed = keep_only_closed_hourly_bars(hourly_raw, now)

    previous_day_close = float(pd.to_numeric(daily_closed["close"], errors="coerce").dropna().iloc[-1]) if daily_closed is not None and not daily_closed.empty else None
    return {
        "symbol": symbol,
        "company": company,
        "MONTHLY": classify_close_direction(monthly_closed),
        "WEEKLY": classify_close_direction(weekly_closed),
        "DAILY": classify_close_direction(daily_closed),
        "1 HOUR": classify_close_direction(hourly_closed),
        "PREVIOUS_DAY_CLOSE": previous_day_close,
    }


def get_completed_today_15m(intraday, now):
    """Return today's completed 15m candles only, through the latest expected closed slot."""
    if intraday is None or intraday.empty:
        return None
    local = intraday.copy()
    local["local_time"] = local["date"].dt.tz_convert("Asia/Kolkata")
    local = local[local["local_time"].dt.date == now.date()].copy()
    if local.empty:
        return None
    local["clock"] = local["local_time"].dt.strftime("%H:%M")
    local = local[local["local_time"].dt.hour >= 9].copy()
    # At 12:07, the latest fully completed 15m candle should start at 11:45.
    latest_expected_start = now.replace(
        minute=(now.minute // 15) * 15, second=0, microsecond=0
    ) - pd.Timedelta(minutes=15)
    local = local[local["local_time"] <= latest_expected_start].copy()
    local = local.sort_values("local_time").drop_duplicates("clock", keep="last")
    if local.empty:
        return None
    latest_start = local["local_time"].iloc[-1]
    if latest_start < latest_expected_start:
        return None
    return local.reset_index(drop=True)


def confirm_opening_45m(intraday, now, previous_close):
    """Fixed 10:00 confirmation: 09:15, 09:30 and 09:45 completed closes vs prior close."""
    if now.hour < 10:
        return "NOT READY"
    if previous_close is None or pd.isna(previous_close):
        return "DATA NOT AVAILABLE"
    completed = get_completed_today_15m(intraday, now)
    if completed is None:
        return "DATA NOT AVAILABLE"
    opening = completed[completed["clock"].isin(["09:15", "09:30", "09:45"])]
    by_clock = opening.drop_duplicates("clock").set_index("clock")
    expected = ["09:15", "09:30", "09:45"]
    if not all(clock in by_clock.index for clock in expected):
        return "DATA NOT AVAILABLE"
    closes = [float(by_clock.loc[clock, "close"]) for clock in expected]
    if all(value > float(previous_close) for value in closes):
        return "UPTREND"
    if all(value < float(previous_close) for value in closes):
        return "DOWNTREND"
    return "FAIL"


def confirm_runtime_trend(intraday, now, previous_close):
    """Run-time confirmation: every completed 15m close today must remain on the same side of prior close."""
    if previous_close is None or pd.isna(previous_close):
        return "DATA NOT AVAILABLE", None
    completed = get_completed_today_15m(intraday, now)
    if completed is None:
        return "DATA NOT AVAILABLE", None
    if len(completed) < 3:
        return "NOT READY", None
    closes = pd.to_numeric(completed["close"], errors="coerce").dropna()
    if len(closes) != len(completed):
        return "DATA NOT AVAILABLE", None
    if (closes > float(previous_close)).all():
        return "UPTREND", completed["local_time"].iloc[-1].strftime("%H:%M")
    if (closes < float(previous_close)).all():
        return "DOWNTREND", completed["local_time"].iloc[-1].strftime("%H:%M")
    return "FAIL", completed["local_time"].iloc[-1].strftime("%H:%M")


def time_matched_volume_metrics(intraday, now, previous_close):
    """Compare today's cumulative completed-15m volume with the same clock slots over prior 20 sessions."""
    completed = get_completed_today_15m(intraday, now)
    if completed is None or previous_close is None or float(previous_close) <= 0:
        return None
    clocks = completed["clock"].tolist()
    if not clocks:
        return None
    today_volume = pd.to_numeric(completed["volume"], errors="coerce")
    if today_volume.isna().any():
        return None
    today_volume = float(today_volume.sum())

    history = intraday.copy()
    history["local_time"] = history["date"].dt.tz_convert("Asia/Kolkata")
    history["session_date"] = history["local_time"].dt.date
    history["clock"] = history["local_time"].dt.strftime("%H:%M")
    history = history[history["session_date"] < now.date()]
    history = history[history["clock"].isin(clocks)].copy()
    historical = []
    for session_date, group in history.groupby("session_date"):
        by_clock = group.drop_duplicates("clock").set_index("clock")
        if not all(clock in by_clock.index for clock in clocks):
            continue
        values = pd.to_numeric(by_clock.loc[clocks, "volume"], errors="coerce")
        if values.isna().any():
            continue
        historical.append((session_date, float(values.sum())))
    historical.sort(key=lambda item: item[0], reverse=True)
    historical = historical[:20]
    if len(historical) < 20:
        return None

    average_volume = sum(value for _, value in historical) / len(historical)
    if average_volume <= 0:
        return None
    latest_close = float(completed.iloc[-1]["close"])
    change_pct = (latest_close / float(previous_close) - 1) * 100
    relative_volume = today_volume / average_volume
    volume_label = (
        "STRONG" if relative_volume >= 1.5 else
        "MODERATE" if relative_volume >= 1.2 else
        "NORMAL"
    )
    return {
        "SESSION_VOLUME_TO_TIME": int(today_volume),
        "AVG_20D_SAME_TIME_VOLUME": round(average_volume, 1),
        "RELATIVE_VOLUME_TO_TIME": round(relative_volume, 2),
        "VOLUME_STRENGTH": volume_label,
        "CHANGE_FROM_PREV_CLOSE_PCT": round(change_pct, 2),
        "TREND_STRENGTH_PCT": round(abs(change_pct), 2),
        "DATA_AS_OF": completed["local_time"].iloc[-1].strftime("%H:%M"),
    }



def split_telegram_message(message, max_length=3500):
    chunks, current = [], ""
    for line in message.splitlines():
        while len(line) > max_length:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:max_length])
            line = line[max_length:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > max_length:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram not sent: bot token/chat ID secret missing.")
        return False
    chunks = split_telegram_message(message)
    for index, chunk in enumerate(chunks, 1):
        text_to_send = f"[Part {index}/{len(chunks)}]\n{chunk}" if len(chunks) > 1 else chunk
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text_to_send, "disable_web_page_preview": True},
                timeout=TIMEOUT,
            )
            if not response.ok or not response.json().get("ok"):
                print(f"Telegram error part {index}/{len(chunks)}: HTTP {response.status_code} {response.text[:400]}")
                return False
            print(f"Telegram part delivered: {index}/{len(chunks)}")
        except Exception as exc:
            print(f"Telegram delivery failed: {exc}")
            return False
        if index < len(chunks):
            time.sleep(1)
    return True


def main():
    started = now_ist()
    print(f"NSE MULTI-TIMEFRAME TREND SCANNER | {started:%Y-%m-%d %H:%M:%S %Z}")
    print("Trend rule: compare CLOSE of the last two fully closed candles only; higher = UPTREND, lower = DOWNTREND, equal = SIDEWAYS. No EMA.")
    print("Timeframes: Monthly, Weekly, Daily, 1 Hour. This scanner is separate from the Daily 6/6 swing scanner.")
    universe = get_nse_universe()
    print(f"NSE EQ symbols downloaded: {len(universe)}")
    results, errors = [], 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(scan_symbol, item): item[0] for item in universe}
        for count, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                errors += 1
                print(f"ERROR {symbol}: {exc}")
            if count % 100 == 0:
                print(f"Progress: {count}/{len(universe)} | scanned={len(results)} | errors={errors}")
    results.sort(key=lambda x: x["symbol"])
    # One consolidated row per stock: show all four timeframe directions together.
    for row in results:
        states = [row.get(tf, "DATA NOT AVAILABLE") for tf in ["MONTHLY", "WEEKLY", "DAILY", "1 HOUR"]]
        if all(state == "UPTREND" for state in states):
            row["ALIGNMENT"] = "4/4 UPTREND"
        elif all(state == "DOWNTREND" for state in states):
            row["ALIGNMENT"] = "4/4 DOWNTREND"
        elif any(state == "DATA NOT AVAILABLE" for state in states):
            row["ALIGNMENT"] = "INCOMPLETE DATA"
        else:
            row["ALIGNMENT"] = "MIXED / SIDEWAYS"

    # 6/6 rule: the fixed 10:00 opening trend AND the trend through this run-time must agree.
    base_aligned = [x for x in results if x.get("ALIGNMENT") in ("4/4 UPTREND", "4/4 DOWNTREND")]
    live_checked = []
    rejected_10am = 0
    rejected_runtime = 0
    if now_ist().hour < 10:
        print("10:00 confirmation is not ready; no trend candidates will be published.")
    else:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            checks = {
                pool.submit(fetch_chart, row["symbol"], "60d", "15m", 3): row
                for row in base_aligned
            }
            for future in as_completed(checks):
                row = checks[future]
                try:
                    intraday = future.result()
                except Exception as exc:
                    print(f"15m data error {row['symbol']}: {exc}")
                    intraday = None
                previous_close = row.get("PREVIOUS_DAY_CLOSE")
                opening_confirmation = confirm_opening_45m(intraday, now_ist(), previous_close)
                expected_direction = "UPTREND" if row["ALIGNMENT"] == "4/4 UPTREND" else "DOWNTREND"
                if opening_confirmation != expected_direction:
                    rejected_10am += 1
                    continue
                runtime_confirmation, data_as_of = confirm_runtime_trend(intraday, now_ist(), previous_close)
                if runtime_confirmation != expected_direction:
                    rejected_runtime += 1
                    continue

                row["15M 10AM"] = opening_confirmation
                row["15M RUN-TIME"] = runtime_confirmation
                row["DATA_AS_OF"] = data_as_of
                row["ALIGNMENT"] = "6/6 UPTREND" if expected_direction == "UPTREND" else "6/6 DOWNTREND"
                volume_data = time_matched_volume_metrics(intraday, now_ist(), previous_close)
                if volume_data is None:
                    row["VOLUME_DATA_STATUS"] = "NOT AVAILABLE - 20 complete same-time sessions required"
                    row["RELATIVE_VOLUME_TO_TIME"] = None
                    row["VOLUME_STRENGTH"] = "DATA NOT AVAILABLE"
                    row["CHANGE_FROM_PREV_CLOSE_PCT"] = None
                    row["TREND_STRENGTH_PCT"] = None
                else:
                    row.update(volume_data)
                    row["VOLUME_DATA_STATUS"] = "OK"
                    row["DATA_AS_OF"] = volume_data["DATA_AS_OF"]
                rvol = row.get("RELATIVE_VOLUME_TO_TIME")
                row["STATUS"] = "GREEN - STRONG TREND" if rvol is not None and rvol >= 1.5 else "YELLOW - WATCH"
                live_checked.append(row)

    all_up = [x["symbol"] for x in live_checked if x.get("ALIGNMENT") == "6/6 UPTREND"]
    all_down = [x["symbol"] for x in live_checked if x.get("ALIGNMENT") == "6/6 DOWNTREND"]
    volume_ranked = sorted(
        [x for x in live_checked if x.get("RELATIVE_VOLUME_TO_TIME") is not None],
        key=lambda x: x["RELATIVE_VOLUME_TO_TIME"], reverse=True
    )
    trend_ranked = sorted(
        [x for x in live_checked if x.get("TREND_STRENGTH_PCT") is not None],
        key=lambda x: x["TREND_STRENGTH_PCT"], reverse=True
    )
    # Transparent ranking: 60% capped relative volume + 40% capped absolute move.
    for item in live_checked:
        rvol = item.get("RELATIVE_VOLUME_TO_TIME")
        move = item.get("TREND_STRENGTH_PCT")
        item["COMBINED_SCORE"] = (
            round(60 * min(float(rvol), 5.0) / 5.0 + 40 * min(float(move), 5.0) / 5.0, 1)
            if rvol is not None and move is not None else None
        )
    combined_ranked = sorted(
        [x for x in live_checked if x.get("COMBINED_SCORE") is not None],
        key=lambda x: x["COMBINED_SCORE"], reverse=True
    )
    live_checked.sort(key=lambda x: x["symbol"])
    pd.DataFrame(
        live_checked,
        columns=[
            "symbol", "company", "MONTHLY", "WEEKLY", "DAILY", "1 HOUR",
            "15M 10AM", "15M RUN-TIME", "ALIGNMENT", "STATUS", "DATA_AS_OF", "PREVIOUS_DAY_CLOSE",
            "SESSION_VOLUME_TO_TIME", "AVG_20D_SAME_TIME_VOLUME",
            "RELATIVE_VOLUME_TO_TIME", "VOLUME_STRENGTH",
            "CHANGE_FROM_PREV_CLOSE_PCT", "TREND_STRENGTH_PCT", "COMBINED_SCORE",
            "VOLUME_DATA_STATUS",
        ],
    ).to_csv("nse_timeframe_trends.csv", index=False)

    report_as_of = now_ist()
    lines = [
        "NSE MULTI-TIMEFRAME LIVE TREND REPORT",
        f"Run time: {report_as_of:%d-%m-%Y %H:%M IST}",
        f"Data as of latest completed 15m candle: {max([x.get('DATA_AS_OF', 'N/A') for x in live_checked], default='N/A')} IST",
        f"Universe: {len(universe)} NSE EQ | scanned: {len(results)} | errors: {errors}",
        "STRICT RULE: 4 timeframe directions + fixed 10AM trend + run-time trend must all agree (6/6).",
        "10AM check: 09:15, 09:30, 09:45 candle CLOSES all on the same side of previous session close.",
        "RUN-TIME check: every completed 15m candle from market open through the latest completed candle must stay on that same side of previous close.",
        f"GREEN - STRONG TREND: {sum(1 for x in live_checked if x.get('STATUS', '').startswith('GREEN'))}",
        f"YELLOW - WATCH: {sum(1 for x in live_checked if x.get('STATUS', '').startswith('YELLOW'))}",
        f"REJECTED at 10AM confirmation: {rejected_10am} | Rejected at run-time confirmation: {rejected_runtime}",
        "",
        f"6/6 UPTREND: {len(all_up)}",
        "Stocks: " + (", ".join(all_up) if all_up else "None"),
        "",
        f"6/6 DOWNTREND: {len(all_down)}",
        "Stocks: " + (", ".join(all_down) if all_down else "None"),
        "",
        "TOP VOLUME (cumulative volume vs prior 20 sessions, same completed 15m slots):",
        *([
            f"{x['symbol']} | RVOL {x['RELATIVE_VOLUME_TO_TIME']:.2f}x | {x['VOLUME_STRENGTH']} | {x['STATUS']} | {x['ALIGNMENT']} | Data {x.get('DATA_AS_OF', 'N/A')}"
            for x in volume_ranked[:10]
        ] or ["No eligible same-time volume data"]),
        "",
        "TOP TREND (latest completed 15m close vs previous session close):",
        *([
            f"{x['symbol']} | Move {x['CHANGE_FROM_PREV_CLOSE_PCT']:+.2f}% | {x['ALIGNMENT']} | {x['STATUS']} | Data {x.get('DATA_AS_OF', 'N/A')}"
            for x in trend_ranked[:10]
        ] or ["No eligible trend data"]),
        "",
        "BEST VOLUME + TREND TOP 5 (ranking score /100; NOT a buy signal):",
        *([
            f"{x['symbol']} | Score {x['COMBINED_SCORE']:.1f}/100 | RVOL {x['RELATIVE_VOLUME_TO_TIME']:.2f}x | Move {x['CHANGE_FROM_PREV_CLOSE_PCT']:+.2f}% | {x['STATUS']}"
            for x in combined_ranked[:5]
        ] or ["No combined ranking available"]),
        "",
        "GREEN = 6/6 alignment + same-time relative volume >=1.5x. YELLOW = 6/6 alignment but volume below 1.5x or unavailable.",
        "RED / REJECT = not shown in candidate list because one or more required trend confirmations failed or data was unavailable.",
        "Volume strength: STRONG >=1.5x; MODERATE 1.2x-1.49x; NORMAL <1.2x.",
        "Combined score is a heuristic ranking only, not an entry signal. Entry still requires your 5-minute candle CLOSE above today's high and a planned stop-loss.",
        "If Yahoo intraday data is delayed/incomplete, the scanner can reject the symbol or show unavailable data; verify the candle timestamp before trading.",
        "CSV artifact contains only 6/6 candidates and their run-time volume/trend fields.",
    ]
    message = "\n".join(lines)
    print(message)
    delivered = send_telegram(message)
    print(f"Telegram delivered: {delivered}")
    print(f"Finished: {now_ist():%Y-%m-%d %H:%M:%S %Z}; errors={errors}; rows={len(results)}")


if __name__ == "__main__":
    main()
