# Kalshi BTC Bot

Production-oriented monitor and trading bot for Kalshi Bitcoin prediction markets.

## Features

- Fetches open BTC markets from Kalshi (`KXBTC15M`, `KXBTC`, `KXBTCD`)
- Builds a probability model from RSI + moving averages
- Optional whale/on-chain adjustments (Glassnode, CryptoQuant)
- Orderbook skew from Kalshi `orderbook_fp`
- Simulation mode by default
- CSV logging and proxy backtests
- CLI tracker and Streamlit dashboard

## Setup

```bash
cd "kalshi_btc_bot_full (1)"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with your credentials. Keep `SIMULATION_MODE=true` until you have tested live auth.

## Run

```bash
# Main bot
python kalshi_btc_bot.py

# Terminal monitor
python btc_tracker.py

# Web dashboard
streamlit run btc_dashboard.py
```

## Live Trading Checklist

1. Create Kalshi API key + RSA private key
2. Set `KALSHI_API_KEY` and `KALSHI_PRIVATE_KEY_PATH` (or `KALSHI_PRIVATE_KEY_PEM`)
3. Test in simulation mode first and review `kalshi_btc_log.csv`
4. Set `SIMULATION_MODE=false` only when ready
5. Start with low `MAX_CONTRACTS`

## Strategy Modes

| `STRATEGY_MODE` | Series used |
|---|---|
| `15min` | `KXBTC15M` |
| `hourly` | `KXBTC` |
| `daily` | `KXBTCD` |
| `all` | all three |

## Docker

```bash
docker build -t kalshi-btc-bot .
docker run --env-file .env kalshi-btc-bot
```

## Security

- Never commit `.env`, `.pem`, or `.key` files
- Rotate any API key that was ever stored in a template or chat log