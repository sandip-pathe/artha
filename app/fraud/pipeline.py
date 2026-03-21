from __future__ import annotations

import asyncio
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FraudChecks, Merchants
from app.fraud.layer_ai import analyze_with_gpt_vision
from app.fraud.layer_color import analyze_color
from app.fraud.google_vision import extract_text
from app.fraud.layer_merchant import analyze_merchant_match
from app.fraud.layer_physical import analyze_physical_reality
from app.fraud.layer_timestamp import analyze_timestamps
from app.fraud.layer_txnid import analyze_transaction_id
from app.fraud.types import FraudResult, LayerResult


AMOUNT_PATTERN = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9]+(?:\.[0-9]{1,2})?)", re.IGNORECASE)
TIME_HINT_PATTERN = re.compile(r"paid(?:\s+successfully)?(?:\s+at)?\s*([01]?\d:[0-5]\d(?:\s?[APMapm]{2})?)", re.IGNORECASE)


async def _run_google_ocr(image_bytes: bytes) -> str:
	return await extract_text(image_bytes)


def _extract_receipt_time(ocr_text: str) -> str:
	match = TIME_HINT_PATTERN.search(ocr_text or "")
	return match.group(1) if match else ""


def _extract_amount(ocr_text: str) -> float | None:
	match = AMOUNT_PATTERN.search(ocr_text or "")
	if not match:
		return None
	try:
		return float(match.group(1))
	except ValueError:
		return None


def _extract_first_ref(layers: list[LayerResult]) -> str | None:
	for layer in layers:
		value = layer.metadata.get("transaction_ref") if layer.metadata else None
		if isinstance(value, str) and value:
			return value
	return None


def _flatten_red_flags(layers: list[LayerResult]) -> list[str]:
	flags: list[str] = []
	for layer in layers:
		for flag in layer.red_flags:
			if flag not in flags:
				flags.append(flag)
	return flags


def _overall_confidence(verdict: str, flagged_count: int) -> str:
	if verdict == "SUSPICIOUS":
		return "HIGH"
	if flagged_count >= 2:
		return "MEDIUM"
	return "LOW"


def _find_layer(layers: list[LayerResult], name: str) -> LayerResult | None:
	return next((layer for layer in layers if layer.layer == name), None)


def _resolve_payment_app(ocr_text: str, layers: list[LayerResult]) -> str | None:
	for layer in layers:
		value = layer.metadata.get("payment_app") if layer.metadata else None
		if isinstance(value, str) and value:
			return value

	upper = (ocr_text or "").upper()
	if "PHONEPE" in upper or "PHONE PE" in upper:
		return "PHONEPE"
	if "PAYTM" in upper:
		return "PAYTM"
	if "GPAY" in upper or "GOOGLE PAY" in upper:
		return "GPAY"
	if "BHIM" in upper:
		return "BHIM"
	return None


def _persist_fraud_check(
	db_session: Session,
	merchant_upi: str,
	merchant_name: str,
	verdict: str,
	confidence: str,
	layers_flagged: list[str],
	red_flags: list[str],
	raw_amount: float | None,
	payment_app: str | None,
	transaction_ref: str | None,
) -> None:
	merchant = None
	if merchant_upi:
		merchant = db_session.scalar(select(Merchants).where(Merchants.upi_id == merchant_upi))
	if not merchant and merchant_name:
		merchant = db_session.scalar(select(Merchants).where(Merchants.name == merchant_name))
	if not merchant:
		return

	recommendation = {
		"GENUINE": "Proceed with order.",
		"CANNOT_VERIFY": "Ask customer to re-initiate payment from your QR.",
		"SUSPICIOUS": "Do not hand over goods until confirmed in merchant account.",
	}[verdict]

	record = FraudChecks(
		merchant_id=merchant.id,
		image_path="whatsapp-media",
		verdict=verdict,
		confidence=confidence,
		layers_flagged=layers_flagged,
		red_flags=red_flags,
		recommendation=recommendation,
		raw_amount=raw_amount,
		payment_app=payment_app,
		transaction_ref=transaction_ref,
	)
	db_session.add(record)
	db_session.commit()


async def run_fraud_pipeline(
	image_bytes: bytes,
	mime_type: str,
	merchant_upi: str,
	merchant_name: str,
	db_session: Session,
) -> FraudResult:
	ocr_text = await _run_google_ocr(image_bytes)
	receipt_time = _extract_receipt_time(ocr_text)

	physical_task = asyncio.create_task(analyze_physical_reality(image_bytes))
	color_task = asyncio.create_task(analyze_color(image_bytes, ocr_text))
	ai_task = asyncio.create_task(analyze_with_gpt_vision(image_bytes, mime_type, ocr_text[:2000]))

	txn_layer = analyze_transaction_id(ocr_text, receipt_time)
	timestamp_layer = analyze_timestamps(ocr_text)
	merchant_layer = analyze_merchant_match(ocr_text, merchant_upi, merchant_name)
	physical_layer, color_layer, ai_layer = await asyncio.gather(physical_task, color_task, ai_task)

	layers = [physical_layer, color_layer, txn_layer, timestamp_layer, merchant_layer, ai_layer]
	flagged_layers = [layer for layer in layers if layer.flagged]
	layer_names = [layer.layer for layer in flagged_layers]

	layer_txnid = _find_layer(layers, "TRANSACTION_ID")
	layer_merchant = _find_layer(layers, "MERCHANT_MATCH")

	if layer_txnid and layer_txnid.flagged and layer_txnid.confidence == "HIGH":
		verdict = "SUSPICIOUS" if len(flagged_layers) >= 2 else "CANNOT_VERIFY"
	elif layer_merchant and layer_merchant.flagged:
		verdict = "SUSPICIOUS"
	elif len(flagged_layers) >= 3:
		verdict = "SUSPICIOUS"
	elif len(flagged_layers) == 2:
		verdict = "CANNOT_VERIFY"
	elif len(flagged_layers) == 0:
		verdict = "GENUINE"
	else:
		verdict = "CANNOT_VERIFY"

	red_flags = _flatten_red_flags(layers)
	amount_detected = _extract_amount(ocr_text)
	payment_app_detected = _resolve_payment_app(ocr_text, layers)
	transaction_ref = _extract_first_ref(layers)
	confidence = _overall_confidence(verdict, len(flagged_layers))

	await asyncio.to_thread(
		_persist_fraud_check,
		db_session,
		merchant_upi,
		merchant_name,
		verdict,
		confidence,
		layer_names,
		red_flags,
		amount_detected,
		payment_app_detected,
		transaction_ref,
	)

	return FraudResult(
		verdict=verdict,
		confidence=confidence,
		layers=layers,
		layers_flagged=layer_names,
		red_flags=red_flags,
		amount_detected=amount_detected,
		payment_app_detected=payment_app_detected,
		transaction_ref=transaction_ref,
	)
