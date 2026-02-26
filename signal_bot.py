"""
QuantDesk Signal Bot
====================
Runs daily analysis and posts signals to Discord.

Daily:  TMEM risk-on/off check (SPY vs 200-day SMA)
1st of month: Full rebalance for both TMEM (top 30) and MEC (top 40)
"""

import asyncio
import logging
from datetime import datetime, time as dtime
from typing import Optional

import discord
from discord.ext import tasks, commands

logger = logging.getLogger(__name__)

# Lazy imports — only load heavy libs when actually running signals
_yf = None
_pd = None
_np = None


def _ensure_imports():
    """Lazy import heavy libraries."""
    global _yf, _pd, _np
    if _pd is None:
        import pandas as pd
        import numpy as np
        import yfinance as yf
        _pd, _np, _yf = pd, np, yf


# ─── S&P 500 Universe ─────────────────────────────────────
# Combined from both strategies — large-cap liquid stocks

SP500_UNIVERSE = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AVGO", "CSCO", "ADBE", "CRM",
    "ORCL", "ACN", "IBM", "INTC", "AMD", "QCOM", "TXN", "NOW", "INTU", "AMAT",
    "MU", "ADI", "LRCX", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "MCHP", "ON",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "SPGI",
    "CB", "MMC", "PNC", "USB", "TFC", "AIG", "MET", "PRU", "AFL", "ALL",
    "CME", "ICE", "MCO", "MSCI", "COF", "DFS", "BK", "STT",
    # Healthcare
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "ISRG", "CVS", "ELV", "CI", "MDT", "SYK", "BSX", "REGN",
    "VRTX", "ZTS", "BDX", "HCA", "DXCM", "IQV", "A", "IDXX",
    # Consumer Discretionary
    "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "CMG",
    "ORLY", "AZO", "ROST", "DHI", "LEN", "MAR", "HLT", "YUM",
    "F", "GM", "EBAY", "BBY", "GPC", "POOL", "ULTA",
    # Consumer Staples
    "PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL",
    "KMB", "GIS", "HSY", "STZ", "KHC", "CLX", "CHD", "KR", "SYY", "ADM",
    # Industrials
    "CAT", "DE", "UNP", "UPS", "HON", "RTX", "BA", "LMT", "GE",
    "ETN", "ITW", "EMR", "PH", "ROK", "CMI", "PCAR", "FAST", "ODFL", "CSX",
    "NSC", "WM", "RSG", "GD", "NOC", "TT", "CARR",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY",
    "HES", "DVN", "FANG", "HAL", "BKR", "KMI", "WMB", "OKE",
    # Materials
    "LIN", "APD", "SHW", "ECL", "DD", "NEM", "FCX", "NUE", "VMC", "MLM",
    "DOW", "PPG",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL",
    # Communication
    "GOOG", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "CHTR",
    # REITs
    "PLD", "AMT", "CCI", "EQIX", "PSA", "O",
]


# ─── Data Fetching ─────────────────────────────────────────

def fetch_spy_data(lookback_days: int = 400) -> "pd.DataFrame":
    """Fetch SPY price data for regime analysis."""
    _ensure_imports()
    end = _pd.Timestamp.now()
    start = end - _pd.Timedelta(days=lookback_days)
    data = _yf.download("SPY", start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=False)
    return data


def fetch_universe_data(tickers: list, lookback_days: int = 400) -> tuple:
    """
    Fetch price and volume data for the full universe.
    Returns (prices_df, volume_df) with tickers as columns.
    """
    _ensure_imports()
    end = _pd.Timestamp.now()
    start = end - _pd.Timedelta(days=lookback_days)

    logger.info(f"Fetching data for {len(tickers)} tickers...")
    data = _yf.download(
        tickers,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=False,
        threads=True,
    )

    if data.empty:
        return _pd.DataFrame(), _pd.DataFrame()

    # Handle yfinance MultiIndex columns
    if isinstance(data.columns, _pd.MultiIndex):
        prices = data["Adj Close"]
        volume = data["Volume"]
    else:
        # Single ticker case
        prices = data[["Adj Close"]].rename(columns={"Adj Close": tickers[0]})
        volume = data[["Volume"]].rename(columns={"Volume": tickers[0]})

    return prices, volume


