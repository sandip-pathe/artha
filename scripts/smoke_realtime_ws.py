import asyncio
import json

import websockets


async def main() -> None:
    uri = "ws://127.0.0.1:8010/api/realtime/ws?merchant_phone=918767394523&session_id=smoke-rt-1"
    async with websockets.connect(uri, max_size=2**20) as ws:
        warmup_done = False
        for _ in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                print(msg)
                if '"type":"response.done"' in msg.replace(" ", ""):
                    warmup_done = True
                    break
            except Exception as exc:
                print(f"recv_done: {exc}")
                break

        if not warmup_done:
            return

        await ws.send(
            json.dumps(
                {
                    "type": "response.create",
                    "response": {
                        "modalities": ["text"],
                        "instructions": "Reply with only: ok",
                    },
                }
            )
        )

        for _ in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=8)
                print(msg)
                if '"type":"response.done"' in msg.replace(" ", ""):
                    break
            except Exception as exc:
                print(f"recv_done: {exc}")
                break


if __name__ == "__main__":
    asyncio.run(main())
