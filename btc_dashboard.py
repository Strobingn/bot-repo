"""Streamlit dashboard for BTC and Kalshi markets."""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from kalshi_common import (
    Settings,
    get_btc_price,
    get_kalshi_btc_markets,
    get_yes_ask,
    market_volume,
)

settings = Settings.from_env()

st.set_page_config(page_title="Kalshi BTC Dashboard", layout="wide")
st.title("Kalshi BTC Dashboard")

refresh_seconds = st.sidebar.slider("Refresh interval (seconds)", 10, 120, 30)
auto_refresh = st.sidebar.toggle("Auto refresh", value=True)
strategy_mode = st.sidebar.selectbox(
    "Strategy mode",
    ["15min", "hourly", "daily", "all"],
    index=["15min", "hourly", "daily", "all"].index(settings.strategy_mode)
    if settings.strategy_mode in {"15min", "hourly", "daily", "all"}
    else 0,
)

if st.sidebar.button("Refresh now"):
    st.rerun()

try:
    price, change = get_btc_price()
except Exception as exc:
    st.error(f"Failed to fetch BTC price: {exc}")
    price, change = 0.0, 0.0

markets = get_kalshi_btc_markets(strategy_mode, limit=50)
col1, col2, col3 = st.columns(3)
col1.metric("BTC Price", f"${price:,.2f}", f"{change:+.2f}%")
col2.metric("Last Update", datetime.now().strftime("%H:%M:%S"))
col3.metric("Open Markets", len(markets))

st.subheader("Kalshi BTC Prediction Markets")
if markets:
    rows = []
    for market in markets:
        rows.append(
            {
                "Ticker": market.get("ticker"),
                "Title": market.get("title"),
                "Yes Ask": get_yes_ask(market),
                "Volume": market_volume(market),
                "Close Time": market.get("close_time"),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
else:
    st.warning("No open Kalshi BTC markets found for the selected mode.")

st.caption("Run with: streamlit run btc_dashboard.py")

if auto_refresh:
    time.sleep(refresh_seconds)
    st.rerun()