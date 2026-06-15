import asyncio
import re
from contextlib import asynccontextmanager
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ── credentials (hardcoded as requested) ─────────────────────────────────────
API_ID = 28350158
API_HASH = "01243eddcec18adbcb459907dd12f0d6"
SESSION = "1AZWarzgBuyG0HT2U3-Ae5L93hAI7_xb9QVvD0ME9dG35io2Q_3SkOIGCBmcQoiJiPkIDcLzO2AdNPrd2HTG9JA_42FsrkgJ-izGGKE4JXUa1885uZdTrMJU61G-PR3iVbkneKLUpxOWfDaAs8Z4Hr5iZ2Hv6j7qssmduZbuJjApOGmj5fF3I1x8x4EF7y-nMpqeCLHFdgWP4SqQmIJP_Fm6Y_VEoOkcdgEGam6t3dChomR1ndbIFWVvLX-wHWDlNxwDhFnKI-E_gYdI5yT_1BjhYmie3lKYKeUT60rfeIVKQpn_Nq1d8_1AXz6AO5gaRmxPUId20PbIl4L4IYRTB41V2iQgjJi0="
BOT_USERNAME = "@VECHILE_INFO_BY_POLYX1_bot"

# ── shared state ──
# Dictionary to track pending requests: {vehicle_no: asyncio.Future}
pending_requests: Dict[str, asyncio.Future] = {}
# Dictionary to track message IDs for debugging
message_tracker: Dict[int, Dict] = {}
# Lock to ensure thread-safe access to pending_requests
pending_lock = asyncio.Lock()

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


def extract_vehicle_number_from_message(text: str) -> Optional[str]:
    """Extract vehicle number from message text"""
    # Indian vehicle number pattern: 2 letters, 2 digits, optional space, 1-2 letters, 4 digits
    pattern = r'([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})'
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def is_temporary_message(text: str) -> bool:
    """Check if message is a temporary/status message"""
    temp_patterns = [
        r'Searching\s+',
        r'Processing\s+',
        r'Please wait',
        r'Fetching',
        r'Loading',
        r'Checking',
        r'\.\.\.$'  # Ends with ellipsis
    ]
    
    text_lower = text.lower()
    for pattern in temp_patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def is_final_message(text: str, vehicle_no: str = None) -> bool:
    """Check if this is the final vehicle information message"""
    # Check for VEHICLE INFORMATION keyword
    if "VEHICLE INFORMATION" in text:
        return True
    
    # If we have a specific vehicle number, check if it appears with substantial content
    if vehicle_no and vehicle_no in text:
        # Check if message has substantial content (more than just the vehicle number)
        words = text.split()
        if len(words) > 5:  # Arbitrary threshold for meaningful content
            return True
    
    return False


async def resolve_pending_request(vehicle_no: str, message_text: str):
    """Resolve a pending request for a vehicle"""
    async with pending_lock:
        future = pending_requests.get(vehicle_no)
        if future and not future.done():
            print(f"[MATCH] ✓ Resolving pending request for {vehicle_no}")
            future.set_result(message_text)
            return True
        else:
            print(f"[WARN] No pending request found for {vehicle_no}")
            return False


@client.on(events.NewMessage(from_users=BOT_USERNAME))
async def on_new_message(event):
    """Handle new messages from bot"""
    message_text = event.message.text
    message_id = event.message.id
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    # Store message info for debugging
    message_tracker[message_id] = {
        'type': 'NEW',
        'text': message_text[:200],
        'timestamp': timestamp,
        'vehicle_no': extract_vehicle_number_from_message(message_text)
    }
    
    print(f"\n{'='*70}")
    print(f"[NEW MESSAGE] ID: {message_id} | Time: {timestamp}")
    print(f"[CONTENT] {message_text[:300]}{'...' if len(message_text) > 300 else ''}")
    print(f"{'='*70}\n")
    
    # Check if it's a temporary message
    if is_temporary_message(message_text):
        print(f"[INFO] ⏳ Ignoring temporary message (ID: {message_id})")
        extracted_no = extract_vehicle_number_from_message(message_text)
        if extracted_no:
            print(f"[INFO] Temporary message for vehicle: {extracted_no}")
        return
    
    # Check if it's a final message
    vehicle_no = extract_vehicle_number_from_message(message_text)
    
    if vehicle_no and is_final_message(message_text, vehicle_no):
        print(f"[FINAL VEHICLE DATA FOUND] 🎯 Vehicle: {vehicle_no}")
        print(f"[FINAL DATA] {message_text[:500]}")
        
        await resolve_pending_request(vehicle_no, message_text)
    else:
        print(f"[INFO] No vehicle number found or not final message")


