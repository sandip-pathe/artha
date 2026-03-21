from __future__ import annotations

import asyncio
import io
from statistics import fmean

from PIL import Image, ImageFilter, ImageStat

from app.fraud.types import LayerResult


def _variance(values: list[float]) -> float:
	if not values:
		return 0.0
	mean = fmean(values)
	return fmean([(v - mean) ** 2 for v in values])


def _analyze_sync(image_bytes: bytes) -> LayerResult:
	image = Image.open(io.BytesIO(image_bytes))
	rgb = image.convert("RGB")
	gray = rgb.convert("L")

	red_flags: list[str] = []
	suspicious_signals = 0

	exif = image.getexif()
	has_camera_exif = bool(exif and any(tag in exif for tag in (271, 272, 36867)))
	if not has_camera_exif:
		suspicious_signals += 1
		red_flags.append("No camera EXIF markers found")

	width, height = gray.size
	edge_band = max(6, min(width, height) // 18)

	sharp = gray.filter(ImageFilter.FIND_EDGES)
	center_box = (edge_band, edge_band, width - edge_band, height - edge_band)

	center_mean = ImageStat.Stat(sharp.crop(center_box)).mean[0]
	border_strips = [
		sharp.crop((0, 0, width, edge_band)),
		sharp.crop((0, height - edge_band, width, height)),
		sharp.crop((0, 0, edge_band, height)),
		sharp.crop((width - edge_band, 0, width, height)),
	]
	border_mean = fmean(ImageStat.Stat(strip).mean[0] for strip in border_strips)
	if border_mean > center_mean * 0.92:
		suspicious_signals += 1
		red_flags.append("Edge sharpness is unusually uniform for a camera capture")

	tiny = gray.resize((96, 96))
	px = list(tiny.getdata())
	diffs = [abs(px[i] - px[i - 1]) for i in range(1, len(px))]
	high_freq_energy = _variance(diffs)
	if high_freq_energy < 70:
		suspicious_signals += 1
		red_flags.append("Low micro-texture suggests a flat digital source")

	aspect = width / float(height)
	if 0.52 <= aspect <= 0.58 and width < 1400:
		suspicious_signals += 1
		red_flags.append("Image framing looks like direct screenshot dimensions")

	flagged = suspicious_signals >= 2
	confidence = "MEDIUM" if flagged else "LOW"
	detail = (
		"Physical checks indicate possible non-camera source"
		if flagged
		else "Physical characteristics are compatible with photographed screen"
	)
	return LayerResult(
		layer="PHYSICAL_REALITY",
		flagged=flagged,
		confidence=confidence,
		detail=detail,
		red_flags=red_flags if flagged else [],
		metadata={"suspicious_subsignals": suspicious_signals, "high_freq_energy": round(high_freq_energy, 2)},
	)


async def analyze_physical_reality(image_bytes: bytes) -> LayerResult:
	return await asyncio.to_thread(_analyze_sync, image_bytes)
