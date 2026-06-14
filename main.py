import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ── credentials (hardcoded as requested) ─────────────────────────────────────
API_ID = 28350158
API_HASH = "01243eddcec18adbcb459907dd12f0d6"
SESSION = "1AZWarzgBu2Kbnsl_HiSjMY_Z9_bsSMf5QmthAz_aRL16dPPD7F02h1tlK4Lu0kHDzm1a4lgWLMh30CU4CvGNFyC6pAGw5uT55TjRuKc3Y0EAQWc0rvM3rH1Cuf52XNOCynyEPbyZhK4viBb0KIC-vjA1QoTEaMZ9qCuKfvFyQGZKmFS4pg4N6f3jzv-jhzhySf7Rwh88LkauYbwE8qzQyhuMhN9PzU4Oq-49JOGrqT6IYjfrWvCs0p9danh2qXtnxNmznSoavLQoBydT1BijA-U1jZVqH5lGStbfJevmqz_Io0zg1H4fCqFcMBikOHDy-wpO_pvfp0bakNeExF0AtA8dNuqbJhE="
BOT_USERNAME = "@VECHILE_INFO_BY_POLYX1_bot"

# ── shared state ──
# Queue stores tuples of (future, vehicle_no) for better matching
waiting: asyncio.Queue = asyncio.Queue()
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


def is_searching_message(text: str) -> bool:
    """Check if message is the initial 'Searching...' message"""
    return "Searching" in text or text.strip().startswith("Searching")


def is_final_message(text: str, vehicle_no: str) -> bool:
    """Check if this is the final vehicle information message"""
    return "VEHICLE INFORMATION" in text and vehicle_no in text


@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def on_bot_reply(event):
    """
    Handle bot replies - ignore searching messages,
    only resolve futures for final vehicle info messages.
    """
    message_text = event.message.text
    print(f"[BOT MESSAGE] {message_text[:100]}...")  # Print first 100 chars
    
    # Check if this is a searching message - ignore it
    if is_searching_message(message_text):
        print("[INFO] Ignoring 'Searching...' message")
        return
    
    # Try to match this message with a waiting request
    # We need to check each waiting future to see if this message matches their vehicle
    temp_queue = asyncio.Queue()
    matched = False
    
    while not waiting.empty():
        try:
            future, vehicle_no = await waiting.get()
            
            # Check if this message is the final response for this vehicle
            if not matched and is_final_message(message_text, vehicle_no):
                print(f"[MATCH] Found final response for vehicle: {vehicle_no}")
                if not future.done():
                    future.set_result(message_text)
                matched = True
                # Don't put this future back in queue
                continue
            else:
                # Put back other futures
                await temp_queue.put((future, vehicle_no))
        except asyncio.QueueEmpty:
            break
    
    # Restore unmatched futures
    while not temp_queue.empty():
        item = await temp_queue.get()
        await waiting.put(item)
    
    if not matched:
        print(f"[WARN] Could not match message to any waiting request")
        print(f"[WARN] Message preview: {message_text[:200]}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    print("Telegram client connected ✅")
    print(f"Listening for messages from {BOT_USERNAME}")
    yield
    await client.disconnect()


app = FastAPI(lifespan=lifespan)


async def lookup(vehicle_no: str) -> str:
    """
    Send to bot and wait for the final vehicle information message.
    Ignores the initial 'Searching...' message.
    """
    bot = await client.get_entity(BOT_USERNAME)
    future = asyncio.get_event_loop().create_future()
    
    # Store both future and vehicle number for matching
    await waiting.put((future, vehicle_no))
    
    # Send the search command
    await client.send_message(bot, f"/search {vehicle_no}")
    print(f"[REQUEST] Sent query for {vehicle_no}")

    try:
        # Wait for the final message (not the searching message)
        result = await asyncio.wait_for(future, timeout=30)
        print(f"[SUCCESS] Received final response for {vehicle_no}")
        return result
    except asyncio.TimeoutError:
        # Clean up: remove our specific future from queue
        temp_queue = asyncio.Queue()
        while not waiting.empty():
            item = await waiting.get()
            if item[0] != future:  # Keep other futures
                await temp_queue.put(item)
        
        # Restore remaining items
        while not temp_queue.empty():
            await waiting.put(await temp_queue.get())
        
        print(f"[ERROR] Timeout for vehicle {vehicle_no} - final message not received within 30 seconds")
        raise HTTPException(
            status_code=504, 
            detail=f"Bot did not return vehicle information for {vehicle_no} within 30 seconds"
        )
    except Exception as e:
        # Clean up on other errors
        temp_queue = asyncio.Queue()
        while not waiting.empty():
            item = await waiting.get()
            if item[0] != future:
                await temp_queue.put(item)
        
        while not temp_queue.empty():
            await waiting.put(await temp_queue.get())
        raise


# ── API Endpoints ────────────────────────────────────────────────────────────
@app.get("/vehicle/{vehicle_no}")
async def vehicle_lookup_get(vehicle_no: str):
    """GET endpoint: /vehicle/KA19ES2578"""
    result = await lookup(vehicle_no.strip().upper())
    return {"vehicle_no": vehicle_no, "result": result}


@app.post("/vehicle")
async def vehicle_lookup_post(data: dict):
    """POST endpoint: {"vehicle_no": "KA19ES2578"}"""
    vehicle_no = data.get("vehicle_no", "").strip().upper()
    if not vehicle_no:
        raise HTTPException(status_code=400, detail="vehicle_no is required")
    result = await lookup(vehicle_no)
    return {"vehicle_no": vehicle_no, "result": result}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok", 
        "client_connected": client.is_connected(),
        "queue_size": waiting.qsize()
    }


@app.get("/debug/queue")
async def debug_queue():
    """Debug endpoint to see pending requests"""
    pending = []
    temp_queue = asyncio.Queue()
    
    while not waiting.empty():
        future, vehicle_no = await waiting.get()
        pending.append({
            "vehicle_no": vehicle_no,
            "done": future.done()
        })
        await temp_queue.put((future, vehicle_no))
    
    while not temp_queue.empty():
        await waiting.put(await temp_queue.get())
    
    return {"pending_requests": pending}


# ── Run the server ──
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
