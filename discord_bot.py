"""
QuantDesk Discord Bot.
Works alongside Whop's native Discord integration:
- Whop handles: getting members into/out of the server
- QuantDesk handles: role assignment, channel permissions, welcome DMs
"""

import discord
from discord.ext import commands
import logging
import asyncio
from config import (
    DISCORD_BOT_TOKEN, DISCORD_GUILD_ID,
    CHANNEL_STRUCTURE, ROLE_COLORS, PRODUCT_ROLE_MAP,
)

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Pending role assignments for members who haven't joined yet
# Maps discord_id → role_name
pending_roles: dict[int, str] = {}


# ─── Helpers ───────────────────────────────────────────────

def get_guild() -> discord.Guild:
    guild = bot.get_guild(DISCORD_GUILD_ID)
    if not guild:
        raise ValueError(f"Guild {DISCORD_GUILD_ID} not found.")
    return guild


def get_role_by_name(guild: discord.Guild, role_name: str) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=role_name)


async def get_or_create_role(guild: discord.Guild, role_name: str) -> discord.Role:
    role = get_role_by_name(guild, role_name)
    if not role:
        color = discord.Color(ROLE_COLORS.get(role_name, 0x95A5A6))
        role = await guild.create_role(
            name=role_name, color=color, mentionable=True,
            reason="QuantDesk auto-setup",
        )
        logger.info(f"Created role: {role_name}")
    return role


# ─── Server Setup ─────────────────────────────────────────

async def setup_server():
    """Create roles, categories, and channels. Safe to run multiple times."""
    guild = get_guild()
    logger.info(f"Setting up server: {guild.name}")

    # Create roles
    roles = {}
    for role_name in ROLE_COLORS:
        roles[role_name] = await get_or_create_role(guild, role_name)
    logger.info(f"Roles ready: {list(roles.keys())}")

    # Create categories and channels
    existing_categories = {c.name: c for c in guild.categories}
    existing_channels = {c.name: c for c in guild.text_channels}

    for channel_name, cfg in CHANNEL_STRUCTURE.items():
        category_name = cfg["category"]
        access = cfg["access"]
        topic = cfg.get("topic", "")

        if category_name not in existing_categories:
            category = await guild.create_category(category_name)
            existing_categories[category_name] = category
            logger.info(f"Created category: {category_name}")
        else:
            category = existing_categories[category_name]

        if channel_name in existing_channels:
            continue

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=(access == "public"),
            ),
        }

        if access != "public":
            for role_name in access:
                role = roles.get(role_name)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True,
                    )

        await guild.create_text_channel(
            name=channel_name, category=category,
            topic=topic, overwrites=overwrites,
            reason="QuantDesk auto-setup",
        )
        logger.info(f"Created channel: {channel_name}")

    logger.info("Server setup complete!")


# ─── Role Management (called by webhook handler) ──────────

async def assign_role_to_member(discord_id: int, product_id: str) -> dict:
    """Assign the correct role based on which Whop product was purchased."""
    guild = get_guild()
    role_name = PRODUCT_ROLE_MAP.get(product_id)

    if not role_name:
        return {"success": False, "error": f"Unknown product: {product_id}"}

    role = get_role_by_name(guild, role_name)
    if not role:
        return {"success": False, "error": f"Role not found: {role_name}"}

    # Try to find member in server
    try:
        member = await guild.fetch_member(discord_id)
    except discord.NotFound:
        # Member hasn't joined yet — Whop will add them shortly
        # Queue the role assignment for when they arrive
        pending_roles[discord_id] = role_name
        logger.info(f"Member {discord_id} not in server yet — queued {role_name}")
        return {"success": True, "message": f"Queued {role_name} for {discord_id}"}
    except discord.HTTPException as e:
        return {"success": False, "error": f"Discord API error: {e}"}

    if role in member.roles:
        return {"success": True, "message": f"{member.name} already has {role_name}"}

    await member.add_roles(role, reason=f"Whop purchase: {product_id}")
    logger.info(f"Assigned {role_name} to {member.name}")

    await send_welcome_dm(member, role_name)
    return {"success": True, "message": f"Assigned {role_name} to {member.name}"}


async def remove_role_from_member(discord_id: int, product_id: str) -> dict:
    """Remove role when subscription ends."""
    guild = get_guild()
    role_name = PRODUCT_ROLE_MAP.get(product_id)

    if not role_name:
        return {"success": False, "error": f"Unknown product: {product_id}"}

    role = get_role_by_name(guild, role_name)
    if not role:
        return {"success": False, "error": f"Role not found: {role_name}"}

    # Clean up pending if exists
    pending_roles.pop(discord_id, None)

    try:
        member = await guild.fetch_member(discord_id)
    except discord.NotFound:
        return {"success": True, "message": "Member not in server"}
    except discord.HTTPException as e:
        return {"success": False, "error": f"Discord API error: {e}"}

    if role not in member.roles:
        return {"success": True, "message": f"{member.name} doesn't have {role_name}"}

    await member.remove_roles(role, reason=f"Whop subscription ended: {product_id}")
    logger.info(f"Removed {role_name} from {member.name}")

    try:
        await member.send(
            f"Your **{role_name}** subscription has ended. "
            f"Resubscribe anytime to regain access!"
        )
    except discord.Forbidden:
        pass

    return {"success": True, "message": f"Removed {role_name} from {member.name}"}


