"""
Configuration for QuantDesk Bot.
Works alongside Whop's native Discord integration.
Whop handles: server join/leave
QuantDesk handles: role assignment, channel setup, signals
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Discord ───────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))

# ─── Whop ──────────────────────────────────────────────────
WHOP_WEBHOOK_SECRET = os.getenv("WHOP_WEBHOOK_SECRET")

# ─── Webhook Server ───────────────────────────────────────
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8000"))

# ─── Product → Role Mapping ───────────────────────────────
PRODUCT_ROLE_MAP = {
    os.getenv("WHOP_TMEM_SIGNALS_PRODUCT_ID", ""): "TMEM Signals",
    os.getenv("WHOP_MEC_SIGNALS_PRODUCT_ID", ""):  "MEC Signals",
}

# ─── Discord Channel Structure ────────────────────────────
CHANNEL_STRUCTURE = {
    # ── Public (everyone can see) ──
    "📢-announcements": {
        "category": "GENERAL",
        "access": "public",
        "topic": "Official announcements and updates",
    },
    "💬-general": {
        "category": "GENERAL",
        "access": "public",
        "topic": "General discussion for all members",
    },
    "📚-education": {
        "category": "GENERAL",
        "access": "public",
        "topic": "Educational content on momentum investing",
    },

    # ── TMEM (only TMEM Signals role) ──
    "📊-tmem-signals": {
        "category": "TMEM TRADING",
        "access": ["TMEM Signals"],
        "topic": "Daily risk-on/off signals & monthly top 30 picks",
    },
    "📈-tmem-performance": {
        "category": "TMEM TRADING",
        "access": ["TMEM Signals"],
        "topic": "Monthly performance reports for TMEM",
    },
    "💬-tmem-discussion": {
        "category": "TMEM TRADING",
        "access": ["TMEM Signals"],
        "topic": "Discussion for TMEM subscribers",
    },

    # ── MEC (only MEC Signals role) ──
    "📊-mec-signals": {
        "category": "MEC TRADING",
        "access": ["MEC Signals"],
        "topic": "Monthly top 40 momentum + earnings stock picks",
    },
    "📈-mec-performance": {
        "category": "MEC TRADING",
        "access": ["MEC Signals"],
        "topic": "Monthly performance reports for MEC",
    },
    "💬-mec-discussion": {
        "category": "MEC TRADING",
        "access": ["MEC Signals"],
        "topic": "Discussion for MEC subscribers",
    },

    # ── Public Market Analysis ──
    "🌍-daily-market-analysis": {
        "category": "MARKET INSIGHTS",
        "access": "public",
        "topic": "Daily market overview & commentary",
    },
}

# ─── Role Colors ──────────────────────────────────────────
ROLE_COLORS = {
    "TMEM Signals": 0x3498DB,  # Blue
    "MEC Signals":  0xE67E22,  # Orange
}
