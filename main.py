import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ── credentials ───────────────────────────────────────────────────────────────
API_ID   = os.getenv("API_ID",   "28350158")
API_HASH = os.getenv("API_HASH", "01243eddcec18adbcb459907dd12f0d6")
SESSION  = os.getenv("SESSION",  "1AZWarzgBu2Kbnsl_HiSjMY_Z9_bsSMf5QmthAz_aRL16dPPD7F02h1tlK4Lu0kHDzm1a4lgWLMh30CU4CvGNFyC6pAGw5uT55TjRuKc3Y0EAQWc0rvM3rH1Cuf52XNOCynyEPbyZhK4viBb0KIC-vjA1QoTEaMZ9qCuKfvFyQGZKmFS4pg4N6f3jzv-jhzhySf7Rwh88LkauYbwE8qzQyhuMhN9PzU4Oq-49JOGrqT6IYjfrWvCs0p9danh2qXtnxNmznSoavLQoBydT1BijA-U1jZVqH5lGStbfJevmqz_Io0zg1H4fCqFcMBikOHDy-wpO_pvfp0bakNeExF0AtA8dNuqbJhE=")

BOT_USERNAME = "@VECHILE_INFO_BY_POLYX1_bot"

# ── shared state ──────────────────────────────────────────────────────────────
# Queue of futures waiting for the next bot message (FIFO)
waiting: asyncio.Queue = asyncio.Queue()

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def on_bot_reply(event):
    """
    Called for EVERY message from the bot — whether it replies or not.
    We resolve the oldest waiting future (FIFO queue).
    """
    print(f"[BOT MESSAGE] {event.message.text}")
    try:
        future = waiting.get_nowait()
        if not future.done():
            future.set_result(event.message.text)
    except asyncio.QueueEmpty:
        print("[WARN] Got bot message but no request was waiting")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    print("Telegram client connected ✅")
    yield
    await client.disconnect()


app = FastAPI(lifespan=lifespan)


async def lookup(vehicle_no: str) -> str:
    """Send to bot and wait for its next message."""
    bot    = await client.get_entity(BOT_USERNAME)
    future = asyncio.get_event_loop().create_future()

    # Enqueue BEFORE sending so we never miss a fast reply
    await waiting.put(future)
    await client.send_message(bot, f"/search {vehicle_no}")

    try:
        return await asyncio.wait_for(future, timeout=20)
    except asyncio.TimeoutError:
        # Remove our future from queue if still there
        try:
            waiting.get_nowait()
        except asyncio.QueueEmpty:
            pass
        raise HTTPException(status_code=504, detail="Bot did not respond in time")


# ── GET /vehicle/KA19ES2578 ───────────────────────────────────────────────────
@app.get("/vehicle/{vehicle_no}")
async def vehicle_lookup_get(vehicle_no: str):
    result = await lookup(vehicle_no.strip().upper())
    return {"vehicle_no": vehicle_no, "result": result}


# ── POST /vehicle  { "vehicle_no": "KA19ES2578" } ────────────────────────────
@app.post("/vehicle")
async def vehicle_lookup_post(data: dict):
    vehicle_no = data.get("vehicle_no", "").strip().upper()
    if not vehicle_no:
        raise HTTPException(status_code=400, detail="vehicle_no is required")
    result = await lookup(vehicle_no)
    return {"vehicle_no": vehicle_no, "result": result}
