from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from openai import AsyncOpenAI
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.db.models import ExpenseEntries, MerchantNotes, Merchants, Transactions, UdhaarEntries

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

PHONEPE_UTR_RE = re.compile(r"T\d{12}[A-Z0-9]{8}")
PAYTM_UTR_RE = re.compile(r"\b\d{16}\b")
GPAY_UTR_RE = re.compile(r"\b[A-Z0-9]{22}\b")
AMOUNT_RE = re.compile(r"(?:₹|INR)\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)

SYSTEM_PROMPT = """
You are Artha — the AI munshi for Sharma General Store, Mumbai.
You are an AI assistant powered by Paytm's transaction data.

YOUR TWO JOBS:
1. Answer any question about this merchant's business using your tools
2. Verify payments when a merchant sends a screenshot (OCR text provided)

TOOL USAGE RULES — CRITICAL:
- ALWAYS call a tool before answering any business question
- NEVER make up numbers — if data is not in the DB, say so honestly
- For "aaj kitna hua" → call get_sales_summary(period="today")
- For "kaun nahi aaya" → call get_churned_customers(days_threshold=10)
- For "Suresh ne diya" → call search_customer(name="Suresh")
- For any image/OCR text → extract UTR, call search_payment(txn_ref=...)
- For udhaar mentioned → call log_udhaar(...)
- For expense mentioned → call log_expense(...)
- For general question → call get_sales_summary or relevant tool first
- If morning brief triggered → call get_morning_brief()

PAYMENT VERIFICATION — when OCR text is in the message:
1. Extract the transaction ID / UTR from the OCR text
2. Call search_payment with that UTR
3. If FOUND and amount matches → payment is genuine
4. If FOUND but amount differs → suspicious, warn merchant
5. If NOT FOUND and < 10 min old → tell merchant to wait, set needs_recheck
6. If NOT FOUND and > 20 min old → tell merchant to ask customer to pay again
7. If image is not a payment screen → say so naturally

LANGUAGE:
- Respond in whatever language the merchant used (Hindi/English/Hinglish)
- Keep responses SHORT — this is a quick chat interface, not email
- Use ₹ for amounts, emojis naturally (not excessively)
- Never use bullet points longer than 4 items

LOAN/PRODUCT SUGGESTIONS:
- If udhaar total > ₹8,000 OR sales down 3+ consecutive days:
  add at end "💡 Paytm merchant loan ke liye type LOAN"
- If merchant asks about capital or cash flow: proactively mention loan option
- Always frame as a suggestion, never as advice

NEVER:
- Make up sales figures or customer data
- Claim a payment is genuine without checking the DB
- Give financial advice (only suggest tools)
- Respond with a generic greeting if the merchant has asked a real question
""".strip()

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_payment",
            "description": "Search payment by transaction reference and optional amount match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "txn_ref": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["txn_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sales_summary",
            "description": "Get merchant sales summary for a given period.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["today", "yesterday", "this_week", "last_week", "this_month"],
                    }
                },
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_customer",
            "description": "Search transactions and customer profile by name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_customers",
            "description": "Get top customers by spend for last 30 days.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_churned_customers",
            "description": "Find customers with 3+ visits whose last purchase is older than threshold days.",
            "parameters": {
                "type": "object",
                "properties": {"days_threshold": {"type": "integer", "minimum": 1, "maximum": 90}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_udhaar",
            "description": "Log udhaar given or received for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "amount": {"type": "number"},
                    "type": {"type": "string", "enum": ["GIVEN", "RECEIVED"]},
                    "note": {"type": "string"},
                },
                "required": ["customer_name", "amount", "type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_expense",
            "description": "Log an expense entry for the merchant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["amount", "category", "note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_udhaar_summary",
            "description": "Get outstanding udhaar summary overall or for one customer.",
            "parameters": {
                "type": "object",
                "properties": {"customer_name": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_morning_brief",
            "description": "Build morning business brief context from sales, churn, and udhaar.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_eod_summary",
            "description": "Get end-of-day summary including income, expenses, udhaar and net.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "default": "today"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_general_note",
            "description": "Store a general merchant note for later recall.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string"},
                    "category": {"type": "string", "default": "GENERAL"},
                },
                "required": ["note"],
            },
        },
    },
]


