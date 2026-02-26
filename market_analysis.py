"""
Daily Market Analysis Bot
=========================
Posts a daily market summary to 🌍-daily-market-analysis channel.
Runs at 10:00 AM ET (after market opens + initial volatility settles).

Includes: SPY performance, key index levels, sector movers, VIX, TMEM regime status.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_yf = None
_pd = None
_np = None


def _ensure_imports():
    global _yf, _pd, _np
    if _pd is None:
        import pandas as pd
        import numpy as np
        import yfinance as yf
        _pd, _np, _yf = pd, np, yf


def fetch_market_data() -> dict:
    """Fetch key market data for the daily summary."""
    _ensure_imports()

    tickers = {
        # Major indices
        "SPY": "S&P 500",
        "QQQ": "Nasdaq 100",
        "DIA": "Dow Jones",
        "IWM": "Russell 2000",
        # Volatility
        "^VIX": "VIX",
        # Sectors
        "XLK": "Technology",
        "XLF": "Financials",
        "XLV": "Healthcare",
        "XLE": "Energy",
        "XLI": "Industrials",
        "XLC": "Communication",
        "XLY": "Consumer Disc.",
        "XLP": "Consumer Staples",
        "XLRE": "Real Estate",
        "XLU": "Utilities",
        "XLB": "Materials",
        # Treasury / Bonds
        "TLT": "20+ Yr Treasury",
        "BIL": "T-Bills",
    }

    ticker_list = list(tickers.keys())

    data = _yf.download(
        ticker_list,
        period="5d",
        progress=False,
        auto_adjust=False,
        threads=True,
    )

    if data.empty:
        return {}

    results = {}

    for ticker, name in tickers.items():
        try:
            if isinstance(data.columns, _pd.MultiIndex):
                close = data["Adj Close"][ticker] if ticker != "^VIX" else data["Close"][ticker]
            else:
                close = data["Adj Close"]

            close = close.dropna()
            if len(close) < 2:
                continue

            current = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            daily_change = ((current / prev) - 1) * 100

            # 5-day change if available
            five_day_change = None
            if len(close) >= 5:
                five_day_change = ((current / float(close.iloc[0])) - 1) * 100

            results[ticker] = {
                "name": name,
                "price": round(current, 2),
                "daily_change": round(daily_change, 2),
                "five_day_change": round(five_day_change, 2) if five_day_change else None,
            }
        except Exception as e:
            logger.warning(f"Failed to get data for {ticker}: {e}")
            continue

    return results


def fetch_spy_sma_data() -> dict:
    """Fetch SPY and 200-SMA for TMEM regime context."""
    _ensure_imports()

    spy = _yf.download("SPY", period="1y", progress=False, auto_adjust=False)
    if spy.empty:
        return {}

    prices = spy["Adj Close"]
    if hasattr(prices, 'columns'):
        prices = prices.iloc[:, 0]

    sma_200 = prices.rolling(200).mean()

    current = float(prices.iloc[-1])
    sma = float(sma_200.iloc[-1])
    pct_diff = ((current / sma) - 1) * 100

    return {
        "spy_price": round(current, 2),
        "sma_200": round(sma, 2),
        "pct_diff": round(pct_diff, 2),
        "is_risk_on": current > sma,
    }


def format_market_analysis(market_data: dict, regime_data: dict) -> str:
    """Format the daily market analysis message."""
    date_str = datetime.now().strftime("%A, %B %d, %Y")

    msg = (
        f"**🌍 Daily Market Analysis — {date_str}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # Major Indices
    msg += "**📈 Major Indices**\n"
    for ticker in ["SPY", "QQQ", "DIA", "IWM"]:
        if ticker in market_data:
            d = market_data[ticker]
            arrow = "🟢" if d["daily_change"] >= 0 else "🔴"
            msg += f"{arrow} **{d['name']}**: ${d['price']} ({d['daily_change']:+.2f}%)\n"
    msg += "\n"

    # VIX
    if "^VIX" in market_data:
        vix = market_data["^VIX"]
        vix_level = "Low" if vix["price"] < 15 else "Moderate" if vix["price"] < 20 else "Elevated" if vix["price"] < 30 else "High"
        msg += f"**📊 Volatility (VIX):** {vix['price']} — {vix_level}\n\n"

    # TMEM Regime
    if regime_data:
        status = "🟢 RISK-ON" if regime_data["is_risk_on"] else "🔴 RISK-OFF"
        direction = "above" if regime_data["is_risk_on"] else "below"
        msg += (
            f"**🛡️ TMEM Regime:** {status}\n"
            f"SPY ${regime_data['spy_price']} is {abs(regime_data['pct_diff']):.2f}% "
            f"{direction} the 200-SMA (${regime_data['sma_200']})\n\n"
        )

    # Sector Performance
    msg += "**🏭 Sector Performance (Today)**\n"
    sectors = []
    for ticker in ["XLK", "XLF", "XLV", "XLE", "XLI", "XLC", "XLY", "XLP", "XLRE", "XLU", "XLB"]:
        if ticker in market_data:
            sectors.append(market_data[ticker])

    # Sort by daily change
    sectors.sort(key=lambda x: x["daily_change"], reverse=True)

    for s in sectors:
        arrow = "🟢" if s["daily_change"] >= 0 else "🔴"
        msg += f"{arrow} {s['name']}: {s['daily_change']:+.2f}%\n"

    msg += "\n"

    # Bonds
    if "TLT" in market_data:
        tlt = market_data["TLT"]
        msg += f"**🏦 Bonds:** 20+ Yr Treasury (TLT) ${tlt['price']} ({tlt['daily_change']:+.2f}%)\n\n"

    # Market Summary
    spy = market_data.get("SPY", {})
    if spy:
        if spy["daily_change"] > 1:
            mood = "Strong bullish momentum today."
        elif spy["daily_change"] > 0:
            mood = "Mild positive day for equities."
        elif spy["daily_change"] > -1:
            mood = "Slight pullback — nothing unusual."
        else:
            mood = "Notable selling pressure today."

        msg += f"**📝 Summary:** {mood}\n"

    msg += (
        "\n*This analysis is informational only and not financial advice.*"
    )

    return msg


async def post_daily_analysis(bot, guild_id: int):
    """Fetch data and post the daily analysis to Discord."""
    import discord

    guild = bot.get_guild(guild_id)
    if not guild:
        logger.error(f"Guild {guild_id} not found")
        return

    channel = discord.utils.get(guild.text_channels, name="🌍-daily-market-analysis")
    if not channel:
        logger.warning("Channel 🌍-daily-market-analysis not found")
        return

    try:
        logger.info("Fetching daily market data...")
        market_data = fetch_market_data()
        regime_data = fetch_spy_sma_data()

        if not market_data:
            logger.error("No market data fetched")
            return

        msg = format_market_analysis(market_data, regime_data)
        await channel.send(msg)
        logger.info("Posted daily market analysis")

    except Exception as e:
        logger.error(f"Daily market analysis failed: {e}", exc_info=True)
