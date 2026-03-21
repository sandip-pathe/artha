from __future__ import annotations

import re
from datetime import datetime

from app.fraud.types import LayerResult


PHONEPE_PATTERN = re.compile(r"T(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\w+")
PAYTM_PATTERN = re.compile(r"\b\d{16,20}\b")
GPAY_PATTERN = re.compile(r"\b[A-Z0-9]{20,25}\b")
TIME_PATTERN = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?[APMapm]{2})?\b")


def _parse_receipt_time(receipt_time_str: str) -> datetime | None:
	if not receipt_time_str:
		return None

	match = TIME_PATTERN.search(receipt_time_str)
	if not match:
		return None

	value = match.group(0).strip()
	for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
		try:
			parsed = datetime.strptime(value.upper(), fmt)
			return parsed
		except ValueError:
			continue
	return None


def analyze_transaction_id(image_text: str, receipt_time_str: str) -> LayerResult:
	ocr_text = image_text or ""

	phonepe_match = PHONEPE_PATTERN.search(ocr_text)
	if phonepe_match:
		yy, mm, dd, hh, minute, ss = map(int, phonepe_match.groups())
		txn_time = datetime(year=2000 + yy, month=mm, day=dd, hour=hh, minute=minute, second=ss)
		receipt_time = _parse_receipt_time(receipt_time_str)

		if receipt_time:
			normalized_receipt = txn_time.replace(
				hour=receipt_time.hour,
				minute=receipt_time.minute,
				second=0,
			)
			delta_minutes = abs((txn_time - normalized_receipt).total_seconds()) / 60.0
			if delta_minutes > 3:
				return LayerResult(
					layer="TRANSACTION_ID",
					flagged=True,
					confidence="HIGH",
					detail=f"PhonePe TXN ID timestamp mismatch: delta {delta_minutes:.1f} min (>3)",
					red_flags=["Transaction ID embedded time does not match receipt time"],
					metadata={"transaction_ref": phonepe_match.group(0)},
				)

			return LayerResult(
				layer="TRANSACTION_ID",
				flagged=False,
				confidence="HIGH",
				detail="PhonePe TXN ID timestamp matches receipt time",
				metadata={"transaction_ref": phonepe_match.group(0)},
			)

		return LayerResult(
			layer="TRANSACTION_ID",
			flagged=False,
			confidence="MEDIUM",
			detail="PhonePe TXN ID found; receipt time unavailable for strict comparison",
			metadata={"transaction_ref": phonepe_match.group(0)},
		)

	paytm_match = PAYTM_PATTERN.search(ocr_text)
	if paytm_match:
		return LayerResult(
			layer="TRANSACTION_ID",
			flagged=False,
			confidence="MEDIUM",
			detail="Paytm-style numeric transaction reference found",
			metadata={"transaction_ref": paytm_match.group(0)},
		)

	gpay_match = GPAY_PATTERN.search(ocr_text)
	if gpay_match:
		return LayerResult(
			layer="TRANSACTION_ID",
			flagged=False,
			confidence="MEDIUM",
			detail="GPay-style alphanumeric transaction reference found",
			metadata={"transaction_ref": gpay_match.group(0)},
		)

	return LayerResult(
		layer="TRANSACTION_ID",
		flagged=True,
		confidence="MEDIUM",
		detail="No known transaction ID pattern found in OCR",
		red_flags=["Missing or unreadable transaction reference"],
	)
