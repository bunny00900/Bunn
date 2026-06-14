import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Optional
import re

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ── credentials (hardcoded as requested) ─────────────────────────────────────
API_ID = 28350158
API_HASH = "01243eddcec18adbcb459907dd12f0d6"
SESSION = "1AZWarzgBu2Kbnsl_HiSjMY_Z9_bsSMf5QmthAz_aRL16dPPD7F02h1tlK4Lu0kHDzm1a4lgWLMh30CU4CvGNFyC6pAGw5uT55TjRuKc3Y0EAQWc0rvM3rH1Cuf52XNOCynyEPbyZhK4viBb0KIC-vjA1QoTEaMZ9qCuKfvFyQGZKmFS4pg4N6f3jzv-jhzhySf7Rwh88LkauYbwE8qzQyhuMhN9PzU4Oq-49JOGrqT6IYjfrWvCs0p9danh2qXtnxNmznSoavLQoBydT1BijA-U1jZVqH5lGStbfJevmqz_Io0zg1H4fCqFcMBikOHDy-wpO_pvfp0bakNeExF0AtA8dNuqbJhE="
BOT_USERNAME = "@VECHILE_INFO_BY_POLYX1_bot"

# ── shared state ──
# Dictionary to track pending requests: {vehicle_no: asyncio.Future}
pending_requests: Dict[str, asyncio.Future] = {}
# Lock to ensure thread-safe access to pending_requests
pending_lock = asyncio.Lock()

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


def extract_vehicle_number_from_message(text: str) -> Optional[str]:
    """Extract vehicle number from message text"""
    # Look for patterns like KA19ES2578, MH12DE1234, etc.
    # Indian vehicle number pattern: 2 letters, 2 digits, optional space, 1-2 letters, 4 digits
    pattern = r'([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})'
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def is_searching_message(text: str) -> bool:
    """Check if message is the initial 'Searching...' message"""
    return "Searching" in text and not ("VEHICLE INFORMATION" in text)


def is_final_message(text: str) -> bool:
    """Check if this is the final vehicle information message"""
    return "VEHICLE INFORMATION" in text


@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def on_bot_reply(event):
    """
    Handle ALL bot messages.
    Match messages to pending requests by extracting vehicle number from the message.
    """
    message_text = event.message.text
    message_id = event.message.id
    
    # Debug log - print full message
    print(f"\n{'='*60}")
    print(f"[BOT MESSAGE] ID: {message_id}")
    print(f"[BOT MESSAGE] Full text:")
    print(f"{message_text}")
    print(f"{'='*60}\n")
    
    # Ignore searching messages
    if is_searching_message(message_text):
        print(f"[INFO] Ignoring 'Searching' message (ID: {message_id})")
        return
    
    # Check if this is a final vehicle information message
    if is_final_message(message_text):
        print(f"[INFO] Received potential final message (ID: {message_id})")
        
        # Extract vehicle number from the message
        vehicle_no = extract_vehicle_number_from_message(message_text)
        
        if vehicle_no:
            print(f"[INFO] Extracted vehicle number: {vehicle_no}")
            
            # Check if there's a pending request for this vehicle
            async with pending_lock:
                future = pending_requests.get(vehicle_no)
            
            if future and not future.done():
                print(f"[MATCH] Found pending request for {vehicle_no}, resolving future")
                future.set_result(message_text)
            else:
                print(f"[WARN] No pending request found for vehicle: {vehicle_no}")
                print(f"[WARN] Current pending requests: {list(pending_requests.keys())}")
        else:
            print(f"[WARN] Could not extract vehicle number from message:")
            print(f"[WARN] {message_text[:200]}")
    else:
        print(f"[INFO] Message doesn't match final message pattern, ignoring")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    print("✅ Telegram client connected")
    print(f"👂 Listening for messages from {BOT_USERNAME}")
    print(f"📋 Pending requests tracker initialized")
    yield
    await client.disconnect()
    print("👋 Telegram client disconnected")


app = FastAPI(lifespan=lifespan)


