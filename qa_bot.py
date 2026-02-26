"""
Client Q&A Bot
==============
Answers subscriber questions about TMEM and MEC strategies using Claude API.

Responds when:
- Someone mentions @quantdesk in a channel
- Someone sends a message in specific Q&A channels

Has built-in knowledge about both strategies and general market concepts.
"""

import logging
import os
from datetime import datetime
from typing import Optional

import discord

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """You are QuantDesk, the AI assistant for B&D Digital's trading signal service. 
You help subscribers understand the TMEM and MEC strategies.

ABOUT THE STRATEGIES:

**TMEM (Trend-Managed Equity Momentum) — Defensive Strategy ($19.99/mo)**
- Uses SPY vs 200-day SMA as a regime filter
- Risk-On (SPY above 200-SMA): Holds top 30 momentum stocks, equal weighted
- Risk-Off (SPY below 200-SMA): Moves entirely to cash/T-bills (BIL)
- Momentum signal: 12-1 month momentum (returns from 12 months ago to 1 month ago)
- Rebalances quarterly (January, April, July, October)
- Daily regime checks posted every trading day
- Filters: minimum $5 price, $20M average daily volume
- Universe: ~180 large-cap S&P 500 stocks
- Key benefit: Protects capital during bear markets while capturing upside

**MEC (Momentum-Led Earnings Confirmation) — Offensive Strategy ($19.99/mo)**
- Fully invested at all times — no market timing
- Ranks stocks by 12-1 month momentum
- Earnings confirmation filter: requires positive 6-month or 3-month momentum
- Holds top 40 stocks, equal weighted
- Rebalances monthly (1st trading day of each month)
- Same universe and liquidity filters as TMEM
- Key benefit: Maximizes returns in bull markets

RULES:
- Be helpful, concise, and friendly
- Always remind users that this is not financial advice
- Never recommend specific buy/sell actions beyond what the signals say
- If asked about something outside your knowledge, say so
- Keep responses under 300 words
- Don't reveal internal implementation details (code, APIs, etc.)
- If asked about account/billing issues, direct them to Whop support
"""


async def get_ai_response(question: str, channel_context: str = "") -> str:
    """Get a response from Claude API."""
    try:
        import httpx
    except ImportError:
        import subprocess
        subprocess.check_call(["pip", "install", "httpx", "--break-system-packages", "-q"])
        import httpx

    if not ANTHROPIC_API_KEY:
        return "⚠️ Q&A bot is not configured yet. Please contact an admin."

    context = f"The user is asking in the #{channel_context} channel. " if channel_context else ""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 500,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": f"{context}{question}"}
                    ],
                },
            )

            if response.status_code != 200:
                logger.error(f"Claude API error: {response.status_code} {response.text}")
                return "Sorry, I'm having trouble right now. Please try again later."

            data = response.json()
            reply = data["content"][0]["text"]
            return reply

    except Exception as e:
        logger.error(f"Q&A bot error: {e}", exc_info=True)
        return "Sorry, I'm having trouble right now. Please try again later."


# Channels where the bot responds to all messages
QA_CHANNELS = [
    "💬-tmem-discussion",
    "💬-mec-discussion",
    "💬-general",
]

# Cooldown tracking to avoid spam
_last_response = {}
COOLDOWN_SECONDS = 10


def setup_qa_bot(bot: discord.ext.commands.Bot, guild_id: int):
    """Set up the Q&A message listener."""

    @bot.event
    async def on_message(message: discord.Message):
        # Don't respond to ourselves or other bots
        if message.author.bot:
            return

        # Process commands first
        await bot.process_commands(message)

        # Check if this is a command (starts with !)
        if message.content.startswith("!"):
            return

        guild = bot.get_guild(guild_id)
        if not guild or message.guild != guild:
            return

        should_respond = False
        channel_name = message.channel.name if hasattr(message.channel, 'name') else ""

        # Respond if bot is mentioned
        if bot.user in message.mentions:
            should_respond = True

        # Respond if message is a question in discussion channels
        if channel_name in QA_CHANNELS and "?" in message.content:
            should_respond = True

        if not should_respond:
            return

        # Cooldown check
        user_key = f"{message.author.id}-{message.channel.id}"
        now = datetime.now().timestamp()
        if user_key in _last_response:
            if now - _last_response[user_key] < COOLDOWN_SECONDS:
                return
        _last_response[user_key] = now

        # Get the question (remove bot mention if present)
        question = message.content
        for mention in message.mentions:
            question = question.replace(f"<@{mention.id}>", "").strip()
            question = question.replace(f"<@!{mention.id}>", "").strip()

        if len(question) < 3:
            return

        # Show typing indicator
        async with message.channel.typing():
            reply = await get_ai_response(question, channel_name)

        await message.reply(reply, mention_author=False)

    logger.info("Q&A bot listener registered")
