import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ── credentials (ONLY from environment!) ──
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION")
BOT_USERNAME = os.getenv("BOT_USERNAME", "@VECHILE_INFO_BY_POLYX1_bot")

# Validate required credentials
if not all([API_ID, API_HASH, SESSION]):
    raise ValueError("Missing required environment variables: API_ID, API_HASH, SESSION")

# ── shared state ──
waiting: asyncio.Queue = asyncio.Queue()
client = TelegramClient(StringSession(SESSION), int(API_ID), API_HASH)


@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def on_bot_reply(event):
    """Handle bot replies - resolve oldest waiting future."""
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
    """Send to bot and wait for its response."""
    bot = await client.get_entity(BOT_USERNAME)
    future = asyncio.get_event_loop().create_future()
    
    # Store tuple (future, vehicle_no) for better debugging
    queue_item = (future, vehicle_no)
    await waiting.put(queue_item)
    
    await client.send_message(bot, f"/search {vehicle_no}")
    print(f"[REQUEST] Sent query for {vehicle_no}")

    try:
        result = await asyncio.wait_for(future, timeout=30)
        return result
    except asyncio.TimeoutError:
        # Clean up: remove our specific item from queue
        temp_queue = asyncio.Queue()
        removed = False
        while not waiting.empty():
            item = await waiting.get()
            if not removed and item[0] == future:
                removed = True
                continue
            await temp_queue.put(item)
        
        # Restore remaining items
        while not temp_queue.empty():
            await waiting.put(await temp_queue.get())
        
        print(f"[ERROR] Timeout for vehicle {vehicle_no}")
        raise HTTPException(status_code=504, detail=f"Bot did not respond for {vehicle_no} within 30 seconds")


# ── API Endpoints ──
@app.get("/vehicle/{vehicle_no}")
async def vehicle_lookup_get(vehicle_no: str):
    result = await lookup(vehicle_no.strip().upper())
    return {"vehicle_no": vehicle_no, "result": result}


@app.post("/vehicle")
async def vehicle_lookup_post(data: dict):
    vehicle_no = data.get("vehicle_no", "").strip().upper()
    if not vehicle_no:
        raise HTTPException(status_code=400, detail="vehicle_no is required")
    result = await lookup(vehicle_no)
    return {"vehicle_no": vehicle_no, "result": result}


@app.get("/health")
async def health_check():
    """Health endpoint to verify service status."""
    return {"status": "ok", "client_connected": client.is_connected()}
