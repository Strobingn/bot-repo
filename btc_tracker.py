"""CLI monitor for BTC price and Kalshi BTC markets."""

from __future__ import annotations

import time
from datetime import datetime

from kalshi_common import (
    Settings,
    configure_logging,
    get_btc_price,
    get_kalshi_btc_markets,
    get_yes_ask,
    logger,
    market_volume,
)

settings = Settings.from_env()


def print_dashboard() -> None:
    while True:
        print("\n" + "=" * 60)
        print(f"BITCOIN TRACKER - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        try:
            price, change = get_btc_price()
            print(f"Price: ${price:,.2f}")
            print(f"24h Change: {change:+.2f}%")
        except Exception as exc:
            print(f"Price fetch error: {exc}")

        markets = get_kalshi_btc_markets(settings.strategy_mode, limit=20)
        print(f"\nKalshi BTC Markets ({settings.strategy_mode}, {len(markets)} open):")
        for market in markets[:8]:
            yes_ask = get_yes_ask(market)
            print(
                f" - {market.get('title', 'N/A')} | "
                f"Yes ask: ${yes_ask:.4f} | "
                f"Vol: {market_volume(market):.2f}"
            )

        print("\nPress Ctrl+C to stop.")
        time.sleep(30)


if __name__ == "__main__":
    configure_logging()
    logger.info("Starting BTC tracker")
    print_dashboard()