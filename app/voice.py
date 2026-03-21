from __future__ import annotations

import io
import os
import re

from openai import AsyncOpenAI


def _clean_for_tts(text: str) -> str:
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    cleaned = cleaned.replace("₹", " rupaye ")
    cleaned = cleaned.replace("%", " pratishat ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


async def transcribe_voice(audio_bytes: bytes, mime_type: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None

    client = AsyncOpenAI(api_key=api_key)
    payload = io.BytesIO(audio_bytes)
    payload.name = "audio.ogg"

    try:
        result = await client.audio.transcriptions.create(
            model="whisper-1",
            file=payload,
            prompt=(
                "This is a message from an Indian grocery store owner about their business. "
                "May contain Hindi, Marathi, or English. Terms may include udhaar, paisa, "
                "customer names, and UPI amounts in rupees."
            ),
        )
    except Exception:
        return None

    text = (getattr(result, "text", "") or "").strip()
    return text or None


async def synthesize_voice(text: str) -> bytes | None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None

    client = AsyncOpenAI(api_key=api_key)
    cleaned_text = _clean_for_tts(text)
    if not cleaned_text:
        return None

    tts_model = os.getenv("OPENAI_TTS_MODEL", "tts-1-hd").strip() or "tts-1-hd"
    tts_voice = os.getenv("OPENAI_TTS_VOICE", "nova").strip() or "nova"

    try:
        response = await client.audio.speech.create(
            model=tts_model,
            voice=tts_voice,
            input=cleaned_text,
            response_format="mp3",
        )
        return response.read()
    except Exception:
        return None


def should_reply_with_voice(input_type: str, response_text: str, intent: str) -> str:
    if intent == "PAYMENT_VERIFY":
        return "text"
    if len((response_text or "").strip()) < 50:
        return "text"
    if intent in {"MORNING_BRIEF", "EOD_BRIEF"}:
        return "both"
    if input_type == "voice":
        return "voice"
    if input_type == "image":
        return "text"
    return "text"
