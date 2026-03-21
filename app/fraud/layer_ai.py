from __future__ import annotations

import base64
import json
import os
import re

from openai import AsyncOpenAI

from app.fraud.types import LayerResult


SYSTEM_PROMPT = """You are a payment fraud analyst. You are analyzing a photo taken by a merchant of a customer's phone showing a payment confirmation screen. This is NOT a digital screenshot - it is a physical photo.

Look for visual inconsistencies that suggest fraud:
1. Font weight/style inconsistencies (edited numbers look different)
2. Pixel artifacts or halos around text (signs of image editing)
3. Color banding or JPEG compression artifacts around amounts
4. Layout deviations from standard Paytm/PhonePe/GPay templates
5. If the screen looks suspiciously perfect for a photo (no reflections, no angle) it may be a pre-made fake image displayed on the fraudster's screen

Respond ONLY with JSON:
{
  "flagged": boolean,
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "visual_anomalies": string[],
  "payment_app_detected": string,
  "amount_detected": string | null
}

Be conservative. Only flagged=true when HIGH confidence of manipulation. When uncertain, flagged=false."""


def _extract_json(text: str) -> dict:
	match = re.search(r"\{.*\}", text, re.DOTALL)
	if not match:
		raise ValueError("No JSON object found in model response")
	return json.loads(match.group(0))


async def analyze_with_gpt_vision(image_bytes: bytes, mime_type: str, ocr_summary: str) -> LayerResult:
	api_key = os.getenv("OPENAI_API_KEY", "")
	if not api_key:
		return LayerResult(
			layer="AI_VISION",
			flagged=False,
			confidence="LOW",
			detail="AI analysis unavailable",
		)

	client = AsyncOpenAI(api_key=api_key)
	image_b64 = base64.b64encode(image_bytes).decode("ascii")

	try:
		response = await client.responses.create(
			model="gpt-4o",
			input=[
				{
					"role": "system",
					"content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
				},
				{
					"role": "user",
					"content": [
						{
							"type": "input_text",
							"text": f"OCR text already extracted: {ocr_summary}",
						},
						{
							"type": "input_image",
							"image_url": f"data:{mime_type};base64,{image_b64}",
						},
					],
				},
			],
		)
		payload = _extract_json(response.output_text)
	except Exception:
		return LayerResult(
			layer="AI_VISION",
			flagged=False,
			confidence="LOW",
			detail="AI analysis unavailable",
		)

	flagged = bool(payload.get("flagged", False))
	confidence = str(payload.get("confidence", "LOW")).upper()
	if confidence not in {"HIGH", "MEDIUM", "LOW"}:
		confidence = "LOW"

	anomalies = [str(x) for x in payload.get("visual_anomalies", []) if str(x).strip()]
	payment_app = payload.get("payment_app_detected")
	amount_detected = payload.get("amount_detected")

	return LayerResult(
		layer="AI_VISION",
		flagged=flagged,
		confidence=confidence,
		detail="GPT-4o vision analysis complete",
		red_flags=anomalies if flagged else [],
		metadata={
			"payment_app": str(payment_app) if payment_app is not None else None,
			"amount_detected": str(amount_detected) if amount_detected is not None else None,
		},
	)