def _resolve_merchant(db_session: Session, merchant_phone: str) -> Merchants | None:
    merchant = db_session.scalar(select(Merchants).where(Merchants.phone == merchant_phone))
    if merchant:
        return merchant
    return db_session.scalar(select(Merchants).order_by(Merchants.id).limit(1))


def _extract_utr_and_amount(text: str) -> tuple[str | None, float | None]:
    upper_text = (text or "").upper()
    utr = None
    for pattern in (PHONEPE_UTR_RE, PAYTM_UTR_RE, GPAY_UTR_RE):
        match = pattern.search(upper_text)
        if match:
            utr = match.group(0)
            break

    amount = None
    for candidate in AMOUNT_RE.findall(text or ""):
        numeric = candidate.replace(",", "").strip()
        try:
            parsed = float(numeric)
            if parsed > 0:
                amount = parsed
                break
        except ValueError:
            continue

    return utr, amount


def _period_bounds(period: str) -> tuple[datetime, datetime, datetime, datetime, str]:
    now = datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "today":
        start, end = today_start, now
        prev_start, prev_end = today_start - timedelta(days=1), today_start
        return start, end, prev_start, prev_end, "vs yesterday"

    if period == "yesterday":
        start = today_start - timedelta(days=1)
        end = today_start
        prev_start, prev_end = start - timedelta(days=1), start
        return start, end, prev_start, prev_end, "vs day before"

    if period == "this_week":
        start = today_start - timedelta(days=today_start.weekday())
        end = now
        prev_end = start
        prev_start = prev_end - timedelta(days=7)
        return start, end, prev_start, prev_end, "vs last week"

    if period == "last_week":
        end = today_start - timedelta(days=today_start.weekday())
        start = end - timedelta(days=7)
        prev_end = start
        prev_start = prev_end - timedelta(days=7)
        return start, end, prev_start, prev_end, "vs previous week"

    start = today_start.replace(day=1)
    end = now
    prev_end = start
    prev_start = (start - timedelta(days=1)).replace(day=1)
    return start, end, prev_start, prev_end, "vs last month"


def _compute_udhaar_balance(db_session: Session, merchant_id: int, customer_name: str | None = None) -> list[dict]:
    stmt = select(UdhaarEntries).where(UdhaarEntries.merchant_id == merchant_id)
    if customer_name:
        stmt = stmt.where(UdhaarEntries.customer_name.ilike(f"%{customer_name}%"))

    entries = list(db_session.scalars(stmt))
    balances: dict[str, float] = {}
    last_dates: dict[str, datetime] = {}

    for row in entries:
        sign = 1 if row.type == "GIVEN" else -1
        balances[row.customer_name] = balances.get(row.customer_name, 0.0) + sign * float(row.amount)
        tx_time = datetime.combine(row.date, datetime.min.time())
        if row.customer_name not in last_dates or tx_time > last_dates[row.customer_name]:
            last_dates[row.customer_name] = tx_time

    now = datetime.now(IST)
    results = []
    for name, amount in balances.items():
        if amount <= 0:
            continue
        last_dt = last_dates.get(name)
        results.append(
            {
                "customer_name": name,
                "net_balance": round(amount, 2),
                "days_since_last_transaction": (now.date() - last_dt.date()).days if last_dt else 0,
                "last_transaction_date": last_dt.date().isoformat() if last_dt else None,
            }
        )

    results.sort(key=lambda item: item["net_balance"], reverse=True)
    return results


