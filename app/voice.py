from __future__ import annotations

import io
import logging
import os
import re

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

def _clean_for_tts(text: str) -> str:
    # Remove unicode emojis and special non-spoken characters
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    # Deepgram Aura does well with English text, expand some hindi terms cleanly
    cleaned = cleaned.replace("₹", " rupees ")
    cleaned = cleaned.replace("%", " percent ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

async def _transcribe_openai_fallback(audio_bytes: bytes) -> str | None:
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
        text = (getattr(result, "text", "") or "").strip()
        return text or None
    except Exception:
        logger.exception("OpenAI fallback transcription failed")
        return None


async def transcribe_voice(audio_bytes: bytes, mime_type: str) -> str | None:
    deepgram_key = os.getenv("DEEPGRAM_API_KEY", "")
    
    if not deepgram_key:
        return await _transcribe_openai_fallback(audio_bytes)

    # Use Deepgram Nova-2 (super high accuracy for Indian accents & Hinglish)
    url = "https://api.deepgram.com/v1/listen?model=nova-2-general&detect_language=true&smart_format=true"
    headers = {
        "Authorization": f"Token {deepgram_key}",
        "Content-Type": mime_type or "audio/ogg",
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, content=audio_bytes, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            channels = data.get("results", {}).get("channels", [])
            if channels and channels[0].get("alternatives"):
                transcript = channels[0]["alternatives"][0].get("transcript", "")
                if transcript:
                    return transcript.strip()
    except Exception:
        logger.exception("Deepgram STT failed, falling back to OpenAI")
        
    return await _transcribe_openai_fallback(audio_bytes)


async def _synthesize_openai_fallback(cleaned_text: str) -> bytes | None:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None

    client = AsyncOpenAI(api_key=api_key)
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
        logger.exception("OpenAI fallback TTS failed")
        return None


async def synthesize_voice(text: str) -> bytes | None:
    cleaned_text = _clean_for_tts(text)
    if not cleaned_text:
        return None

    deepgram_key = os.getenv("DEEPGRAM_API_KEY", "")
    if not deepgram_key:
        return await _synthesize_openai_fallback(cleaned_text)

    # Use Deepgram Aura TTS (extremely fast, very human-like "call quality")
    # Asteria is a pleasant female voice; 'aura-zeus-en' or 'aura-orion-en' are male
    voice_model = "aura-asteria-en"
    url = f"https://api.deepgram.com/v1/speak?model={voice_model}"
    headers = {
        "Authorization": f"Token {deepgram_key}",
        "Content-Type": "application/json"
    }
    payload = {"text": cleaned_text}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            return response.content
    except Exception:
        logger.exception("Deepgram TTS failed, falling back to OpenAI")
        return await _synthesize_openai_fallback(cleaned_text)


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
