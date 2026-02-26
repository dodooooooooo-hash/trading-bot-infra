"""
Whop Webhook Handler.
Listens for Whop payment events and tells QuantDesk bot which role to assign.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from config import WHOP_WEBHOOK_SECRET

logger = logging.getLogger(__name__)

app = FastAPI(title="QuantDesk Webhook Server")

# Subscription tracking (swap with DB for production)
subscriptions: dict[str, dict] = {}

# Discord bot reference — injected by main.py
discord_bot_ref = None


def set_discord_bot(bot_module):
    global discord_bot_ref
    discord_bot_ref = bot_module


# ─── Signature Verification ──────────────────────────────

def verify_whop_signature(payload: bytes, signature: str) -> bool:
    if not WHOP_WEBHOOK_SECRET:
        logger.warning("WHOP_WEBHOOK_SECRET not set — skipping verification!")
        return True
    expected = hmac.new(
        WHOP_WEBHOOK_SECRET.encode(), payload, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─── Payload Helpers ──────────────────────────────────────

def extract_discord_id(data: dict) -> int | None:
    user = data.get("data", {}).get("user", {})

    discord_id = user.get("discord", {}).get("id")
    if discord_id:
        return int(discord_id)

    for account in user.get("social_accounts", []):
        if account.get("service") == "discord":
            return int(account.get("id", 0))

    discord_id = data.get("data", {}).get("metadata", {}).get("discord_id")
    if discord_id:
        return int(discord_id)

    return None


def extract_product_id(data: dict) -> str | None:
    return data.get("data", {}).get("product_id")


def extract_membership_id(data: dict) -> str | None:
    return data.get("data", {}).get("id") or data.get("data", {}).get("membership_id")


# ─── Webhook Endpoint ────────────────────────────────────

@app.post("/webhooks/whop")
async def handle_whop_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("whop-signature", "")

    if not verify_whop_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("event")
    logger.info(f"Whop event: {event_type}")

    if event_type == "membership.went_valid":
        return await handle_new_subscription(payload)
    elif event_type == "membership.went_invalid":
        return await handle_subscription_ended(payload)
    elif event_type == "payment.succeeded":
        return await handle_payment_success(payload)
    elif event_type == "payment.failed":
        return await handle_payment_failed(payload)
    else:
        return {"status": "ignored", "event": event_type}


# ─── Event Handlers ──────────────────────────────────────

async def handle_new_subscription(payload: dict):
    """Someone bought TMEM or MEC — assign the correct role."""
    discord_id = extract_discord_id(payload)
    product_id = extract_product_id(payload)
    membership_id = extract_membership_id(payload)

    if not discord_id:
        logger.error(f"No Discord ID for membership {membership_id}")
        return {"status": "error", "message": "No Discord ID"}

    if not product_id:
        return {"status": "error", "message": "No product ID"}

    # Track it
    subscriptions[membership_id] = {
        "discord_id": discord_id,
        "product_id": product_id,
        "status": "active",
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Tell QuantDesk bot to assign the role
    if discord_bot_ref:
        result = await discord_bot_ref.assign_role_to_member(discord_id, product_id)
        return {"status": "processed", "result": result}
    return {"status": "error", "message": "Bot not ready"}


async def handle_subscription_ended(payload: dict):
    """Subscription cancelled — remove the role."""
    discord_id = extract_discord_id(payload)
    product_id = extract_product_id(payload)
    membership_id = extract_membership_id(payload)

    # Fallback to our records
    if (not discord_id or not product_id) and membership_id in subscriptions:
        sub = subscriptions[membership_id]
        discord_id = discord_id or sub.get("discord_id")
        product_id = product_id or sub.get("product_id")

    if not discord_id or not product_id:
        return {"status": "error", "message": "Missing data"}

    if membership_id in subscriptions:
        subscriptions[membership_id]["status"] = "cancelled"

    if discord_bot_ref:
        result = await discord_bot_ref.remove_role_from_member(discord_id, product_id)
        return {"status": "processed", "result": result}
    return {"status": "error", "message": "Bot not ready"}


async def handle_payment_success(payload: dict):
    membership_id = extract_membership_id(payload)
    if membership_id in subscriptions:
        sub = subscriptions[membership_id]
        sub["last_payment_at"] = datetime.now(timezone.utc).isoformat()
        sub.setdefault("payment_count", 0)
        sub["payment_count"] += 1
    return {"status": "logged"}


async def handle_payment_failed(payload: dict):
    membership_id = extract_membership_id(payload)
    discord_id = extract_discord_id(payload)
    logger.warning(f"Payment FAILED: {membership_id}")

    if discord_id and discord_bot_ref:
        try:
            guild = discord_bot_ref.get_guild()
            member = await guild.fetch_member(discord_id)
            await member.send(
                "⚠️ **Payment Issue**\n\n"
                "Your payment didn't go through. Please update your "
                "payment method on Whop to keep your access."
            )
        except Exception:
            pass

    return {"status": "logged"}


# ─── Endpoints ────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "bot_connected": discord_bot_ref is not None,
        "active_subs": sum(1 for s in subscriptions.values() if s.get("status") == "active"),
    }
