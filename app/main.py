from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError

from app.agent import run_artha_streaming
from app.db.bootstrap import ensure_artha_schema
from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.fraud.google_vision import extract_text
from app.metrics import metrics_store
from app.orchestration import run_langgraph_chat, stream_langgraph_chat
from app.realtime_ws import realtime_ws_handler
from app.sessions import (
    append_conversation_pair,
    get_or_create_session,
    get_session_context,
    update_session_context,
)
from app.voice import synthesize_voice, transcribe_voice

app = FastAPI(title="Artha")
logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

def _csv_env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]

_default_cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_configured_cors_origins = _csv_env_list("CORS_ALLOW_ORIGINS")
_cors_origin_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX", r"https://.*\.vercel\.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_cors_origins + _configured_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup() -> None:
    def _init_schema() -> None:
        Base.metadata.create_all(bind=engine)
        ensure_artha_schema(engine)

    try:
        await asyncio.wait_for(asyncio.to_thread(_init_schema), timeout=12)
    except asyncio.TimeoutError:
        logger.warning("Database schema initialization timed out; continuing startup")
    except Exception as exc:
        logger.warning("Database schema initialization skipped at startup: %s", exc)

@app.get("/api/context/{phone}")
async def api_get_context(phone: str):
    with SessionLocal() as db:
        session_context = get_session_context(db, phone)
        # Using dummy stats for now, pending deeper DB integration for stats
        return {
            "total_sales": 12500,
            "transactions": 14,
            "history": session_context.get("conversation_history", [])
        }

@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    mime_type = file.content_type
    transcript = await transcribe_voice(audio_bytes, mime_type)
    return {"transcript": transcript}

@app.post("/api/upload-image")
async def api_upload_image(file: UploadFile = File(...)):
    image_bytes = await file.read()
    extracted = await extract_text(image_bytes)
    return {"ocr_text": extracted}

@app.post("/api/chat")
async def api_chat(
    phone: str = Form(...),
    message: str = Form(...),
    input_type: str = Form("text"),
    ocr_text: str | None = Form(None)
):
    result = await run_langgraph_chat(
        phone=phone,
        message=message,
        input_type=input_type,
        ocr_text=ocr_text,
        session_id=phone,
    )

    with SessionLocal() as db:
        append_conversation_pair(db, phone, message, result.get("response_text", ""))

    return {
        "response_text": result.get("response_text"),
        "intent": result.get("intent"),
        "tools_called": result.get("tools_called", []),
        "node_timings_ms": result.get("node_timings_ms", {}),
        "cache_hit": result.get("cache_hit", False),
    }

class ChatStreamRequest(BaseModel):
    phone: str
    message: str
    input_type: str = "text"
    ocr_text: str | None = None

@app.post("/api/chat-stream")
async def api_chat_stream(req: ChatStreamRequest):
    async def event_generator():
        aggregated = ""
        async for event in stream_langgraph_chat(
            phone=req.phone,
            message=req.message,
            input_type=req.input_type,
            ocr_text=req.ocr_text,
            session_id=req.phone,
        ):
            if event.get("type") == "chunk":
                aggregated += event.get("content", "")
            elif event.get("type") == "error":
                content = event.get("content") or "Abhi system issue aa gaya. Ek baar phir try karo."
                aggregated += content
                event = {"type": "chunk", "content": content}
            yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"

        with SessionLocal() as db:
            append_conversation_pair(db, req.phone, req.message, aggregated.strip())

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.websocket("/api/realtime/ws")
async def api_realtime_ws(websocket: WebSocket):
    await realtime_ws_handler(websocket)

@app.post("/api/tts")
async def api_tts(text: str = Form(...)):
    audio = await synthesize_voice(text)
    if audio:
        return {"audio": base64.b64encode(audio).decode("utf-8")}
    return {"audio": None}

@app.get("/health")
async def health() -> dict:
    db_connected = False
    try:
        with SessionLocal() as db:
            db.execute(sql_text("SELECT 1"))
            db_connected = True
    except Exception:
        db_connected = False

    return {
        "status": "ok",
        "timestamp": datetime.now(IST).isoformat(),
        "db_connected": db_connected,
        "version": "Artha 1.0",
    }

@app.get("/metrics")
async def metrics(limit: int = 200) -> dict:
    records = await metrics_store.latest(limit=limit)
    return {"count": len(records), "records": records}

@app.get("/demo", response_class=HTMLResponse)
async def demo_page() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Artha Demo</title>
  <style>
    :root {
      --bg: #fff8ef;
      --ink: #20120a;
      --muted: #6b4b3a;
      --brand: #d66a1f;
      --brand-2: #b7872f;
      --card: #fff;
      --border: #efdfc9;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Noto Sans", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 10% 10%, #ffefdc, var(--bg));
    }
    .wrap { max-width: 920px; margin: 32px auto; padding: 0 18px; }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 26px;
      box-shadow: 0 10px 30px rgba(71, 34, 5, 0.08);
    }
    .pill {
      display: inline-block;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 7px 12px;
      border-radius: 999px;
      color: #7a3b06;
      border: 1px solid #f1c9a6;
      background: #fff1e3;
    }
    h1 {
      margin: 14px 0 8px;
      font-size: 42px;
      line-height: 1.05;
      color: var(--brand);
    }
    p { color: var(--muted); line-height: 1.6; }
    .grid {
      margin-top: 18px;
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .feature {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      background: #fffdfa;
    }
    .feature h3 { margin: 0 0 8px; color: var(--brand-2); }
    @media (max-width: 760px) {
      h1 { font-size: 32px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <section class="card">
      <span class="pill">Artha 1.0</span>
      <h1>Artha: AI Munshi for Kirana Shops</h1>
      <p>
        AI assistant for your web application.
      </p>
      <div class="grid">
        <article class="feature"><h3>Voice In, Voice Out</h3><p>Send voice note, Artha replies.</p></article>
        <article class="feature"><h3>Payment Verification</h3><p>OCR + DB lookup.</p></article>
        <article class="feature"><h3>Business Memory</h3><p>Tracks udhaar, expenses.</p></article>
      </div>
    </section>
  </main>
</body>
</html>
"""
