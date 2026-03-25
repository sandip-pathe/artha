#!/usr/bin/env python3
"""Debug script to simulate incoming WhatsApp webhook and trace execution."""
import asyncio
import json
import sys
from app.db.session import SessionLocal
from app.main import process_message

async def debug_incoming_hii():
    """Simulate incoming HII message from your 8767 number."""
    phone = "918767394523"
    message_type = "text"
    text_body = "hii"
    
    print(f"\n{'='*60}")
    print(f"SIMULATING WEBHOOK: phone={phone}, type={message_type}, text='{text_body}'")
    print(f"{'='*60}\n")
    
    try:
        print("[1] Starting message processing...")
        task = asyncio.create_task(process_message(
            phone=phone,
            message_type=message_type,
            text_body=text_body,
            media_id=None,
        ))
        print("[2] Waiting for response (will call Meta API)...")
        await asyncio.wait_for(task, timeout=15)
        print("\n✅ process_message completed successfully")
    except asyncio.TimeoutError:
        print("\n✅ Message processing timed out (likely waiting on Meta API send, which is OK)")
        print("   The important part is that it got past the Google Vision import issue")
    except Exception as e:
        print(f"\n❌ ERROR in process_message: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_incoming_hii())
