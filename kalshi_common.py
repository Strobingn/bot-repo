"""Shared Kalshi BTC bot utilities."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import ccxt
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

KALSHI_API_BASE = os.getenv(
    "KALSHI_API_BASE", "https://external-api.kalshi.com/trade-api/v2"
)
BTC_SERIES_15M = "KXBTC15M"
BTC_SERIES_HOURLY = "KXBTC"
BTC_SERIES_DAILY = "KXBTCD"

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))


@dataclass(frozen=True)
class Settings:
    kalshi_api_key_id: str
    kalshi_private_key_pem: str
    kalshi_api_base: str
    glassnode_api_key: str
    cryptoquant_api_key: str
    telegram_token: str
    telegram_chat_id: str
    discord_webhook: str
    simulation_mode: bool
    edge_threshold: float
    strategy_mode: str
    loop_interval_seconds: int
    max_contracts: int
    log_file: str
    backtest_file: str

    @classmethod
    def from_env(cls) -> "Settings":
        strategy = os.getenv("STRATEGY_MODE", "15min").lower()
        return cls(
            kalshi_api_key_id=os.getenv("KALSHI_API_KEY", "").strip(),
            kalshi_private_key_pem=_load_private_key_pem(),
            kalshi_api_base=KALSHI_API_BASE.rstrip("/"),
            glassnode_api_key=os.getenv("GLASSNODE_API_KEY", "").strip(),
            cryptoquant_api_key=os.getenv("CRYPTOQUANT_API_KEY", "").strip(),
            telegram_token=os.getenv("TELEGRAM_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            discord_webhook=os.getenv("DISCORD_WEBHOOK", "").strip(),
            simulation_mode=os.getenv("SIMULATION_MODE", "true").lower() == "true",
            edge_threshold=float(os.getenv("EDGE_THRESHOLD", "0.15")),
            strategy_mode=strategy,
            loop_interval_seconds=int(os.getenv("LOOP_INTERVAL_SECONDS", "20")),
            max_contracts=int(os.getenv("MAX_CONTRACTS", "5")),
            log_file=os.getenv("LOG_FILE", "kalshi_btc_log.csv"),
            backtest_file=os.getenv("BACKTEST_FILE", "backtest_results.csv"),
        )


def _load_private_key_pem() -> str:
    inline = os.getenv("KALSHI_PRIVATE_KEY_PEM", "").strip()
    if inline:
        return inline.replace("\\n", "\n")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if key_path and os.path.isfile(key_path):
        with open(key_path, encoding="utf-8") as handle:
            return handle.read()
    return ""


def configure_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=getattr(logging, (level or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_dollar(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(Decimal(str(value)))
    except Exception:
        return default


def format_dollar_price(value: float) -> str:
    return f"{value:.4f}"


def market_volume(market: dict[str, Any]) -> float:
    for key in ("volume_fp", "volume_24h", "volume"):
        if market.get(key) is not None:
            return parse_dollar(market.get(key))
    return 0.0


def get_yes_ask(market: dict[str, Any]) -> float:
    if market.get("yes_ask_dollars") is not None:
        return parse_dollar(market["yes_ask_dollars"])
    if market.get("yes_ask") is not None:
        return parse_dollar(market["yes_ask"]) / 100.0
    if market.get("yes_price") is not None:
        return parse_dollar(market["yes_price"]) / 100.0
    return parse_dollar(market.get("yes_bid_dollars"))


def get_no_ask(market: dict[str, Any]) -> float:
    if market.get("no_ask_dollars") is not None:
        return parse_dollar(market["no_ask_dollars"])
    yes_ask = get_yes_ask(market)
    if yes_ask > 0:
        return max(0.0, 1.0 - yes_ask)
    return 0.5


def series_for_strategy(strategy_mode: str) -> list[str]:
    if strategy_mode == "15min":
        return [BTC_SERIES_15M]
    if strategy_mode == "hourly":
        return [BTC_SERIES_HOURLY]
    if strategy_mode == "daily":
        return [BTC_SERIES_DAILY]
    return [BTC_SERIES_15M, BTC_SERIES_HOURLY, BTC_SERIES_DAILY]


def get_kalshi_btc_markets(
    strategy_mode: str = "15min",
    status: str = "open",
    limit: int = 100,
) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for series in series_for_strategy(strategy_mode):
        try:
            response = requests.get(
                f"{KALSHI_API_BASE}/markets",
                params={
                    "series_ticker": series,
                    "status": status,
                    "limit": limit,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            for market in response.json().get("markets", []):
                ticker = market.get("ticker")
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    markets.append(market)
        except Exception as exc:
            logger.warning("Failed to fetch markets for %s: %s", series, exc)
    markets.sort(key=market_volume, reverse=True)
    return markets


def is_short_term_market(market: dict[str, Any], strategy_mode: str) -> bool:
    if strategy_mode == "daily":
        return "KXBTCD" in market.get("ticker", "")
    if strategy_mode == "hourly":
        return market.get("ticker", "").startswith("KXBTC-")
    title = market.get("title", "").lower()
    if "15" in title or "minute" in title or "min" in title:
        return True
    close_time = market.get("close_time")
    if not close_time:
        return market.get("ticker", "").startswith("KXBTC15M")
    try:
        close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        seconds = (close_dt - datetime.now(timezone.utc)).total_seconds()
        return 0 < seconds <= 3600
    except Exception:
        return market.get("ticker", "").startswith("KXBTC15M")


EXCHANGE_FALLBACKS = ("coinbase", "kraken", "binanceus", "binance")


def create_exchange(preferred: str | None = None) -> ccxt.Exchange:
    names = [preferred] if preferred else []
    names.extend(name for name in EXCHANGE_FALLBACKS if name not in names)
    last_error: Exception | None = None
    for name in names:
        if not name or not hasattr(ccxt, name):
            continue
        client = getattr(ccxt, name)({"enableRateLimit": True})
        try:
            client.load_markets()
            if client.markets and "BTC/USD" in client.markets:
                return client
            if client.markets and "BTC/USDT" in client.markets:
                return client
        except Exception as exc:
            last_error = exc
            logger.debug("Exchange %s unavailable: %s", name, exc)
    if last_error:
        raise RuntimeError("No usable BTC exchange fallback found") from last_error
    raise RuntimeError("No usable BTC exchange fallback found")


def btc_symbol(exchange: ccxt.Exchange) -> str:
    if exchange.markets and "BTC/USD" in exchange.markets:
        return "BTC/USD"
    return "BTC/USDT"


def get_btc_price(exchange: ccxt.Exchange | None = None) -> tuple[float, float]:
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        bitcoin = response.json()["bitcoin"]
        return float(bitcoin["usd"]), float(bitcoin.get("usd_24h_change", 0))
    except Exception as exc:
        logger.warning("CoinGecko price fetch failed: %s", exc)
        try:
            client = exchange or create_exchange()
            ticker = client.fetch_ticker(btc_symbol(client))
            return float(ticker["last"]), float(ticker.get("percentage") or 0)
        except Exception as fallback_exc:
            logger.error("BTC price fallback failed: %s", fallback_exc)
            raise RuntimeError("Unable to fetch BTC price") from fallback_exc


def fetch_historical_prices(exchange: ccxt.Exchange, limit: int = 300) -> pd.DataFrame:
    try:
        ohlcv = exchange.fetch_ohlcv(btc_symbol(exchange), "5m", limit=limit)
        frame = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return frame
    except Exception as exc:
        logger.warning("Historical price fetch failed: %s", exc)
        return pd.DataFrame()


def compute_ta_signals(frame: pd.DataFrame) -> tuple[float, str]:
    if len(frame) < 50:
        return 0.5, "neutral"
    working = frame.copy()
    working["rsi"] = ta.rsi(working["close"], length=14)
    working["sma_short"] = ta.sma(working["close"], length=9)
    working["sma_long"] = ta.sma(working["close"], length=21)
    latest_rsi = float(working["rsi"].iloc[-1])
    if (
        working["sma_short"].iloc[-1] > working["sma_long"].iloc[-1]
        and latest_rsi < 70
    ):
        return 0.65, "bullish"
    if (
        working["sma_short"].iloc[-1] < working["sma_long"].iloc[-1]
        and latest_rsi > 30
    ):
        return 0.35, "bearish"
    return 0.5, "neutral"


def get_whale_proxy(settings: Settings, exchange: ccxt.Exchange) -> float:
    accum_score = 0.5
    whale_ratio = 0.5
    try:
        if settings.glassnode_api_key:
            response = requests.get(
                "https://api.glassnode.com/v1/metrics/indicators/accumulation_trend_score",
                params={"a": "BTC", "api_key": settings.glassnode_api_key},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            if payload:
                accum_score = float(payload[-1]["v"])
        if settings.cryptoquant_api_key:
            response = requests.get(
                "https://api.cryptoquant.com/v1/btc/flow-indicator/exchange-whale-ratio",
                params={"api_key": settings.cryptoquant_api_key},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json().get("data", [])
            if payload:
                whale_ratio = float(payload[-1].get("value", 0.5))
        whale_adj = (accum_score - 0.5) * 0.3 - (whale_ratio - 0.5) * 0.4
        logger.info(
            "Whale signals accum=%.2f whale_ratio=%.2f adj=%.3f",
            accum_score,
            whale_ratio,
            whale_adj,
        )
        return whale_adj
    except Exception as exc:
        logger.warning("Whale API unavailable, using exchange fallback: %s", exc)
        try:
            trades = exchange.fetch_trades(btc_symbol(exchange), limit=20)
            large_sell = any(
                trade["side"] == "sell" and trade["amount"] > 10 for trade in trades
            )
            return -0.08 if large_sell else 0.04
        except Exception:
            return 0.0


def get_orderbook_skew(ticker: str, exchange: ccxt.Exchange) -> float:
    try:
        response = requests.get(
            f"{KALSHI_API_BASE}/markets/{ticker}/orderbook",
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        orderbook = response.json().get("orderbook_fp", {})
        yes_volume = sum(
            parse_dollar(level[1]) for level in orderbook.get("yes_dollars", [])
        )
        no_volume = sum(
            parse_dollar(level[1]) for level in orderbook.get("no_dollars", [])
        )
        return (yes_volume - no_volume) / (yes_volume + no_volume + 1.0)
    except Exception as exc:
        logger.debug("Kalshi orderbook unavailable for %s: %s", ticker, exc)
        try:
            book = exchange.fetch_order_book(btc_symbol(exchange), limit=10)
            bid_volume = sum(level[1] for level in book["bids"])
            ask_volume = sum(level[1] for level in book["asks"])
            return (bid_volume - ask_volume) / (bid_volume + ask_volume + 1.0)
        except Exception:
            return 0.0


def calculate_edge(
    market: dict[str, Any],
    prob_model: float,
    whale_adj: float,
    orderbook_skew: float,
) -> tuple[float, float, str | None]:
    yes_ask = get_yes_ask(market)
    adjusted_prob = max(0.05, min(0.95, prob_model + whale_adj + orderbook_skew * 0.05))
    edge_score = abs(adjusted_prob - yes_ask)
    if adjusted_prob > yes_ask + 0.02:
        return edge_score, yes_ask, "yes"
    if adjusted_prob < yes_ask - 0.02:
        return edge_score, yes_ask, "no"
    return edge_score, yes_ask, None


def send_alert(settings: Settings, message: str) -> None:
    if settings.telegram_token and settings.telegram_chat_id:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Telegram alert failed: %s", exc)
    if settings.discord_webhook:
        try:
            response = requests.post(
                settings.discord_webhook,
                json={"content": message[:1900]},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Discord alert failed: %s", exc)


def create_kalshi_client(settings: Settings):
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_pem:
        raise ValueError(
            "Live trading requires KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PEM "
            "or KALSHI_PRIVATE_KEY_PATH"
        )
    from kalshi_python_sync import Configuration, KalshiClient

    configuration = Configuration(host=settings.kalshi_api_base)
    configuration.api_key_id = settings.kalshi_api_key_id
    configuration.private_key_pem = settings.kalshi_private_key_pem
    return KalshiClient(configuration)


def place_order(
    settings: Settings,
    client: Any,
    market: dict[str, Any],
    side: str,
    count: int,
) -> bool:
    ticker = market["ticker"]
    if settings.simulation_mode:
        yes_ask = get_yes_ask(market)
        logger.info(
            "[SIMULATION] buy %s %s contracts on %s around yes_ask=%.4f",
            side,
            count,
            ticker,
            yes_ask,
        )
        send_alert(settings, f"[SIM] BUY {side.upper()} {count} on {ticker}")
        return True

    if client is None:
        logger.error("Kalshi client is not initialized")
        return False

    payload: dict[str, Any] = {
        "ticker": ticker,
        "side": side,
        "action": "buy",
        "count": count,
        "type": "limit",
        "client_order_id": str(uuid.uuid4()),
        "time_in_force": "good_till_canceled",
    }
    if side == "yes":
        payload["yes_price_dollars"] = format_dollar_price(get_yes_ask(market))
    else:
        payload["no_price_dollars"] = format_dollar_price(get_no_ask(market))

    try:
        response = client.create_order(**payload)
        logger.info("Live order placed on %s: %s", ticker, response)
        send_alert(settings, f"LIVE BUY {side.upper()} {count} on {ticker}")
        return True
    except Exception as exc:
        logger.error("Order failed for %s: %s", ticker, exc)
        return False