def execute_tool(name: str, args: dict, db_session: Session, merchant_id: int) -> dict:
    now = datetime.now(IST)

    if name == "search_payment":
        txn_ref = str(args.get("txn_ref") or "").strip()
        amount = args.get("amount")

        if not txn_ref:
            return {"found": False, "txn_ref": "", "minutes_since_receipt": 0}

        exact = db_session.scalar(
            select(Transactions)
            .where(
                and_(
                    Transactions.merchant_id == merchant_id,
                    Transactions.transaction_ref == txn_ref,
                )
            )
            .order_by(desc(Transactions.timestamp))
            .limit(1)
        )
        if exact:
            minutes_ago = max(0, int((now - exact.timestamp.replace(tzinfo=IST)).total_seconds() // 60)) if exact.timestamp.tzinfo else max(0, int((datetime.now() - exact.timestamp).total_seconds() // 60))
            return {
                "found": True,
                "txn_ref": exact.transaction_ref,
                "amount": float(exact.amount),
                "customer_name": exact.customer_name,
                "timestamp": exact.timestamp.isoformat(),
                "minutes_ago": minutes_ago,
                "status": exact.status,
            }

        if amount is not None:
            try:
                amount_value = float(amount)
            except (TypeError, ValueError):
                amount_value = None
            if amount_value and amount_value > 0:
                min_amt, max_amt = amount_value * 0.9, amount_value * 1.1
                cutoff = datetime.now() - timedelta(minutes=30)
                near = db_session.scalar(
                    select(Transactions)
                    .where(
                        and_(
                            Transactions.merchant_id == merchant_id,
                            Transactions.amount >= min_amt,
                            Transactions.amount <= max_amt,
                            Transactions.timestamp >= cutoff,
                        )
                    )
                    .order_by(desc(Transactions.timestamp))
                    .limit(1)
                )
                if near:
                    minutes_ago = max(0, int((datetime.now() - near.timestamp).total_seconds() // 60))
                    return {
                        "found": True,
                        "txn_ref": near.transaction_ref,
                        "amount": float(near.amount),
                        "customer_name": near.customer_name,
                        "timestamp": near.timestamp.isoformat(),
                        "minutes_ago": minutes_ago,
                        "status": near.status,
                        "matched_by": "amount_window",
                    }

        return {
            "found": False,
            "txn_ref": txn_ref,
            "minutes_since_receipt": 2,
        }

    if name == "get_sales_summary":
        period = str(args.get("period") or "today")
        start, end, prev_start, prev_end, comparison_label = _period_bounds(period)

        rows = list(
            db_session.scalars(
                select(Transactions).where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.timestamp >= start,
                        Transactions.timestamp < end,
                    )
                )
            )
        )
        prev_rows = list(
            db_session.scalars(
                select(Transactions).where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.timestamp >= prev_start,
                        Transactions.timestamp < prev_end,
                    )
                )
            )
        )

        total_amount = sum(float(r.amount) for r in rows)
        prev_total = sum(float(r.amount) for r in prev_rows)
        transaction_count = len(rows)
        avg_transaction = total_amount / transaction_count if transaction_count else 0.0

        spend_by_customer: dict[str, float] = {}
        hour_count: dict[int, int] = {}
        for row in rows:
            spend_by_customer[row.customer_name] = spend_by_customer.get(row.customer_name, 0.0) + float(row.amount)
            hour_count[row.timestamp.hour] = hour_count.get(row.timestamp.hour, 0) + 1

        top_customer_name = None
        top_customer_amount = 0.0
        if spend_by_customer:
            top_customer_name, top_customer_amount = max(spend_by_customer.items(), key=lambda item: item[1])

        busiest_hour = max(hour_count.items(), key=lambda item: item[1])[0] if hour_count else None

        if prev_total <= 0:
            comparison_pct_change = 0.0 if total_amount <= 0 else 100.0
        else:
            comparison_pct_change = ((total_amount - prev_total) / prev_total) * 100.0

        return {
            "total_amount": round(total_amount, 2),
            "transaction_count": transaction_count,
            "avg_transaction": round(avg_transaction, 2),
            "top_customer_name": top_customer_name,
            "top_customer_amount": round(float(top_customer_amount), 2),
            "busiest_hour": busiest_hour,
            "comparison_label": comparison_label,
            "comparison_pct_change": round(comparison_pct_change, 2),
        }

    if name == "search_customer":
        query = str(args.get("name") or "").strip()
        if not query:
            return {"customer_name": None, "recent_transactions": []}

        rows = list(
            db_session.scalars(
                select(Transactions)
                .where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.customer_name.ilike(f"%{query}%"),
                    )
                )
                .order_by(desc(Transactions.timestamp))
                .limit(10)
            )
        )
        if not rows:
            return {"customer_name": query, "recent_transactions": []}

        canonical = rows[0].customer_name
        all_rows = list(
            db_session.scalars(
                select(Transactions).where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.customer_name == canonical,
                    )
                )
            )
        )
        total_spent = sum(float(r.amount) for r in all_rows)
        visit_count = len(all_rows)
        last_visit_date = rows[0].timestamp.date().isoformat()
        days_since = (datetime.now().date() - rows[0].timestamp.date()).days

        udhaar = _compute_udhaar_balance(db_session, merchant_id, canonical)
        udhaar_balance = udhaar[0]["net_balance"] if udhaar else 0.0

        return {
            "customer_name": canonical,
            "total_spent": round(total_spent, 2),
            "visit_count": visit_count,
            "last_visit_date": last_visit_date,
            "days_since_last_visit": days_since,
            "udhaar_balance": udhaar_balance,
            "recent_transactions": [
                {
                    "amount": float(r.amount),
                    "timestamp": r.timestamp.isoformat(),
                    "txn_ref": r.transaction_ref,
                }
                for r in rows
            ],
        }

    if name == "get_top_customers":
        limit = int(args.get("limit") or 5)
        cutoff = datetime.now() - timedelta(days=30)
        rows = db_session.execute(
            select(
                Transactions.customer_name,
                Transactions.customer_phone,
                func.sum(Transactions.amount).label("total_spent"),
                func.count(Transactions.id).label("visit_count"),
            )
            .where(
                and_(
                    Transactions.merchant_id == merchant_id,
                    Transactions.timestamp >= cutoff,
                )
            )
            .group_by(Transactions.customer_name, Transactions.customer_phone)
            .order_by(desc("total_spent"))
            .limit(limit)
        ).all()
        return {
            "customers": [
                {
                    "customer_name": r.customer_name,
                    "customer_phone": r.customer_phone,
                    "total_spent": round(float(r.total_spent), 2),
                    "visit_count": int(r.visit_count),
                }
                for r in rows
            ]
        }

    if name == "get_churned_customers":
        threshold = int(args.get("days_threshold") or 10)
        all_tx = list(db_session.scalars(select(Transactions).where(Transactions.merchant_id == merchant_id)))

        by_customer: dict[str, list[Transactions]] = {}
        for tx in all_tx:
            by_customer.setdefault(tx.customer_name, []).append(tx)

        items = []
        for customer_name, txs in by_customer.items():
            if len(txs) < 3:
                continue
            txs.sort(key=lambda item: item.timestamp)
            last = txs[-1].timestamp
            days_ago = (datetime.now().date() - last.date()).days
            if days_ago <= threshold:
                continue
            avg_spend = sum(float(item.amount) for item in txs) / len(txs)
            udhaar = _compute_udhaar_balance(db_session, merchant_id, customer_name)
            udhaar_balance = udhaar[0]["net_balance"] if udhaar else 0.0
            items.append(
                {
                    "customer_name": customer_name,
                    "last_visit_days_ago": days_ago,
                    "avg_spend": round(avg_spend, 2),
                    "visit_count": len(txs),
                    "udhaar_balance": udhaar_balance,
                }
            )

        items.sort(key=lambda item: item["udhaar_balance"], reverse=True)
        return {"customers": items}

    if name == "log_udhaar":
        customer_name = str(args.get("customer_name") or "").strip()
        amount = float(args.get("amount") or 0)
        entry_type = str(args.get("type") or "GIVEN").upper()
        note = args.get("note")
        if not customer_name or amount <= 0:
            return {"logged": False, "message": "invalid_input"}

        db_session.add(
            UdhaarEntries(
                merchant_id=merchant_id,
                customer_name=customer_name,
                customer_phone=None,
                amount=amount,
                type="RECEIVED" if entry_type == "RECEIVED" else "GIVEN",
                note=note,
                date=datetime.now(IST).date(),
            )
        )
        db_session.commit()

        balances = _compute_udhaar_balance(db_session, merchant_id, customer_name)
        running_balance = balances[0]["net_balance"] if balances else 0.0
        return {
            "logged": True,
            "customer_name": customer_name,
            "amount": amount,
            "type": "RECEIVED" if entry_type == "RECEIVED" else "GIVEN",
            "running_balance": round(running_balance, 2),
            "message": f"{customer_name} ka total udhaar: ₹{running_balance:.2f}",
        }

    if name == "log_expense":
        amount = float(args.get("amount") or 0)
        category = str(args.get("category") or "GENERAL").upper()
        note = str(args.get("note") or "")
        if amount <= 0:
            return {"logged": False, "message": "invalid_amount"}

        today = datetime.now(IST).date()
        db_session.add(
            ExpenseEntries(
                merchant_id=merchant_id,
                amount=amount,
                category=category,
                note=note,
                date=today,
            )
        )
        db_session.commit()

        today_total = db_session.scalar(
            select(func.coalesce(func.sum(ExpenseEntries.amount), 0.0)).where(
                and_(
                    ExpenseEntries.merchant_id == merchant_id,
                    ExpenseEntries.date == today,
                )
            )
        )
        return {
            "logged": True,
            "amount": amount,
            "category": category,
            "today_total_expenses": round(float(today_total or 0.0), 2),
        }

    if name == "get_udhaar_summary":
        customer_name = args.get("customer_name")
        return {"items": _compute_udhaar_balance(db_session, merchant_id, customer_name)}

    if name == "get_morning_brief":
        today = datetime.now(IST).date()
        yesterday_start = datetime.combine(today - timedelta(days=1), datetime.min.time())
        yesterday_end = datetime.combine(today, datetime.min.time())

        y_rows = list(
            db_session.scalars(
                select(Transactions).where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.timestamp >= yesterday_start,
                        Transactions.timestamp < yesterday_end,
                    )
                )
            )
        )
        yesterday_total = sum(float(r.amount) for r in y_rows)

        same_weekday_rows = []
        for weeks_back in range(1, 5):
            anchor_day = today - timedelta(days=7 * weeks_back)
            start = datetime.combine(anchor_day, datetime.min.time())
            end = start + timedelta(days=1)
            rows = list(
                db_session.scalars(
                    select(Transactions).where(
                        and_(
                            Transactions.merchant_id == merchant_id,
                            Transactions.timestamp >= start,
                            Transactions.timestamp < end,
                        )
                    )
                )
            )
            same_weekday_rows.append(sum(float(r.amount) for r in rows))

        avg_same_weekday = sum(same_weekday_rows) / len(same_weekday_rows) if same_weekday_rows else 0.0
        churn = execute_tool("get_churned_customers", {"days_threshold": 10}, db_session, merchant_id).get("customers", [])[:3]
        udhaar = execute_tool("get_udhaar_summary", {}, db_session, merchant_id).get("items", [])[:3]

        day_last_week = today - timedelta(days=7)
        last_week_start = datetime.combine(day_last_week, datetime.min.time())
        last_week_end = last_week_start + timedelta(days=1)
        lw_rows = list(
            db_session.scalars(
                select(Transactions).where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.timestamp >= last_week_start,
                        Transactions.timestamp < last_week_end,
                    )
                )
            )
        )

        return {
            "yesterday_sales_total": round(yesterday_total, 2),
            "yesterday_transaction_count": len(y_rows),
            "same_day_last_week_total": round(sum(float(r.amount) for r in lw_rows), 2),
            "historical_avg_same_day_last_4_weeks": round(avg_same_weekday, 2),
            "top_churn_risk_customers": churn,
            "top_udhaar_dues": udhaar,
        }

    if name == "get_eod_summary":
        date_arg = str(args.get("date") or "today")
        if date_arg == "today":
            day = datetime.now(IST).date()
        else:
            try:
                day = datetime.fromisoformat(date_arg).date()
            except ValueError:
                day = datetime.now(IST).date()

        day_start = datetime.combine(day, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        tx_rows = list(
            db_session.scalars(
                select(Transactions).where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.timestamp >= day_start,
                        Transactions.timestamp < day_end,
                    )
                )
            )
        )
        exp_rows = list(
            db_session.scalars(
                select(ExpenseEntries).where(
                    and_(
                        ExpenseEntries.merchant_id == merchant_id,
                        ExpenseEntries.date == day,
                    )
                )
            )
        )
        udhaar_rows = list(
            db_session.scalars(
                select(UdhaarEntries).where(
                    and_(
                        UdhaarEntries.merchant_id == merchant_id,
                        UdhaarEntries.date == day,
                    )
                )
            )
        )

        income = sum(float(r.amount) for r in tx_rows)
        expenses = sum(float(r.amount) for r in exp_rows)
        udhaar_given = sum(float(r.amount) for r in udhaar_rows if r.type == "GIVEN")
        udhaar_received = sum(float(r.amount) for r in udhaar_rows if r.type == "RECEIVED")
        net = income + udhaar_received - expenses - udhaar_given

        largest_tx = None
        if tx_rows:
            tx = max(tx_rows, key=lambda item: float(item.amount))
            largest_tx = {
                "amount": float(tx.amount),
                "customer_name": tx.customer_name,
                "txn_ref": tx.transaction_ref,
            }

        all_prev_customers = set(
            db_session.scalars(
                select(Transactions.customer_phone).where(
                    and_(
                        Transactions.merchant_id == merchant_id,
                        Transactions.timestamp < day_start,
                    )
                )
            )
        )
        today_customers = {row.customer_phone for row in tx_rows}
        new_customer_count = len({phone for phone in today_customers if phone not in all_prev_customers})

        return {
            "date": day.isoformat(),
            "income": round(income, 2),
            "expenses": round(expenses, 2),
            "udhaar_given": round(udhaar_given, 2),
            "udhaar_received": round(udhaar_received, 2),
            "net": round(net, 2),
            "transaction_count": len(tx_rows),
            "largest_transaction": largest_tx,
            "new_customers": new_customer_count,
        }

    if name == "log_general_note":
        note = str(args.get("note") or "").strip()
        category = str(args.get("category") or "GENERAL").upper()
        if not note:
            return {"logged": False, "note_preview": ""}

        db_session.add(MerchantNotes(merchant_id=merchant_id, category=category, note=note))
        db_session.commit()
        return {
            "logged": True,
            "note_preview": note[:50],
        }

    return {"error": "unknown_tool", "tool": name}


