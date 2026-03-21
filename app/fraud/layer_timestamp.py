from __future__ import annotations

import re
from datetime import date, datetime

from app.fraud.types import LayerResult


STATUS_TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
RECEIPT_TIME_PATTERN = re.compile(
	r"paid(?:\s+successfully)?(?:\s+at)?\s*([01]?\d|2[0-3]):([0-5]\d)",
	re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b")


def _extract_times(ocr_text: str) -> tuple[datetime | None, datetime | None]:
	all_times = STATUS_TIME_PATTERN.findall(ocr_text)
	status_bar = None
	receipt = None

	if all_times:
		h, m = all_times[0]
		status_bar = datetime.now().replace(hour=int(h), minute=int(m), second=0, microsecond=0)

	receipt_match = RECEIPT_TIME_PATTERN.search(ocr_text)
	if receipt_match:
		h, m = receipt_match.groups()
		receipt = datetime.now().replace(hour=int(h), minute=int(m), second=0, microsecond=0)

	return status_bar, receipt


def _extract_date(ocr_text: str) -> date | None:
	match = DATE_PATTERN.search(ocr_text)
	if not match:
		return None

	d, m, y = match.groups()
	year = int(y)
	if year < 100:
		year += 2000

	try:
		return date(year=year, month=int(m), day=int(d))
	except ValueError:
		return None


def analyze_timestamps(ocr_text: str) -> LayerResult:
	status_bar_time, receipt_time = _extract_times(ocr_text or "")
	red_flags: list[str] = []

	if status_bar_time and receipt_time:
		delta_minutes = abs((status_bar_time - receipt_time).total_seconds()) / 60.0
		if delta_minutes > 15:
			red_flags.append(f"Status bar and receipt times differ by {delta_minutes:.1f} minutes")

	receipt_date = _extract_date(ocr_text or "")
	if receipt_date:
		days_old = (date.today() - receipt_date).days
		if days_old > 2:
			red_flags.append(f"Receipt appears {days_old} days old")
	else:
		days_old = None

	if red_flags:
		confidence = "HIGH" if any("days old" in flag for flag in red_flags) else "MEDIUM"
		return LayerResult(
			layer="TIMESTAMP",
			flagged=True,
			confidence=confidence,
			detail="Timestamp consistency checks found anomalies",
			red_flags=red_flags,
			metadata={"receipt_age_days": days_old},
		)

	if status_bar_time and receipt_time:
		return LayerResult(
			layer="TIMESTAMP",
			flagged=False,
			confidence="MEDIUM",
			detail="Status bar and receipt timestamps are within normal range",
		)

	return LayerResult(
		layer="TIMESTAMP",
		flagged=False,
		confidence="LOW",
		detail="Insufficient timestamp fields detected for full validation",
	)