# ─── TMEM Strategy Logic ──────────────────────────────────

def compute_tmem_regime(spy_prices: "pd.Series", sma_lookback: int = 200) -> dict:
    """
    Compute TMEM risk-on/risk-off regime.

    Returns dict with:
    - is_risk_on: bool
    - spy_price: float
    - sma_value: float
    - spy_above_sma_pct: float (how far above/below SMA in %)
    """
    _ensure_imports()

    if len(spy_prices) < sma_lookback:
        raise ValueError(f"Need at least {sma_lookback} days of SPY data, got {len(spy_prices)}")

    sma = spy_prices.rolling(window=sma_lookback, min_periods=sma_lookback).mean()

    current_price = spy_prices.iloc[-1]
    current_sma = sma.iloc[-1]
    is_risk_on = current_price > current_sma
    pct_diff = ((current_price / current_sma) - 1) * 100

    return {
        "is_risk_on": is_risk_on,
        "spy_price": round(float(current_price), 2),
        "sma_value": round(float(current_sma), 2),
        "pct_diff": round(float(pct_diff), 2),
    }


def compute_tmem_top_stocks(prices: "pd.DataFrame", volume: "pd.DataFrame",
                            n_holdings: int = 30) -> list:
    """
    Compute TMEM top momentum stocks (12-1 month momentum).

    Returns list of dicts with ticker, momentum score, and rank.
    """
    _ensure_imports()

    # 12-1 month momentum: return from t-252 to t-21
    price_end = prices.shift(21)     # price 1 month ago
    price_start = prices.shift(252)  # price 12 months ago

    momentum = (price_end / price_start) - 1

    # Get latest momentum scores
    latest = momentum.iloc[-1].dropna()

    # Filter: need minimum price and liquidity
    current_prices = prices.iloc[-1]
    price_filter = current_prices >= 5.0

    # ADV filter: 60-day average dollar volume > $20M
    dollar_vol = prices * volume
    adv_60 = dollar_vol.rolling(60).mean().iloc[-1]
    adv_filter = adv_60 >= 20_000_000

    # Combine filters
    eligible = latest.index.intersection(price_filter[price_filter].index)
    eligible = eligible.intersection(adv_filter[adv_filter].index)

    scores = latest[eligible].sort_values(ascending=False)
    top_n = scores.head(n_holdings)

    result = []
    for rank, (ticker, score) in enumerate(top_n.items(), 1):
        result.append({
            "rank": rank,
            "ticker": ticker,
            "momentum": round(float(score) * 100, 2),  # as percentage
            "price": round(float(current_prices.get(ticker, 0)), 2),
        })

    return result


# ─── MEC Strategy Logic ───────────────────────────────────

def compute_mec_top_stocks(prices: "pd.DataFrame", volume: "pd.DataFrame",
                           n_holdings: int = 40) -> list:
    """
    Compute MEC top stocks: 12-1 momentum + earnings confirmation proxy.

    Since we don't have real-time earnings surprise data via yfinance,
    we use a momentum quality proxy:
    - 12-1 month momentum (primary ranking)
    - 6-month momentum > 0 (earnings confirmation proxy)
    - Positive 3-month momentum (recent trend confirmation)

    Returns list of dicts with ticker, momentum, and rank.
    """
    _ensure_imports()

    # 12-1 month momentum
    price_1m = prices.shift(21)
    price_12m = prices.shift(252)
    mom_12_1 = (price_1m / price_12m) - 1

    # 6-month momentum (earnings confirmation proxy)
    price_6m = prices.shift(126)
    mom_6m = (price_1m / price_6m) - 1

    # 3-month momentum (recent trend)
    price_3m = prices.shift(63)
    mom_3m = (price_1m / price_3m) - 1

    # Get latest scores
    latest_12_1 = mom_12_1.iloc[-1].dropna()
    latest_6m = mom_6m.iloc[-1].dropna()
    latest_3m = mom_3m.iloc[-1].dropna()

    # Filters
    current_prices = prices.iloc[-1]
    price_filter = current_prices >= 5.0

    dollar_vol = prices * volume
    adv_60 = dollar_vol.rolling(60).mean().iloc[-1]
    adv_filter = adv_60 >= 20_000_000

    # Combine: price + liquidity + earnings confirmation proxy
    eligible = latest_12_1.index
    eligible = eligible.intersection(price_filter[price_filter].index)
    eligible = eligible.intersection(adv_filter[adv_filter].index)

    # Earnings confirmation: 6-month momentum > 0 OR 3-month momentum > 0
    earnings_confirmed = eligible[
        (latest_6m.reindex(eligible) > 0) | (latest_3m.reindex(eligible) > 0)
    ]

    # Rank by 12-1 momentum among confirmed stocks
    scores = latest_12_1[earnings_confirmed].sort_values(ascending=False)
    top_n = scores.head(n_holdings)

    result = []
    for rank, (ticker, score) in enumerate(top_n.items(), 1):
        result.append({
            "rank": rank,
            "ticker": ticker,
            "momentum": round(float(score) * 100, 2),
            "price": round(float(current_prices.get(ticker, 0)), 2),
        })

    return result


