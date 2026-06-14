import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ── credentials (use env vars in production) ──────────────────────────────────
API_ID   = os.getenv("API_ID",   "28350158")
API_HASH = os.getenv("API_HASH", "01243eddcec18adbcb459907dd12f0d6")
SESSION  = os.getenv("SESSION",  "1AZWarzgBu2Kbnsl_HiSjMY_Z9_bsSMf5QmthAz_aRL16dPPD7F02h1tlK4Lu0kHDzm1a4lgWLMh30CU4CvGNFyC6pAGw5uT55TjRuKc3Y0EAQWc0rvM3rH1Cuf52XNOCynyEPbyZhK4viBb0KIC-vjA1QoTEaMZ9qCuKfvFyQGZKmFS4pg4N6f3jzv-jhzhySf7Rwh88LkauYbwE8qzQyhuMhN9PzU4Oq-49JOGrqT6IYjfrWvCs0p9danh2qXtnxNmznSoavLQoBydT1BijA-U1jZVqH5lGStbfJevmqz_Io0zg1H4fCqFcMBikOHDy-wpO_pvfp0bakNeExF0AtA8dNuqbJhE=")

BOT_USERNAME = "@VECHILE_INFO_BY_POLYX1_bot"

# ── shared state ──────────────────────────────────────────────────────────────
pending: dict[int, asyncio.Future] = {}

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


# ── event handler: fires on every message received from the bot ───────────────
@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def on_bot_reply(event):
    msg      = event.message
    reply_to = getattr(msg.reply_to, "reply_to_msg_id", None)

    if reply_to and reply_to in pending:
        future = pending.pop(reply_to)
        if not future.done():
            future.set_result(msg.text)


# ── lifespan: start/stop Telethon with FastAPI ────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    print("Telegram client connected ✅")
    yield
    await client.disconnect()
    print("Telegram client disconnected")


app = FastAPI(lifespan=lifespan)


# ── endpoint ──────────────────────────────────────────────────────────────────
@app.post("/vehicle")
async def vehicle_lookup(data: dict):
    vehicle_no = data.get("vehicle_no", "").strip()
    if not vehicle_no:
        raise HTTPException(status_code=400, detail="vehicle_no is required")

    bot    = await client.get_entity(BOT_USERNAME)
    loop   = asyncio.get_event_loop()
    future = loop.create_future()

    # Register the future BEFORE sending to avoid missing a fast reply
    sent            = await client.send_message(bot, f"/search {vehicle_no}")
    pending[sent.id] = future

    try:
        result = await asyncio.wait_for(future, timeout=15)
    except asyncio.TimeoutError:
        pending.pop(sent.id, None)
        raise HTTPException(status_code=504, detail="Bot did not respond in time")

    return {"vehicle_no": vehicle_no, "result": result}