async def send_welcome_dm(member: discord.Member, role_name: str):
    strategy = "TMEM" if "TMEM" in role_name else "MEC"

    if strategy == "TMEM":
        signals_channel = "📊-tmem-signals"
        description = (
            "TMEM is our defensive momentum strategy. You'll receive daily "
            "risk-on/off signals and monthly top 30 stock picks."
        )
    else:
        signals_channel = "📊-mec-signals"
        description = (
            "MEC is our momentum + earnings confirmation strategy. You'll receive "
            "monthly top 40 stock picks with rebalancing notifications."
        )

    msg = (
        f"🎉 **Welcome to {strategy} Trading — Signals!**\n\n"
        f"{description}\n\n"
        f"**Getting started:**\n"
        f"• Head to #{signals_channel} for your signals\n"
        f"• Check out #📚-education for strategy deep-dives\n"
        f"• Join #💬-{strategy.lower()}-discussion to connect with other members\n\n"
        f"Happy investing! 📈"
    )

    try:
        await member.send(msg)
    except discord.Forbidden:
        logger.warning(f"Could not DM {member.name}")


# ─── Event: Member Joins ──────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
    """
    When a new member joins (via Whop), check if we have a
    pending role assignment and apply it.
    """
    if member.id in pending_roles:
        role_name = pending_roles.pop(member.id)
        guild = get_guild()
        role = get_role_by_name(guild, role_name)

        if role:
            # Small delay to let Whop finish its own setup
            await asyncio.sleep(2)
            await member.add_roles(role, reason="Pending Whop purchase")
            logger.info(f"Applied pending role {role_name} to {member.name}")
            await send_welcome_dm(member, role_name)


# ─── Bot Ready ────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"QuantDesk bot connected as {bot.user} (ID: {bot.user.id})")
    await setup_server()

    # Start signal bot
    from signal_bot import setup_signal_tasks
    setup_signal_tasks(bot, DISCORD_GUILD_ID)
    logger.info("Signal bot started!")

    # Start market analysis
    from market_analysis import post_daily_analysis
    from discord.ext import tasks
    from datetime import time as dtime

    @tasks.loop(time=dtime(hour=15, minute=0))  # 3:00 PM UTC = 10:00 AM ET
    async def daily_market_analysis():
        await post_daily_analysis(bot, DISCORD_GUILD_ID)

    @daily_market_analysis.before_loop
    async def before_market_analysis():
        await bot.wait_until_ready()
        logger.info("Market analysis task ready — will run daily at 15:00 UTC (10:00 AM ET)")

    daily_market_analysis.start()
    logger.info("Market analysis started!")

    # Start Q&A bot
    from qa_bot import setup_qa_bot
    setup_qa_bot(bot, DISCORD_GUILD_ID)
    logger.info("Q&A bot started!")

    logger.info("Ready!")


# ─── Admin Commands ───────────────────────────────────────

@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def cmd_setup(ctx):
    await ctx.send("⚙️ Running server setup...")
    await setup_server()
    await ctx.send("✅ Done!")


@bot.command(name="subscribers")
@commands.has_permissions(administrator=True)
async def cmd_subscribers(ctx):
    guild = get_guild()
    lines = ["📊 **Subscriber Counts:**\n"]
    for role_name in ROLE_COLORS:
        role = get_role_by_name(guild, role_name)
        count = len(role.members) if role else 0
        lines.append(f"• **{role_name}**: {count}")
    await ctx.send("\n".join(lines))


@bot.command(name="health")
@commands.has_permissions(administrator=True)
async def cmd_health(ctx):
    guild = get_guild()
    roles_ok = all(get_role_by_name(guild, r) for r in ROLE_COLORS)
    channels_ok = all(
        discord.utils.get(guild.text_channels, name=ch)
        for ch in CHANNEL_STRUCTURE
    )
    pending = len(pending_roles)

    await ctx.send(
        f"🤖 **QuantDesk Health Check**\n\n"
        f"• Discord: ✅ Connected\n"
        f"• Guild: {guild.name} ✅\n"
        f"• Roles: {'✅' if roles_ok else '⚠️ Some missing'}\n"
        f"• Channels: {'✅' if channels_ok else '⚠️ Some missing'}\n"
        f"• Pending role assignments: {pending}\n"
    )


@bot.command(name="market")
@commands.has_permissions(administrator=True)
async def cmd_market(ctx):
    """Force-run daily market analysis."""
    await ctx.send("⚙️ Running market analysis...")
    from market_analysis import post_daily_analysis
    await post_daily_analysis(bot, DISCORD_GUILD_ID)
    await ctx.send("✅ Market analysis posted!")