# ─── Discord Message Formatting ───────────────────────────

def format_tmem_daily_signal(regime: dict) -> str:
    """Format TMEM daily regime signal for Discord."""
    status = "🟢 RISK-ON" if regime["is_risk_on"] else "🔴 RISK-OFF"
    direction = "above" if regime["is_risk_on"] else "below"

    msg = (
        f"**📊 TMEM Daily Signal — {datetime.now().strftime('%B %d, %Y')}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"**Regime: {status}**\n\n"
        f"SPY: **${regime['spy_price']}**\n"
        f"200-day SMA: **${regime['sma_value']}**\n"
        f"SPY is **{abs(regime['pct_diff']):.2f}%** {direction} the 200-SMA\n\n"
    )

    if regime["is_risk_on"]:
        msg += (
            "**Action:** Hold top 30 momentum stocks.\n"
            "Portfolio remains fully invested in equities."
        )
    else:
        msg += (
            "**Action:** Move to defensive allocation (cash/T-bills).\n"
            "Capital preservation mode active."
        )

    msg += (
        "\n\n*⚠️ This is not financial advice. "
        "Past performance does not guarantee future results.*"
    )

    return msg


def format_tmem_monthly_picks(regime: dict, picks: list) -> str:
    """Format TMEM quarterly rebalance for Discord."""
    status = "🟢 RISK-ON" if regime["is_risk_on"] else "🔴 RISK-OFF"
    date_str = datetime.now().strftime("%B %Y")

    msg = (
        f"**📊 TMEM Quarterly Rebalance — {date_str}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"**Regime: {status}**\n\n"
    )

    if not regime["is_risk_on"]:
        msg += (
            "SPY is **below** the 200-day SMA.\n"
            "**Action:** 100% defensive — hold cash/T-bills (BIL).\n"
            "No equity positions this month.\n\n"
            "*Portfolio will re-enter equities when SPY crosses above the 200-SMA.*"
        )
    else:
        msg += f"**Top 30 Momentum Stocks — Equal Weight (3.33% each):**\n\n"
        msg += "```\n"
        msg += f"{'Rank':<6} {'Ticker':<8} {'12-1 Mom %':<12} {'Price':>8}\n"
        msg += f"{'─'*6} {'─'*8} {'─'*12} {'─'*8}\n"

        for pick in picks:
            msg += (
                f"{pick['rank']:<6} {pick['ticker']:<8} "
                f"{pick['momentum']:>+10.2f}%  ${pick['price']:>7.2f}\n"
            )

        msg += "```\n\n"
        msg += (
            "**Rebalance instructions:**\n"
            "• Equal-weight all 30 stocks at ~3.33% each\n"
            "• Sell any stocks no longer in the top 30\n"
            "• Buy new entries at equal weight\n"
            "• Next rebalance: 1st trading day of next quarter (Jan/Apr/Jul/Oct)"
        )

    msg += (
        "\n\n*⚠️ This is not financial advice. "
        "Past performance does not guarantee future results.*"
    )

    return msg