def _intent_from_tools(tool_calls: list[str], input_type: str, is_morning: bool) -> str:
    called = set(tool_calls)
    if "search_payment" in called or input_type == "image":
        return "PAYMENT_VERIFY"
    if "get_morning_brief" in called or is_morning:
        return "MORNING_BRIEF"
    if "get_eod_summary" in called:
        return "EOD_BRIEF"
    if "log_udhaar" in called:
        return "UDHAAR_LOG"
    if "log_expense" in called:
        return "EXPENSE_LOG"
    if "search_customer" in called or "get_udhaar_summary" in called:
        return "CUSTOMER_QUERY"
    if "get_sales_summary" in called:
        return "SALES_QUERY"
    if "log_general_note" in called:
        return "GENERAL_NOTE"
    return "GENERAL"


def _check_if_needs_recheck(tool_results: list[dict]) -> bool:
    for event in tool_results:
        if event.get("name") != "search_payment":
            continue
        result = event.get("result") or {}
        if result.get("found"):
            continue
        minutes = int(result.get("minutes_since_receipt") or 0)
        if minutes < 10:
            return True
    return False


def _extract_payment_meta(tool_results: list[dict]) -> dict | None:
    for event in tool_results:
        if event.get("name") != "search_payment":
            continue
        args = event.get("args") or {}
        txn_ref = args.get("txn_ref")
        if txn_ref:
            return {
                "txn_ref": str(txn_ref),
                "amount": args.get("amount"),
            }
    return None


