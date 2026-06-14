import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events

API_ID = "28350158"
API_HASH = "01243eddcec18adbcb459907dd12f0d6"
BOT_USERNAME = "@VECHILE_INFO_BY_POLYX1_bot"

# Stores pending requests: { sent_message_id: asyncio.Future }
pending: dict[int, asyncio.Future] = {}

client = TelegramClient("session", API_ID, API_HASH)


@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def on_bot_reply(event):
    """
    Telethon fires this for every message the bot sends us.
    We match it to the pending request via reply_to_msg_id.
    """
    msg = event.message
    reply_to = getattr(msg.reply_to, "reply_to_msg_id", None)

    if reply_to and reply_to in pending:
        future = pending.pop(reply_to)
        if not future.done():
            future.set_result(msg.text)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    yield
    await client.disconnect()


app = FastAPI(lifespan=lifespan)


@app.post("/vehicle")
async def vehicle_lookup(data: dict):
    vehicle_no = data.get("vehicle_no", "").strip()
    if not vehicle_no:
        raise HTTPException(status_code=400, detail="vehicle_no is required")

    bot = await client.get_entity(BOT_USERNAME)

    # Create a Future BEFORE sending, so we never miss the reply
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

    # Send the message and get our sent message ID
    sent = await client.send_message(bot, f"/search {vehicle_no}")
    pending[sent.id] = future

    try:
        # Wait up to 15 seconds for the bot to reply to THIS message
        result = await asyncio.wait_for(future, timeout=15)
    except asyncio.TimeoutError:
        pending.pop(sent.id, None)
        raise HTTPException(status_code=504, detail="Bot did not respond in time")

    return {"vehicle_no": vehicle_no, "result": result}