def format_mec_monthly_picks(picks: list) -> str:
    """Format MEC monthly rebalance for Discord."""
    date_str = datetime.now().strftime("%B %Y")

    msg = (
        f"**📊 MEC Monthly Rebalance — {date_str}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"**Top 40 Momentum + Earnings Confirmed Stocks**\n"
        f"Equal Weight (2.50% each) | Fully Invested\n\n"
    )

    msg += "```\n"
    msg += f"{'Rank':<6} {'Ticker':<8} {'12-1 Mom %':<12} {'Price':>8}\n"
    msg += f"{'─'*6} {'─'*8} {'─'*12} {'─'*8}\n"

    for pick in picks:
        msg += (
            f"{pick['rank']:<6} {pick['ticker']:<8} "
            f"{pick['momentum']:>+10.2f}%  ${pick['price']:>7.2f}\n"
        )

    msg += "```\n\n"
    msg += (
        "**Rebalance instructions:**\n"
        "• Equal-weight all 40 stocks at 2.50% each\n"
        "• Sell any stocks no longer in the top 40\n"
        "• Buy new entries at equal weight\n"
        "• MEC remains fully invested — no market timing\n"
        "• Next rebalance: 1st trading day of next month"
    )

    msg += (
        "\n\n*⚠️ This is not financial advice. "
        "Past performance does not guarantee future results.*"
    )

    return msg


# ─── Signal Runner ─────────────────────────────────────────

