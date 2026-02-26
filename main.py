"""
QuantDesk — Main Entry Point.
Runs Discord bot + Whop webhook server together.
"""

import asyncio
import logging
import threading
import uvicorn

from config import DISCORD_BOT_TOKEN, WEBHOOK_HOST, WEBHOOK_PORT
import discord_bot
from webhook_handler import app, set_discord_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_webhook_server():
    uvicorn.run(app, host=WEBHOOK_HOST, port=WEBHOOK_PORT, log_level="info")


async def main():
    set_discord_bot(discord_bot)
    
    webhook_thread = threading.Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()
    logger.info(f"Webhook server on {WEBHOOK_HOST}:{WEBHOOK_PORT}")

    logger.info("Starting QuantDesk bot...")
    await discord_bot.bot.start(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
