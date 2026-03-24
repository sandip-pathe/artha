from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.agent import _extract_utr_and_amount, run_artha
from app.db.bootstrap import ensure_artha_schema
from app.db.models import ProcessedWebhookMessages
from app.db.seed import seed
from app.db.session import SessionLocal, engine
from app.main import _should_send_morning_brief, app
from app.voice import should_reply_with_voice


def _ensure_seed_data() -> None:
    ensure_artha_schema(engine)
    seed()


def test_extract_utr_and_amount_parses_image_text() -> None:
    utr, amount = _extract_utr_and_amount("Paid\nTxn ID T260321153045DEMO0001\nAmount INR 450")
    assert utr == "T260321153045DEMO0001"
    assert amount == 450.0


def test_payment_verify_found_demo_transaction() -> None:
    _ensure_seed_data()
    with SessionLocal() as db:
        result = asyncio.run(
            run_artha(
                merchant_phone="918767394523",
                user_input="image bheja hai",
                input_type="image",
                ocr_text="Txn ID T260321153045DEMO0001\nAmount INR 450",
                db_session=db,
            )
        )
    assert result["intent"] == "PAYMENT_VERIFY"
    assert result["needs_recheck"] is False
    assert "Confirmed" in result["response_text"]


def test_payment_verify_missing_transaction_sets_recheck() -> None:
    _ensure_seed_data()
    with SessionLocal() as db:
        result = asyncio.run(
            run_artha(
                merchant_phone="918767394523",
                user_input="image bheja hai",
                input_type="image",
                ocr_text="Txn ID T260321153045DEMO9999\nAmount INR 450",
                db_session=db,
            )
        )
    assert result["intent"] == "PAYMENT_VERIFY"
    assert result["needs_recheck"] is True


def test_morning_brief_trigger_window() -> None:
    now = datetime(2026, 3, 20, 8, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    today = now.date().isoformat()
    yesterday = (now - timedelta(days=1)).date().isoformat()

    assert _should_send_morning_brief(last_message_date=yesterday, now=now) is True
    assert _should_send_morning_brief(last_message_date=today, now=now) is False

    late = now.replace(hour=21)
    assert _should_send_morning_brief(last_message_date=yesterday, now=late) is False


def test_voice_modality_rules() -> None:
    assert should_reply_with_voice(input_type="voice", response_text="Aaj ka total 2400 rupaye hai", intent="SALES_QUERY") == "voice"
    assert should_reply_with_voice(input_type="image", response_text="✅ Payment Confirmed", intent="PAYMENT_VERIFY") == "text"
    assert should_reply_with_voice(input_type="text", response_text="Kal ka summary ready hai", intent="MORNING_BRIEF") == "both"
    assert should_reply_with_voice(input_type="text", response_text="Noted", intent="GENERAL_NOTE") == "text"


def test_webhook_dedupes_same_message_id(monkeypatch) -> None:
    _ensure_seed_data()

    with SessionLocal() as db:
        db.execute(delete(ProcessedWebhookMessages).where(ProcessedWebhookMessages.message_id == "wamid.TEST123"))
        db.commit()

    calls: list[object] = []

    def _capture(coro):
        calls.append(coro)

    monkeypatch.setattr("app.main._launch_background_task", _capture)

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.TEST123",
                                    "from": "918767394523",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    client = TestClient(app)
    first = client.post("/webhook", json=payload)
    second = client.post("/webhook", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json().get("deduped") is True
    assert len(calls) == 1
