#!/usr/bin/env python3
"""Trace complete message processing with error capture."""
import asyncio
import logging
from app.db.session import SessionLocal
from app.main import process_message

# Enable all logging to see what's happening
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(name)s: %(message)s')

async def debug_trace():
    """Simulate a complete inbound message flow."""
    phone = "918767394523"
    
    print(f"\n{'='*70}")
    print(f"TRACING: Incoming message from {phone}")
    print(f"{'='*70}\n")
    
    try:
        # Run the message processing
        print("[START] Processing message...")
        await asyncio.wait_for(
            process_message(
                phone=phone,
                message_type="text",
                text_body="hii",
                media_id=None,
            ),
            timeout=30
        )
        print("[DONE] Message processing completed")
    except asyncio.TimeoutError:
        print("[TIMEOUT] Message processing took >30 seconds")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_trace())
