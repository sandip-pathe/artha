from __future__ import annotations

import re

from app.fraud.google_vision import dominant_rgb
from app.fraud.types import LayerResult


APP_COLORS: dict[str, tuple[int, int, int]] = {
	"PAYTM": (0, 186, 242),
	"PHONEPE": (95, 37, 159),
	"GPAY": (66, 133, 244),
	"BHIM": (0, 44, 95),
}


def _detect_claimed_app(ocr_text: str) -> str | None:
	text = (ocr_text or "").upper()
	if "PHONEPE" in text or "PHONE PE" in text:
		return "PHONEPE"
	if "PAYTM" in text:
		return "PAYTM"
	if "GPAY" in text or "GOOGLE PAY" in text:
		return "GPAY"
	if re.search(r"\bBHIM\b", text):
		return "BHIM"
	return None


def _distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
	return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


async def analyze_color(image_bytes: bytes, ocr_text: str) -> LayerResult:
	claimed_app = _detect_claimed_app(ocr_text)
	dominant = await dominant_rgb(image_bytes)
	if dominant is None:
		return LayerResult(
			layer="APP_COLOR",
			flagged=False,
			confidence="LOW",
			detail="Color check unavailable: configure Google Vision service account credentials",
			metadata={"payment_app": claimed_app},
		)

	if claimed_app and claimed_app in APP_COLORS:
		dist = _distance(dominant, APP_COLORS[claimed_app])
		if dist > 95:
			return LayerResult(
				layer="APP_COLOR",
				flagged=True,
				confidence="HIGH",
				detail=f"Dominant color does not match claimed {claimed_app} palette",
				red_flags=[f"App color mismatch for {claimed_app}"],
				metadata={"payment_app": claimed_app, "dominant_rgb": str(dominant), "distance": round(dist, 2)},
			)

	inferred_app = min(APP_COLORS, key=lambda app: _distance(dominant, APP_COLORS[app]))
	return LayerResult(
		layer="APP_COLOR",
		flagged=False,
		confidence="MEDIUM",
		detail="Dominant color is consistent with payment app branding",
		metadata={"payment_app": claimed_app or inferred_app, "dominant_rgb": str(dominant)},
	)