@client.on(events.MessageEdited(from_users=BOT_USERNAME))
async def on_edit_message(event):
    """Handle edited messages from bot (crucial for bots that update messages)"""
    message_text = event.message.text
    message_id = event.message.id
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    edit_version = message_tracker.get(message_id, {}).get('edit_count', 0) + 1
    
    # Store or update message info
    if message_id not in message_tracker:
        message_tracker[message_id] = {}
    
    message_tracker[message_id].update({
        'type': 'EDITED',
        'text': message_text[:200],
        'timestamp': timestamp,
        'edit_count': edit_version,
        'vehicle_no': extract_vehicle_number_from_message(message_text)
    })
    
    print(f"\n{'='*70}")
    print(f"[EDITED MESSAGE] ID: {message_id} | Version: {edit_version} | Time: {timestamp}")
    print(f"[CONTENT] {message_text[:300]}{'...' if len(message_text) > 300 else ''}")
    print(f"{'='*70}\n")
    
    # Check if it's a temporary message (should ignore even if edited)
    if is_temporary_message(message_text):
        print(f"[INFO] ⏳ Ignoring temporary edited message (ID: {message_id})")
        return
    
    # Check for final vehicle information
    vehicle_no = extract_vehicle_number_from_message(message_text)
    
    if vehicle_no and is_final_message(message_text, vehicle_no):
        print(f"[FINAL VEHICLE DATA FOUND] 🎯 Vehicle: {vehicle_no} (via EDIT)")
        print(f"[FINAL DATA] {message_text[:500]}")
        
        await resolve_pending_request(vehicle_no, message_text)
    else:
        # Log if this might be a transition to final state
        if vehicle_no:
            print(f"[INFO] Edited message for {vehicle_no} but not final yet")
            print(f"[INFO] Message length: {len(message_text)} chars")
            print(f"[INFO] Contains 'VEHICLE INFORMATION': {'VEHICLE INFORMATION' in message_text}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    print("\n" + "="*70)
    print("✅ Telegram client connected successfully")
    print(f"👂 Listening for messages from {BOT_USERNAME}")
    print(f"📋 Tracking both NEW and EDITED messages")
    print(f"🔍 Vehicle number regex pattern enabled")
    print("="*70 + "\n")
    yield
    await client.disconnect()
    print("\n👋 Telegram client disconnected")


app = FastAPI(lifespan=lifespan)


async def lookup(vehicle_no: str) -> str:
    """
    Send request to bot and wait for the final vehicle information message.
    Handles both new messages and edited messages.
    """
    # Normalize vehicle number
    vehicle_no = vehicle_no.strip().upper()
    
    # Create a future for this request
    future = asyncio.get_event_loop().create_future()
    
    # Store the future in the pending requests dictionary
    async with pending_lock:
        if vehicle_no in pending_requests:
            print(f"[WARN] Request already pending for {vehicle_no}, replacing")
        pending_requests[vehicle_no] = future
        print(f"[TRACK] Added {vehicle_no} to pending requests (Total: {len(pending_requests)})")
    
    try:
        # Get bot entity and send message
        bot = await client.get_entity(BOT_USERNAME)
        await client.send_message(bot, f"/search {vehicle_no}")
        print(f"\n[REQUEST] 📤 Sent query for {vehicle_no} at {datetime.now().strftime('%H:%M:%S')}")
        
        # Wait for the future to be resolved by either new message or edit handler
        result = await asyncio.wait_for(future, timeout=30.0)
        print(f"[SUCCESS] ✅ Received final response for {vehicle_no}")
        return result
        
    except asyncio.TimeoutError:
        print(f"[ERROR] ⏰ Timeout for vehicle {vehicle_no} after 30 seconds")
        print(f"[ERROR] No final message received (checked both NEW and EDITED messages)")
        raise HTTPException(
            status_code=504,
            detail=f"Bot did not return vehicle information for {vehicle_no} within 30 seconds"
        )
    except Exception as e:
        print(f"[ERROR] ❌ Exception in lookup for {vehicle_no}: {type(e).__name__}: {e}")
        raise
    finally:
        # Clean up: remove the future from pending requests
        async with pending_lock:
            if vehicle_no in pending_requests:
                del pending_requests[vehicle_no]
                print(f"[CLEANUP] 🧹 Removed {vehicle_no} from pending requests (Remaining: {len(pending_requests)})")


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
        "tracked_messages": len(message_tracker),
        "listening_for": "NEW and EDITED messages"
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


@app.get("/debug/messages")
async def debug_messages(limit: int = 10):
    """Debug endpoint to see recent bot messages"""
    recent_messages = list(message_tracker.items())[-limit:]
    return {
        "recent_messages": [
            {
                "message_id": msg_id,
                "type": data.get('type'),
                "vehicle_no": data.get('vehicle_no'),
                "text_preview": data.get('text', '')[:100],
                "timestamp": data.get('timestamp'),
                "edit_count": data.get('edit_count', 1)
            }
            for msg_id, data in recent_messages
        ]
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
    
    message_tracker.clear()
    
    return {
        "message": f"Cleared {count} pending requests and message tracker",
        "status": "success"
    }


# ── Run the server ──
if __name__ == "__main__":
    import uvicorn
    print("\n" + "🚀"*35)
    print("🚀 STARTING VEHICLE LOOKUP API SERVICE")
    print("🚀"*35)
    print(f"📡 Bot username: {BOT_USERNAME}")
    print(f"🔧 Features:")
    print(f"   • NEW message handling: ✓")
    print(f"   • EDITED message handling: ✓")
    print(f"   • Concurrent requests: ✓")
    print(f"   • Vehicle number extraction: ✓")
    print(f"   • Temporary message filtering: ✓")
    print(f"\n📍 API Endpoints:")
    print(f"   GET  /vehicle/{{vehicle_no}}")
    print(f"   POST /vehicle")
    print(f"   GET  /health")
    print(f"   GET  /debug/pending")
    print(f"   GET  /debug/messages")
    print(f"   POST /debug/clear")
    print("\n" + "="*70 + "\n")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000, 
        log_level="info",
        access_log=True
    )
