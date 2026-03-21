from __future__ import annotations

import re

from app.fraud.types import LayerResult


UPI_PATTERN = re.compile(r"\b[a-zA-Z0-9._-]+@[a-zA-Z]{2,}\b")


def _normalize_text(value: str) -> str:
	return re.sub(r"[^a-z0-9]", "", value.lower())


def _levenshtein(a: str, b: str) -> int:
	if a == b:
		return 0
	if not a:
		return len(b)
	if not b:
		return len(a)

	prev = list(range(len(b) + 1))
	for i, ca in enumerate(a, 1):
		cur = [i]
		for j, cb in enumerate(b, 1):
			cost = 0 if ca == cb else 1
			cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
		prev = cur
	return prev[-1]


def _extract_candidate_name(ocr_text: str) -> str | None:
	for line in ocr_text.splitlines():
		line = line.strip()
		if not line:
			continue
		if any(token in line.lower() for token in ["paid", "transaction", "upi", "ref", "id"]):
			continue
		if re.search(r"[A-Za-z]{3,}\s+[A-Za-z]{2,}", line):
			return line
	return None


def analyze_merchant_match(ocr_text: str, merchant_upi: str, merchant_name: str) -> LayerResult:
	red_flags: list[str] = []
	text = ocr_text or ""

	found_upis = UPI_PATTERN.findall(text)
	matched_upi = next((u for u in found_upis if u.lower() == merchant_upi.lower()), None)
	if merchant_upi and not matched_upi and found_upis:
		expected_domain = merchant_upi.split("@")[-1].lower()
		found_domain = found_upis[0].split("@")[-1].lower()
		if expected_domain != found_domain:
			red_flags.append("UPI domain mismatch against registered merchant UPI")
		else:
			red_flags.append("UPI ID mismatch against registered merchant UPI")

	candidate_name = _extract_candidate_name(text)
	if merchant_name and candidate_name:
		merchant_norm = _normalize_text(merchant_name)
		candidate_norm = _normalize_text(candidate_name)
		distance = _levenshtein(merchant_norm, candidate_norm)
		if distance >= 3:
			red_flags.append("Recipient name does not match registered merchant name")

	if red_flags:
		return LayerResult(
			layer="MERCHANT_MATCH",
			flagged=True,
			confidence="HIGH",
			detail="Merchant recipient validation failed",
			red_flags=red_flags,
			metadata={"detected_upi": found_upis[0] if found_upis else None, "detected_name": candidate_name},
		)

	return LayerResult(
		layer="MERCHANT_MATCH",
		flagged=False,
		confidence="HIGH",
		detail="Recipient details match merchant profile",
		metadata={"detected_upi": matched_upi or (found_upis[0] if found_upis else None), "detected_name": candidate_name},
	)
