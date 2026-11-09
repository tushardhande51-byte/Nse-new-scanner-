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
