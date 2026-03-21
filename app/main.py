from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError

from app.agent import run_artha, search_payment
from app.db.bootstrap import ensure_artha_schema
from app.db.models import Base, ProcessedWebhookMessages
from app.db.session import SessionLocal, engine
from app.fraud.google_vision import extract_text
from app.sessions import (
    append_conversation_pair,
    get_or_create_session,
    get_pending_recheck,
    get_session_context,
    set_pending_recheck,
    update_session_context,
)
from app.voice import should_reply_with_voice, synthesize_voice, transcribe_voice
from app.whatsapp import (
    download_media,
    send_message,
    send_voice_message,
)

app = FastAPI(title="Artha")
logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


@app.on_event("startup")
async def on_startup() -> None:
    try:
        ensure_artha_schema(engine)
        Base.metadata.create_all(bind=engine)
    except Exception:
        logger.exception("Database schema initialization skipped at startup")


async def _safe_send_message(phone: str, text: str) -> None:
    try:
        await send_message(phone, text)
    except Exception:
        logger.exception("Failed to send WhatsApp text reply")


async def _safe_send_voice(phone: str, text: str) -> None:
    audio = await synthesize_voice(text)
    if not audio:
        await _safe_send_message(phone, text)
        return
    try:
        await send_voice_message(phone, audio)
    except Exception:
        logger.exception("Failed to send WhatsApp voice reply")
        await _safe_send_message(phone, text)


