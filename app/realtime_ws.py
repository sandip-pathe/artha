from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from sqlalchemy import select

from app.agent import TOOLS, execute_tool
from app.db.models import Merchants
from app.db.session import SessionLocal
from app.metrics import metrics_store

logger = logging.getLogger(__name__)


def _resolve_merchant_id(phone: str) -> int | None:
    with SessionLocal() as db:
        merchant = db.scalar(select(Merchants).where(Merchants.phone == phone))
        if merchant:
            return int(merchant.id)
        fallback = db.scalar(select(Merchants).order_by(Merchants.id).limit(1))
        return int(fallback.id) if fallback else None


async def _execute_tool_call(merchant_id: int, tool_name: str, args_json: str) -> str:
    try:
        args = json.loads(args_json or "{}")
    except Exception:
        args = {}

    def _run() -> dict[str, Any]:
        with SessionLocal() as db:
            return execute_tool(tool_name, args, db, merchant_id)

    result = await asyncio.to_thread(_run)
    return json.dumps(result, ensure_ascii=True)


def _realtime_tools_spec() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for t in TOOLS:
        fn = t.get("function") or {}
        specs.append(
            {
                "type": "function",
                "name": fn.get("name"),
                "description": fn.get("description"),
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return specs


async def realtime_ws_handler(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id = websocket.query_params.get("session_id") or f"ws-{int(time.time() * 1000)}"
    merchant_phone = websocket.query_params.get("merchant_phone") or ""

    merchant_id = _resolve_merchant_id(merchant_phone)
    if not merchant_id:
        await websocket.send_json({"type": "error", "message": "merchant_not_found"})
        await websocket.close(code=1011)
        return

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_key:
        await websocket.send_json({"type": "error", "message": "openai_key_missing"})
        await websocket.close(code=1011)
        return

    model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
    ws_url = f"wss://api.openai.com/v1/realtime?model={model}"
    headers = {
        "Authorization": f"Bearer {openai_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    active_request_started_at: float | None = None
    function_call_buffers: dict[str, dict[str, str]] = defaultdict(lambda: {"name": "", "args": ""})

    async with websockets.connect(ws_url, additional_headers=headers, ping_interval=20, ping_timeout=20) as oai_ws:
        # Session update with native function-calling specs.
        await oai_ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "instructions": "You are Artha. Use tools whenever business data is needed.",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "silence_duration_ms": 350,
                        },
                        "tools": _realtime_tools_spec(),
                        "tool_choice": "auto",
                    },
                }
            )
        )

        # Warm-up for lower first-token latency.
        await oai_ws.send(
            json.dumps(
                {
                    "type": "response.create",
                    "response": {
                        "modalities": ["text"],
                        "instructions": "Reply with one word: ready",
                    },
                }
            )
        )

        async def client_to_openai() -> None:
            nonlocal active_request_started_at
            try:
                while True:
                    msg = await websocket.receive_text()
                    payload = json.loads(msg)
                    ptype = payload.get("type")

                    if ptype == "interrupt":
                        await oai_ws.send(json.dumps({"type": "response.cancel"}))
                        continue

                    if ptype in {"input_audio_buffer.commit", "response.create"}:
                        active_request_started_at = time.perf_counter()

                    await oai_ws.send(json.dumps(payload))
            except WebSocketDisconnect:
                try:
                    await oai_ws.close()
                except Exception:
                    pass

        async def _safe_send_to_client(message: str) -> bool:
            if websocket.client_state != WebSocketState.CONNECTED:
                return False
            try:
                await websocket.send_text(message)
                return True
            except Exception:
                return False

        async def openai_to_client() -> None:
            nonlocal active_request_started_at
            async for raw in oai_ws:
                try:
                    event = json.loads(raw)
                except Exception:
                    continue

                etype = event.get("type")

                # Function calling in Realtime API: assemble args delta chunks.
                if etype == "response.function_call_arguments.delta":
                    call_id = str(event.get("call_id") or "")
                    if call_id:
                        function_call_buffers[call_id]["name"] = str(event.get("name") or function_call_buffers[call_id]["name"])
                        function_call_buffers[call_id]["args"] += str(event.get("delta") or "")
                    if isinstance(raw, bytes):
                        outbound = raw.decode("utf-8", errors="ignore")
                    else:
                        outbound = str(raw)
                    if not await _safe_send_to_client(outbound):
                        break
                    continue

                if etype == "response.function_call_arguments.done":
                    call_id = str(event.get("call_id") or "")
                    call_name = str(event.get("name") or function_call_buffers[call_id]["name"])
                    call_args = str(event.get("arguments") or function_call_buffers[call_id]["args"])

                    output = await _execute_tool_call(merchant_id=merchant_id, tool_name=call_name, args_json=call_args)

                    await oai_ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": output,
                                },
                            }
                        )
                    )
                    await oai_ws.send(json.dumps({"type": "response.create"}))
                    if isinstance(raw, bytes):
                        outbound = raw.decode("utf-8", errors="ignore")
                    else:
                        outbound = str(raw)
                    if not await _safe_send_to_client(outbound):
                        break
                    continue

                # Fallback parser: some responses carry complete function call in output item done.
                if etype == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        call_id = str(item.get("call_id") or "")
                        call_name = str(item.get("name") or "")
                        call_args = str(item.get("arguments") or "{}")
                        output = await _execute_tool_call(merchant_id=merchant_id, tool_name=call_name, args_json=call_args)
                        await oai_ws.send(
                            json.dumps(
                                {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": output,
                                    },
                                }
                            )
                        )
                        await oai_ws.send(json.dumps({"type": "response.create"}))

                if etype == "response.done" and active_request_started_at is not None:
                    latency_ms = round((time.perf_counter() - active_request_started_at) * 1000, 2)
                    await metrics_store.record(
                        {
                            "session_id": session_id,
                            "pipeline_used": "realtime",
                            "total_latency_ms": latency_ms,
                        }
                    )
                    active_request_started_at = None

                if isinstance(raw, bytes):
                    outbound = raw.decode("utf-8", errors="ignore")
                else:
                    outbound = str(raw)
                if not await _safe_send_to_client(outbound):
                    break

        await asyncio.gather(client_to_openai(), openai_to_client())
