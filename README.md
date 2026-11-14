# NSE EOD Swing Scanner

Broker-free, automatic daily NSE cash-equity end-of-day scanner. It does **not** place orders.

## What it does
- Downloads the NSE equity list and scans the EQ series.
- Retrieves daily historical candles from Yahoo Finance (free public chart endpoint).
- Applies six independent technical conditions:
  1. Latest close > EMA20
  2. EMA20 > EMA50
  3. RSI(14) between 55 and 70
  4. Latest volume > 1.5 × 20-day average volume
  5. Latest close > the previous 20-session high (today excluded)
  6. ADX(14) > 20
- Creates `nse_swing_signals.csv`.
- Sends a Telegram summary when secrets are configured.
- Runs Monday-Friday at 16:00 India time via GitHub Actions, plus manual Run workflow.


## NSE low-float / high-demand shortlist

The EOD scanner now enriches strict 6/6 technical matches with the latest NSE quarterly shareholding-pattern XBRL filing:
- NSE promoter holding and public holding percentages are extracted from the latest available filing.
- NSE public holding is used as a **low-float proxy only**; it is not exact investible free float because public holdings can include strategic, locked-in, or otherwise non-freely-traded shares.
- Candidate band: 10%-40% NSE public-holding proxy.
- Demand confirmation: relative volume at least 2.0x the 20-session average. The existing 6/6 technical filter already requires a 20-session breakout and volume above 1.5x.
- The Telegram report displays up to 20 "LOW FLOAT PROXY + HIGH DEMAND" candidates separately. If NSE filing data is missing, the stock is marked unavailable; missing data is never treated as a pass.
- Shareholding is quarterly, not live. The filing period is shown in the report.

NSE shareholding filing page: https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern

## GitHub Secrets
In **Settings → Secrets and variables → Actions → New repository secret**, add:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Never put bot credentials directly in code.

## Run manually
Open **Actions → NSE EOD Swing Scanner → Run workflow**.

## Data and limitations
- No broker login, broker API, live quotes, or order placement is used.
- NSE EQ list is the universe source; Yahoo Finance supplies historical daily candles. Yahoo may occasionally omit, delay, throttle, or fail to map symbols. The run logs failures and the CSV contains only stocks with complete usable data.
- GitHub scheduled jobs can start late; 16:00 IST is the scheduled target, not a guaranteed exact delivery time.
- Entry is the latest daily close. Stop-loss 5% and target 10% are illustrative defaults, not validated trading recommendations. Verify current prices, liquidity, corporate actions, and risk before placing any trade.
- A 6/6 match is a technical screen, not a guarantee of returns. Backtest and paper-trade before using real capital.