def _extract_message(payload: dict) -> dict | None:
    try:
        return payload["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return None


def _extract_message_type_data(message: dict) -> tuple[str, str | None, str | None]:
    message_type = message.get("type", "")
    if message_type == "text":
        return "text", (message.get("text") or {}).get("body", ""), None
    if message_type == "button":
        button_text = (message.get("button") or {}).get("text", "")
        button_payload = (message.get("button") or {}).get("payload", "")
        merged = button_text.strip() or button_payload.strip()
        return "text", merged, None
    if message_type == "audio":
        return "audio", None, (message.get("audio") or {}).get("id")
    if message_type == "image":
        return "image", None, (message.get("image") or {}).get("id")
    if message_type == "document":
        doc = message.get("document") or {}
        caption = doc.get("caption", "")
        media_id = doc.get("id")
        return "document", caption, media_id
    if message_type == "video":
        return "video", None, (message.get("video") or {}).get("id")
    if message_type == "location":
        return "location", "", None
    return message_type, "", None




def _should_send_morning_brief(last_message_date: str | None, now: datetime) -> bool:
    is_morning_window = 5 <= now.hour <= 10
    today_str = now.date().isoformat()
    is_first_message_today = last_message_date != today_str
    return is_first_message_today and is_morning_window


def _register_inbound_message_id(message_id: str | None, phone: str | None) -> bool:
    if not message_id:
        return True
    with SessionLocal() as db:
        entry = ProcessedWebhookMessages(message_id=message_id, phone=phone)
        db.add(entry)
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False


async def _send_output(phone: str, input_type: str, intent: str, response_text: str) -> None:
    output_mode = should_reply_with_voice(input_type=input_type, response_text=response_text, intent=intent)

    if output_mode == "voice":
        await _safe_send_voice(phone, response_text)
        return

    if output_mode == "both":
        await _safe_send_voice(phone, response_text)
        await _safe_send_message(phone, response_text)
        return

    await _safe_send_message(phone, response_text)


async def _schedule_payment_recheck(phone: str, txn_ref: str, amount: float | None) -> None:
    await asyncio.sleep(90)
    with SessionLocal() as db:
        pending = get_pending_recheck(db, phone)
        if not pending:
            return
        if pending.get("txn_ref") != txn_ref:
            return
        result = await search_payment(db, phone, txn_ref, amount)
        if result.get("found"):
            await _safe_send_message(
                phone,
                "✅ Update: Re-check complete. Payment ab record mein dikh raha hai. Maal de sakte ho.",
            )
        else:
            await _safe_send_message(
                phone,
                "❌ Update: 90 second re-check ke baad bhi payment record nahi mila. Customer se live UPI confirmation maango.",
            )
        set_pending_recheck(db, phone, None)


def _launch_background_task(coro) -> None:
    task = asyncio.create_task(coro)

    def _consume_result(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except Exception:
            logger.exception("Background task failed")

    task.add_done_callback(_consume_result)


async def process_message(
    phone: str,
    message_type: str,
    text_body: str | None = None,
    media_id: str | None = None,
) -> None:
    now = datetime.now(IST)
    current_hour = now.hour
    is_evening = current_hour >= 19

    with SessionLocal() as db:
        get_or_create_session(db, phone)
        session_context = get_session_context(db, phone)

        last_message_date = session_context.get("last_message_date")
        today_str = now.date().isoformat()
        is_morning_brief = _should_send_morning_brief(last_message_date=last_message_date, now=now)

        input_text = text_body or ""
        input_type = "text"
        ocr_text = None

        if message_type == "text":
            pass

        elif message_type == "audio":
            input_type = "voice"
            await _safe_send_message(phone, "🎙️ Sun raha hoon...")
            if not media_id:
                await _safe_send_message(phone, "Audio media missing tha. Dobara bhejo.")
                return
            audio_bytes, mime_type = await download_media(media_id)
            transcript = await transcribe_voice(audio_bytes, mime_type)
            if not transcript:
                await _safe_send_message(phone, "Aawaz clearly nahi aayi. Dobara bhejo? ���")
                return
            input_text = transcript

        elif message_type == "image":
            input_type = "image"
            await _safe_send_message(phone, "📸 Dekh raha hoon...")
            if not media_id:
                await _safe_send_message(phone, "Image media missing tha. Dobara bhejo.")
                return
            image_bytes, _ = await download_media(media_id)
            ocr_text = await extract_text(image_bytes)
            input_text = "image bheja hai"

        elif message_type == "document":
            input_type = "document"
            await _safe_send_message(phone, "Document mil gaya. Context analyze kar raha hoon.")
            if not media_id:
                await _safe_send_message(phone, "Document media missing tha. Dobara bhejo.")
                return
            doc_bytes, _ = await download_media(media_id)
            extracted = await extract_text(doc_bytes)
            ocr_text = extracted or ""
            if text_body:
                input_text = text_body
            elif ocr_text:
                input_text = "document bheja hai"
            else:
                input_text = "document bheja hai, summary do"

        elif message_type == "video":
            input_text = "User sent a video message and wants business help. Ask one clarification question if needed."
            input_type = "text"

        elif message_type == "location":
            input_text = "User shared a location pin in WhatsApp and asked for support. Respond naturally for business context."
            input_type = "text"

        elif message_type == "link":
            input_text = "User shared a link and wants business assistance. Respond naturally and ask a focused next step."
            input_type = "text"

        history = list(session_context.get("conversation_history", []))

        result = await run_artha(
            merchant_phone=phone,
            user_input=input_text,
            input_type=input_type,
            ocr_text=ocr_text,
            is_morning=is_morning_brief,
            is_evening=is_evening,
            conversation_history=history,
            db_session=db,
        )

        response_text = result.get("response_text", "Thoda busy hoon abhi, ek minute mein try karo ���")
        intent = result.get("intent", "OUT_OF_SCOPE")

        append_conversation_pair(db, phone, input_text, response_text)
        session_context = get_session_context(db, phone)
        session_context["last_message_date"] = today_str
        if is_morning_brief:
            session_context["morning_brief_sent_date"] = today_str
        update_session_context(db, phone, session_context)

        if result.get("needs_recheck"):
            payment_meta = result.get("payment_meta") or {}
            txn_ref = payment_meta.get("txn_ref")
            if txn_ref:
                set_pending_recheck(
                    db,
                    phone,
                    {
                        "txn_ref": txn_ref,
                        "amount": payment_meta.get("amount"),
                        "created_at": datetime.now().isoformat(),
                    },
                )
                _launch_background_task(_schedule_payment_recheck(phone, txn_ref, payment_meta.get("amount")))

    await _send_output(phone, input_type=input_type, intent=intent, response_text=response_text)


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    if hub_mode == "subscribe" and hub_verify_token == verify_token and hub_challenge is not None:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@app.post("/webhook")
async def webhook_handler(request: Request) -> JSONResponse:
    payload = await request.json()
    message = _extract_message(payload)
    if not message:
        return JSONResponse({"status": "ok"})

    phone = message.get("from")
    if not phone:
        return JSONResponse({"status": "ok"})

    message_id = message.get("id")
    if not _register_inbound_message_id(message_id=message_id, phone=phone):
        return JSONResponse({"status": "ok", "deduped": True})

    message_type, text_body, media_id = _extract_message_type_data(message)
    _launch_background_task(process_message(phone=phone, message_type=message_type, text_body=text_body, media_id=media_id))
    return JSONResponse({"status": "ok"})


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


@app.get("/demo", response_class=HTMLResponse)
async def demo_page() -> str:
    return """
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
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
  <main class=\"wrap\">
    <section class=\"card\">
      <span class=\"pill\">Artha 1.0</span>
      <h1>Artha: AI Munshi for Kirana Shops</h1>
      <p>
        Voice notes, payment verification, udhaar tracking, and proactive business insights - all in WhatsApp.
      </p>
      <div class=\"grid\">
        <article class=\"feature\"><h3>Voice In, Voice Out</h3><p>Merchant sends voice note, Artha replies with voice + grounded numbers.</p></article>
        <article class=\"feature\"><h3>Payment Verification</h3><p>OCR + DB lookup for honest confirmation without false claims.</p></article>
        <article class=\"feature\"><h3>Business Memory</h3><p>Tracks udhaar, expenses, customer patterns, and morning/eod summaries.</p></article>
      </div>
    </section>
  </main>
</body>
</html>
"""