async def lookup(vehicle_no: str) -> str:
    """
    Send request to bot and wait for the final vehicle information message.
    Uses vehicle number to match the response.
    """
    # Normalize vehicle number
    vehicle_no = vehicle_no.strip().upper()
    
    # Create a future for this request
    future = asyncio.get_event_loop().create_future()
    
    # Store the future in the pending requests dictionary
    async with pending_lock:
        if vehicle_no in pending_requests:
            # Should not happen with proper locking, but just in case
            print(f"[WARN] Request already pending for {vehicle_no}")
        pending_requests[vehicle_no] = future
    
    try:
        # Get bot entity and send message
        bot = await client.get_entity(BOT_USERNAME)
        await client.send_message(bot, f"/search {vehicle_no}")
        print(f"[REQUEST] Sent query for {vehicle_no} at {asyncio.get_event_loop().time():.2f}")
        
        # Wait for the future to be resolved by the message handler
        # Timeout after 30 seconds
        result = await asyncio.wait_for(future, timeout=30.0)
        print(f"[SUCCESS] Received final response for {vehicle_no}")
        return result
        
    except asyncio.TimeoutError:
        print(f"[ERROR] Timeout for vehicle {vehicle_no} after 30 seconds")
        raise HTTPException(
            status_code=504,
            detail=f"Bot did not return vehicle information for {vehicle_no} within 30 seconds"
        )
    except Exception as e:
        print(f"[ERROR] Exception in lookup for {vehicle_no}: {type(e).__name__}: {e}")
        raise
    finally:
        # Clean up: remove the future from pending requests
        async with pending_lock:
            if vehicle_no in pending_requests:
                del pending_requests[vehicle_no]
                print(f"[CLEANUP] Removed {vehicle_no} from pending requests")


# ── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/vehicle/{vehicle_no}")
async def vehicle_lookup_get(vehicle_no: str):
    """GET endpoint: /vehicle/KA19ES2578"""
    result = await lookup(vehicle_no)
    return {
        "vehicle_no": vehicle_no,
        "result": result,
        "status": "success"
    }


@app.post("/vehicle")
async def vehicle_lookup_post(data: dict):
    """POST endpoint: {\"vehicle_no\": \"KA19ES2578\"}"""
    vehicle_no = data.get("vehicle_no", "").strip().upper()
    if not vehicle_no:
        raise HTTPException(status_code=400, detail="vehicle_no is required")
    result = await lookup(vehicle_no)
    return {
        "vehicle_no": vehicle_no,
        "result": result,
        "status": "success"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    async with pending_lock:
        pending_count = len(pending_requests)
        pending_vehicles = list(pending_requests.keys())
    
    return {
        "status": "ok",
        "client_connected": client.is_connected(),
        "pending_requests_count": pending_count,
        "pending_vehicles": pending_vehicles,
        "is_connected": client.is_connected()
    }


@app.get("/debug/pending")
async def debug_pending():
    """Debug endpoint to see all pending requests"""
    async with pending_lock:
        pending = [
            {
                "vehicle_no": vno,
                "done": future.done(),
                "cancelled": future.cancelled()
            }
            for vno, future in pending_requests.items()
        ]
    
    return {
        "total_pending": len(pending),
        "pending_requests": pending
    }


@app.post("/debug/clear")
async def debug_clear():
    """Debug endpoint to clear all pending requests (use carefully!)"""
    async with pending_lock:
        count = len(pending_requests)
        for vehicle_no, future in pending_requests.items():
            if not future.done():
                future.cancel()
        pending_requests.clear()
    
    return {
        "message": f"Cleared {count} pending requests",
        "status": "success"
    }


# ── Run the server ──
if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting FastAPI server...")
    print(f"📡 Bot username: {BOT_USERNAME}")
    print("📍 API endpoints:")
    print("   GET  /vehicle/{vehicle_no}")
    print("   POST /vehicle")
    print("   GET  /health")
    print("   GET  /debug/pending")
    print("   POST /debug/clear")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