async def search_payment(db_session: Session, merchant_phone: str, txn_ref: str, amount: float | None = None) -> dict:
    merchant = _resolve_merchant(db_session, merchant_phone)
    if not merchant:
        return {"found": False, "txn_ref": txn_ref, "minutes_since_receipt": 0}
    return execute_tool("search_payment", {"txn_ref": txn_ref, "amount": amount}, db_session, merchant.id)


async def run_artha(
    merchant_phone: str,
    user_input: str,
    input_type: str,
    ocr_text: str | None = None,
    is_morning: bool = False,
    is_evening: bool = False,
    conversation_history: list | None = None,
    db_session: Session | None = None,
) -> dict:
    tool_names: list[str] = []
    tool_results: list[dict] = []

    try:
        if db_session is None:
            raise RuntimeError("db_session_missing")

        merchant = _resolve_merchant(db_session, merchant_phone)
        if not merchant:
            raise RuntimeError("merchant_missing")

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("openai_key_missing")

        client = AsyncOpenAI(api_key=api_key)

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        history = list(conversation_history or [])[-12:]
        for item in history:
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})

        if is_morning:
            morning_context = execute_tool("get_morning_brief", {}, db_session, merchant.id)
            tool_names.append("get_morning_brief")
            tool_results.append({"name": "get_morning_brief", "args": {}, "result": morning_context})
            messages.append(
                {
                    "role": "system",
                    "content": f"Morning brief context (tool output): {json.dumps(morning_context, ensure_ascii=True)}",
                }
            )

        user_message = (user_input or "").strip() or "Hi"
        if ocr_text:
            auto_utr, auto_amount = _extract_utr_and_amount(ocr_text)
            ocr_prefix = f"[OCR TEXT FROM IMAGE: {ocr_text}]"
            if auto_utr:
                ocr_prefix += f" [OCR CANDIDATE UTR: {auto_utr}]"
            if auto_amount is not None:
                ocr_prefix += f" [OCR CANDIDATE AMOUNT: {auto_amount}]"
            user_message = f"{ocr_prefix}\n{user_message}"

        messages.append({"role": "user", "content": user_message})

        async def _call_llm() -> Any:
            return await client.chat.completions.create(
                model="gpt-4o",
                messages=cast(Any, messages),
                tools=cast(Any, TOOLS),
                tool_choice="auto",
                temperature=0.3,
                max_tokens=600,
            )

        response = await _call_llm()
        iteration_count = 0
        last_message = response.choices[0].message

        while True:
            message = response.choices[0].message
            last_message = message
            if message.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [tool_call.model_dump() for tool_call in message.tool_calls],
                    }
                )

                for tool_call in message.tool_calls:
                    function_obj = getattr(tool_call, "function", None)
                    if not function_obj:
                        continue

                    tool_name = getattr(function_obj, "name", "")
                    raw_args = getattr(function_obj, "arguments", "{}")
                    try:
                        parsed_args = json.loads(raw_args or "{}")
                    except json.JSONDecodeError:
                        parsed_args = {}

                    result = execute_tool(tool_name, parsed_args, db_session, merchant.id)
                    tool_names.append(tool_name)
                    tool_results.append(
                        {
                            "name": tool_name,
                            "args": parsed_args,
                            "result": result,
                        }
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result, ensure_ascii=True),
                        }
                    )

                response = await _call_llm()
                iteration_count += 1
                if iteration_count >= 5:
                    break
            else:
                break

        final_text = (last_message.content or "").strip()
        if not final_text:
            raise RuntimeError("empty_final_response")

        intent = _intent_from_tools(tool_names, input_type=input_type, is_morning=is_morning)
        needs_recheck = _check_if_needs_recheck(tool_results)
        payment_meta = _extract_payment_meta(tool_results)

        return {
            "response_text": final_text,
            "response_type": "both" if intent in {"MORNING_BRIEF", "EOD_BRIEF"} else "text",
            "intent": intent,
            "tools_called": tool_names,
            "needs_recheck": needs_recheck,
            "payment_meta": payment_meta,
            "is_evening": is_evening,
        }

    except Exception as exc:
        logger.error("Agent error: %s", exc)
        return {
            "response_text": "Thoda busy hoon abhi, ek minute mein dobara try karo 🙏",
            "response_type": "text",
            "intent": "ERROR",
            "tools_called": tool_names,
            "needs_recheck": False,
            "payment_meta": None,
        }



