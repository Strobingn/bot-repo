"""Kalshi BTC edge-hunting bot."""

from __future__ import annotations

import os
import time
from datetime import datetime

import pandas as pd

from kalshi_common import (
    Settings,
    calculate_edge,
    compute_ta_signals,
    configure_logging,
    create_exchange,
    create_kalshi_client,
    fetch_historical_prices,
    get_btc_price,
    get_kalshi_btc_markets,
    get_orderbook_skew,
    get_whale_proxy,
    get_yes_ask,
    is_short_term_market,
    logger,
    market_volume,
    place_order,
    send_alert,
)

settings = Settings.from_env()
exchange = create_exchange(os.getenv("CCXT_EXCHANGE"))
kalshi_client = None


def init_live_client() -> None:
    global kalshi_client
    if settings.simulation_mode:
        logger.info("Simulation mode enabled; live Kalshi client not initialized")
        return
    kalshi_client = create_kalshi_client(settings)
    logger.info("Kalshi live trading client initialized")


def log_snapshot(
    btc_price: float,
    btc_change: float,
    prob_model: float,
    signal: str,
    whale_adj: float,
    markets: list[dict],
    evaluations: list[dict],
) -> None:
    timestamp = datetime.now().isoformat()
    rows = []
    evaluated = {item["ticker"]: item for item in evaluations}
    for market in markets:
        ticker = market.get("ticker")
        evaluation = evaluated.get(ticker, {})
        rows.append(
            {
                "timestamp": timestamp,
                "btc_price": btc_price,
                "btc_change_24h": btc_change,
                "prob_model": prob_model,
                "ta_signal": signal,
                "whale_adj": whale_adj,
                "ticker": ticker,
                "title": market.get("title"),
                "yes_ask": get_yes_ask(market),
                "volume": market_volume(market),
                "edge_score": evaluation.get("edge_score", 0),
                "recommended_side": evaluation.get("side"),
                "orderbook_skew": evaluation.get("orderbook_skew", 0),
                "traded": evaluation.get("traded", False),
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(
        settings.log_file,
        mode="a",
        header=not os.path.exists(settings.log_file),
        index=False,
    )


def run_backtest() -> float:
    if not os.path.exists(settings.log_file):
        logger.info("No log file found; skipping backtest")
        return 0.0

    frame = pd.read_csv(settings.log_file)
    if frame.empty:
        return 0.0

    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp")
    candidates = frame[frame["edge_score"] >= settings.edge_threshold].copy()
    if candidates.empty:
        logger.info("No edge candidates in log for backtest")
        return 0.0

    candidates["next_btc_price"] = candidates["btc_price"].shift(-1)
    candidates["btc_move"] = candidates["next_btc_price"] - candidates["btc_price"]
    candidates = candidates.dropna(subset=["next_btc_price"])

    wins = 0
    pnl = 0.0
    for _, row in candidates.iterrows():
        side = str(row.get("recommended_side", "")).lower()
        move = float(row["btc_move"])
        if side == "yes" and move > 0:
            wins += 1
            pnl += 1.0
        elif side == "no" and move < 0:
            wins += 1
            pnl += 1.0
        else:
            pnl -= 1.0

    win_rate = (wins / len(candidates)) * 100 if len(candidates) else 0.0
    logger.info(
        "Backtest over %s candidates: win_rate=%.1f%% proxy_pnl=%.2f",
        len(candidates),
        win_rate,
        pnl,
    )
    candidates.to_csv(settings.backtest_file, index=False)
    return pnl


def evaluate_markets(
    markets: list[dict],
    prob_model: float,
    whale_adj: float,
) -> list[dict]:
    evaluations: list[dict] = []
    for market in markets:
        if not is_short_term_market(market, settings.strategy_mode):
            continue
        ticker = market.get("ticker", "")
        skew = get_orderbook_skew(ticker, exchange)
        edge_score, yes_ask, side = calculate_edge(market, prob_model, whale_adj, skew)
        traded = False
        if side and edge_score >= settings.edge_threshold:
            traded = place_order(
                settings,
                kalshi_client,
                market,
                side,
                settings.max_contracts,
            )
        evaluations.append(
            {
                "ticker": ticker,
                "title": market.get("title"),
                "yes_ask": yes_ask,
                "edge_score": edge_score,
                "side": side,
                "orderbook_skew": skew,
                "traded": traded,
            }
        )
        logger.info(
            "%s | yes_ask=%.4f edge=%.3f side=%s skew=%.3f traded=%s",
            ticker,
            yes_ask,
            edge_score,
            side,
            skew,
            traded,
        )
    return evaluations


def main() -> None:
    configure_logging()
    init_live_client()
    if os.path.exists(settings.log_file):
        run_backtest()

    logger.info(
        "Starting Kalshi BTC bot mode=%s simulation=%s threshold=%.2f",
        settings.strategy_mode,
        settings.simulation_mode,
        settings.edge_threshold,
    )
    send_alert(
        settings,
        f"Kalshi BTC bot started ({settings.strategy_mode}, simulation={settings.simulation_mode})",
    )

    while True:
        try:
            btc_price, btc_change = get_btc_price(exchange)
            markets = get_kalshi_btc_markets(settings.strategy_mode)
            history = fetch_historical_prices(exchange)
            prob_model, signal = compute_ta_signals(history)
            whale_adj = get_whale_proxy(settings, exchange)
            top_markets = markets[:15]

            logger.info(
                "BTC=%.2f (%+.2f%%) markets=%s ta=%s whale_adj=%.3f",
                btc_price,
                btc_change,
                len(top_markets),
                signal,
                whale_adj,
            )

            evaluations = evaluate_markets(top_markets, prob_model, whale_adj)
            traded = [item for item in evaluations if item["traded"]]
            if traded:
                send_alert(
                    settings,
                    f"Trades placed: {', '.join(item['ticker'] for item in traded)}",
                )

            log_snapshot(
                btc_price,
                btc_change,
                prob_model,
                signal,
                whale_adj,
                top_markets,
                evaluations,
            )
        except Exception as exc:
            logger.exception("Main loop error: %s", exc)

        time.sleep(settings.loop_interval_seconds)


if __name__ == "__main__":
    main()