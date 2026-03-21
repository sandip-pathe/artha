from __future__ import annotations

import os

import httpx


GRAPH_API_BASE = "https://graph.facebook.com/v22.0"


class WhatsAppAPIError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise WhatsAppAPIError(f"Missing required environment variable: {name}")
    return value


async def download_media(media_id: str) -> tuple[bytes, str]:
    token = _require_env("WHATSAPP_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        meta_url = f"{GRAPH_API_BASE}/{media_id}"
        meta_res = await client.get(meta_url, headers=headers)
        if meta_res.status_code >= 400:
            raise WhatsAppAPIError(
                f"Failed to fetch media metadata for media_id={media_id}: "
                f"status={meta_res.status_code}, body={meta_res.text}"
            )

        try:
            media_url = meta_res.json()["url"]
        except (KeyError, TypeError, ValueError) as exc:
            raise WhatsAppAPIError(
                f"Media metadata missing url field for media_id={media_id}"
            ) from exc

        media_res = await client.get(media_url, headers=headers)
        if media_res.status_code >= 400:
            raise WhatsAppAPIError(
                f"Failed to download media for media_id={media_id}: "
                f"status={media_res.status_code}, body={media_res.text}"
            )

        mime_type = media_res.headers.get("content-type", "application/octet-stream")
        return media_res.content, mime_type


async def send_message(to: str, text: str) -> dict:
    token = _require_env("WHATSAPP_TOKEN")
    phone_number_id = _require_env("WHATSAPP_PHONE_NUMBER_ID")

    url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise WhatsAppAPIError(
                f"Failed to send WhatsApp message to {to}: "
                f"status={response.status_code}, body={response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise WhatsAppAPIError(
                f"WhatsApp API returned non-JSON response for send_message to {to}"
            ) from exc


async def send_interactive_buttons(to: str, body_text: str, buttons: list[dict]) -> dict:
    token = _require_env("WHATSAPP_TOKEN")
    phone_number_id = _require_env("WHATSAPP_PHONE_NUMBER_ID")

    if not buttons:
        raise WhatsAppAPIError("interactive buttons payload cannot be empty")

    reply_buttons = []
    for item in buttons[:3]:
        button_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not button_id or not title:
            continue
        reply_buttons.append(
            {
                "type": "reply",
                "reply": {
                    "id": button_id[:256],
                    "title": title[:20],
                },
            }
        )

    if not reply_buttons:
        raise WhatsAppAPIError("no valid interactive buttons were provided")

    url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": reply_buttons},
        },
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise WhatsAppAPIError(
                f"Failed to send WhatsApp interactive buttons to {to}: "
                f"status={response.status_code}, body={response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise WhatsAppAPIError(
                f"WhatsApp API returned non-JSON response for send_interactive_buttons to {to}"
            ) from exc


async def send_template_message(
    to: str,
    template_name: str,
    language_code: str = "en",
    components: list[dict] | None = None,
) -> dict:
    token = _require_env("WHATSAPP_TOKEN")
    phone_number_id = _require_env("WHATSAPP_PHONE_NUMBER_ID")

    if not template_name.strip():
        raise WhatsAppAPIError("template_name is required")

    url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    template_payload: dict = {
        "name": template_name.strip(),
        "language": {"code": language_code or "en"},
    }
    if components:
        template_payload["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template_payload,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise WhatsAppAPIError(
                f"Failed to send WhatsApp template to {to}: "
                f"status={response.status_code}, body={response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise WhatsAppAPIError(
                f"WhatsApp API returned non-JSON response for send_template_message to {to}"
            ) from exc


async def upload_media(media_bytes: bytes, mime_type: str, filename: str) -> str:
    token = _require_env("WHATSAPP_TOKEN")
    phone_number_id = _require_env("WHATSAPP_PHONE_NUMBER_ID")

    url = f"{GRAPH_API_BASE}/{phone_number_id}/media"
    headers = {"Authorization": f"Bearer {token}"}
    files = {
        "file": (filename, media_bytes, mime_type),
    }
    data = {
        "messaging_product": "whatsapp",
        "type": mime_type,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, files=files, data=data)
        if response.status_code >= 400:
            raise WhatsAppAPIError(
                f"Failed to upload media: status={response.status_code}, body={response.text}"
            )
        try:
            payload = response.json()
            media_id = payload["id"]
            return str(media_id)
        except (ValueError, KeyError, TypeError) as exc:
            raise WhatsAppAPIError("WhatsApp media upload returned invalid payload") from exc


async def send_voice_message(to: str, audio_bytes: bytes) -> dict:
    token = _require_env("WHATSAPP_TOKEN")
    phone_number_id = _require_env("WHATSAPP_PHONE_NUMBER_ID")
    media_id = await upload_media(audio_bytes, "audio/mpeg", "artha-reply.mp3")

    url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise WhatsAppAPIError(
                f"Failed to send WhatsApp voice message to {to}: status={response.status_code}, body={response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise WhatsAppAPIError(
                f"WhatsApp API returned non-JSON response for send_voice_message to {to}"
            ) from exc