async def run_artha_streaming(
    merchant_phone: str,
    user_input: str,
    input_type: str,
    ocr_text: str | None = None,
    is_morning: bool = False,
    is_evening: bool = False,
    conversation_history: list | None = None,
    db_session: Session | None = None,
):
    try:
        if db_session is None:
            yield f"data: {json.dumps({'type': 'error', 'content': 'db_session_missing'})}\n\n"
            return

        merchant = _resolve_merchant(db_session, merchant_phone)
        if not merchant:
            yield f"data: {json.dumps({'type': 'error', 'content': 'merchant_missing'})}\n\n"
            return

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        client = AsyncOpenAI(api_key=api_key)

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        history = list(conversation_history or [])[-12:]
        for item in history:
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})

        if is_morning:
            morning_context = execute_tool("get_morning_brief", {}, db_session, merchant.id)
            messages.append(
                {
                    "role": "system",
                    "content": f"Morning brief context (tool output): {json.dumps(morning_context, ensure_ascii=True)}",
                }
            )

        user_message = (user_input or "").strip() or "Hi"
        if ocr_text:
            auto_utr, auto_amount = _extract_utr_and_amount(ocr_text)
            ocr_prefix = f"[OCR TEXT FROM IMAGE: {ocr_text}]"
            if auto_utr:
                ocr_prefix += f" [OCR CANDIDATE UTR: {auto_utr}]"
            if auto_amount is not None:
                ocr_prefix += f" [OCR CANDIDATE AMOUNT: {auto_amount}]"
            user_message = f"{ocr_prefix}\n{user_message}"

        messages.append({"role": "user", "content": user_message})

        loop_count = 0
        while True:
            response_stream = await client.chat.completions.create(
                model="gpt-4o",
                messages=cast(Any, messages),
                tools=cast(Any, TOOLS),
                tool_choice="auto",
                temperature=0.3,
                max_tokens=600,
                stream=True,
            )

            content = ""
            tool_calls = {}

            async for chunk in response_stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content += delta.content
                    yield f"data: {json.dumps({'type': 'chunk', 'content': delta.content})}\n\n"

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls:
                            tool_calls[idx] = {"id": tc.id, "function": {"name": tc.function.name or "", "arguments": tc.function.arguments or ""}}
                        else:
                            if tc.function.name:
                                tool_calls[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls[idx]["function"]["arguments"] += tc.function.arguments

            assistant_msg = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content
            else:
                assistant_msg["content"] = None

            if tool_calls:
                assistant_tc = []
                for idx, tc in sorted(tool_calls.items()):
                    assistant_tc.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"]
                    })
                assistant_msg["tool_calls"] = assistant_tc
            
            messages.append(assistant_msg)

            if not tool_calls:
                break

            for idx, tc in sorted(tool_calls.items()):
                name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                yield f"data: {json.dumps({'type': 'tool_call', 'name': name, 'args': raw_args})}\n\n"
                
                try:
                    parsed_args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}

                result = execute_tool(name, parsed_args, db_session, merchant.id)
                res_str = json.dumps(result, ensure_ascii=True)
                yield f"data: {json.dumps({'type': 'tool_result', 'result': res_str})}\n\n"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": res_str,
                })

            loop_count += 1
            if loop_count >= 5:
                break

    except Exception as exc:
        logger.error(f"Agent streaming error: {exc}")
        yield f"data: {json.dumps({'type': 'error', 'content': 'Thoda busy hoon abhi, ek minute mein dobara try karo'})}\n\n"

