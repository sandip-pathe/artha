import json
import asyncio
import httpx

async def test_webhook():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "918767394523",
                        "id": "test-msg-001",
                        "type": "text",
                        "text": {"body": "hii"}
                    }]
                }
            }]
        }]
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://127.0.0.1:8010/webhook",
                json=payload,
                timeout=5
            )
            print(f"Response: {response.status_code}")
            print(f"Body: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test_webhook())