class SignalBot:
    """
    Manages signal computation and posting schedule.
    Runs as discord.ext.tasks loop inside the QuantDesk bot.
    """

    def __init__(self, bot: commands.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self._last_daily_run: Optional[str] = None
        self._last_monthly_run: Optional[str] = None

    def get_channel(self, name: str) -> Optional[discord.TextChannel]:
        """Find a channel by name in the guild."""
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return None
        return discord.utils.get(guild.text_channels, name=name)

    async def run_daily_tmem_signal(self):
        """Run TMEM daily regime check and post to Discord."""
        today = datetime.now().strftime("%Y-%m-%d")

        # Skip if already ran today
        if self._last_daily_run == today:
            logger.info("Daily TMEM signal already posted today, skipping.")
            return

        logger.info("Running TMEM daily regime check...")

        try:
            spy_data = fetch_spy_data(lookback_days=400)

            if spy_data.empty:
                logger.error("Failed to fetch SPY data")
                return

            # Get adjusted close prices
            if "Adj Close" in spy_data.columns:
                spy_prices = spy_data["Adj Close"]
            else:
                spy_prices = spy_data["Close"]

            # Handle MultiIndex from yfinance
            if hasattr(spy_prices, 'columns'):
                spy_prices = spy_prices.iloc[:, 0]

            regime = compute_tmem_regime(spy_prices)
            msg = format_tmem_daily_signal(regime)

            channel = self.get_channel("📊-tmem-signals")
            if channel:
                await channel.send(msg)
                logger.info(
                    f"Posted TMEM daily signal: "
                    f"{'RISK-ON' if regime['is_risk_on'] else 'RISK-OFF'} "
                    f"(SPY ${regime['spy_price']} vs SMA ${regime['sma_value']})"
                )
            else:
                logger.warning("Channel 📊-tmem-signals not found")

            self._last_daily_run = today

        except Exception as e:
            logger.error(f"TMEM daily signal failed: {e}", exc_info=True)

    async def run_monthly_rebalance(self):
        """
        Run rebalance:
        - MEC: every month (top 40)
        - TMEM: quarterly only — Jan, Apr, Jul, Oct (top 30)
        Both post on the 1st-3rd of the relevant month.
        """
        today = datetime.now()
        month_key = today.strftime("%Y-%m")

        # Skip if already ran this month
        if self._last_monthly_run == month_key:
            logger.info("Rebalance already posted this month, skipping.")
            return

        # Only run on the 1st-3rd (grace period for weekends)
        if today.day > 3:
            return

        logger.info("Running rebalance...")

        try:
            # Fetch all data once
            spy_data = fetch_spy_data(lookback_days=400)
            prices, volume = fetch_universe_data(SP500_UNIVERSE, lookback_days=400)

            if prices.empty:
                logger.error("Failed to fetch universe data")
                return

            # Get SPY prices
            if "Adj Close" in spy_data.columns:
                spy_prices = spy_data["Adj Close"]
            else:
                spy_prices = spy_data["Close"]
            if hasattr(spy_prices, 'columns'):
                spy_prices = spy_prices.iloc[:, 0]

            # ── TMEM Rebalance (Quarterly: Jan, Apr, Jul, Oct) ──
            is_tmem_quarter = today.month in [1, 4, 7, 10]

            if is_tmem_quarter:
                regime = compute_tmem_regime(spy_prices)
                tmem_picks = []
                if regime["is_risk_on"]:
                    tmem_picks = compute_tmem_top_stocks(prices, volume, n_holdings=30)

                tmem_msg = format_tmem_monthly_picks(regime, tmem_picks)

                tmem_channel = self.get_channel("📊-tmem-signals")
                if tmem_channel:
                    await tmem_channel.send(tmem_msg)
                    logger.info(f"Posted TMEM quarterly rebalance: {len(tmem_picks)} stocks")
                else:
                    logger.warning("Channel 📊-tmem-signals not found")
            else:
                logger.info(f"Skipping TMEM rebalance — not a quarter month (current: {today.month})")

            # ── MEC Rebalance (Monthly) ──
            mec_picks = compute_mec_top_stocks(prices, volume, n_holdings=40)
            mec_msg = format_mec_monthly_picks(mec_picks)

            mec_channel = self.get_channel("📊-mec-signals")
            if mec_channel:
                await mec_channel.send(mec_msg)
                logger.info(f"Posted MEC monthly rebalance: {len(mec_picks)} stocks")
            else:
                logger.warning("Channel 📊-mec-signals not found")

            self._last_monthly_run = month_key

        except Exception as e:
            logger.error(f"Rebalance failed: {e}", exc_info=True)

    async def run_all_signals(self):
        """Main signal runner — called by the scheduled task."""
        now = datetime.now()

        # Always run daily TMEM regime check (weekdays only)
        if now.weekday() < 5:  # Mon-Fri
            await self.run_daily_tmem_signal()

        # Run monthly rebalance on the 1st-3rd of each month
        if now.day <= 3 and now.weekday() < 5:
            await self.run_monthly_rebalance()


# ─── Discord Task Setup ───────────────────────────────────

signal_bot: Optional[SignalBot] = None


def setup_signal_tasks(bot: commands.Bot, guild_id: int):
    """
    Start the signal bot's scheduled tasks.
    Called from discord_bot.py after bot is ready.
    """
    global signal_bot
    signal_bot = SignalBot(bot, guild_id)

    @tasks.loop(time=dtime(hour=14, minute=30))  # 2:30 PM UTC ≈ 9:30 AM ET (market open)
    async def daily_signal_task():
        if signal_bot:
            await signal_bot.run_all_signals()

    @daily_signal_task.before_loop
    async def before_signal_task():
        await bot.wait_until_ready()
        logger.info("Signal task ready — will run daily at 14:30 UTC (9:30 AM ET)")

    daily_signal_task.start()

    # Admin command to force-run signals
    @bot.command(name="signals")
    @commands.has_permissions(administrator=True)
    async def cmd_force_signals(ctx):
        """Force-run all signals now (admin only)."""
        await ctx.send("⚙️ Running signals manually...")
        if signal_bot:
            await signal_bot.run_all_signals()
            await ctx.send("✅ Signals posted!")
        else:
            await ctx.send("❌ Signal bot not initialized")

    @bot.command(name="regime")
    @commands.has_permissions(administrator=True)
    async def cmd_check_regime(ctx):
        """Quick regime check without posting to signals channel."""
        _ensure_imports()
        try:
            spy_data = fetch_spy_data(lookback_days=400)
            spy_prices = spy_data["Adj Close"]
            if hasattr(spy_prices, 'columns'):
                spy_prices = spy_prices.iloc[:, 0]

            regime = compute_tmem_regime(spy_prices)
            status = "🟢 RISK-ON" if regime["is_risk_on"] else "🔴 RISK-OFF"
            direction = "above" if regime["is_risk_on"] else "below"

            await ctx.send(
                f"**TMEM Regime Check**\n"
                f"Status: {status}\n"
                f"SPY: ${regime['spy_price']} | 200-SMA: ${regime['sma_value']}\n"
                f"({abs(regime['pct_diff']):.2f}% {direction})"
            )
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    logger.info("Signal bot tasks registered")
