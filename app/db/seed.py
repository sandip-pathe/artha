from __future__ import annotations

import random
import string
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.db.bootstrap import ensure_artha_schema
from app.db.models import Base, ExpenseEntries, Merchants, UdhaarEntries, Transactions
from app.db.session import SessionLocal, engine


DEMO_MERCHANT_PHONE = "918767394523"
LEGACY_DEMO_MERCHANT_PHONE = "919876543210"


CUSTOMERS: list[dict[str, str]] = [
    {"name": "Priya Mehta", "phone": "919110000001", "segment": "regular", "min": "50", "max": "200"},
    {"name": "Suresh Yadav", "phone": "919110000002", "segment": "regular", "min": "150", "max": "400"},
    {"name": "Kamla Bai", "phone": "919110000003", "segment": "regular", "min": "400", "max": "900"},
    {"name": "Raju Delivery", "phone": "919110000004", "segment": "regular", "min": "30", "max": "100"},
    {"name": "Anita Desai", "phone": "919110000005", "segment": "semi", "min": "100", "max": "350"},
    {"name": "Mohammed Rafiq", "phone": "919110000006", "segment": "semi", "min": "120", "max": "380"},
    {"name": "Sunita Patil", "phone": "919110000007", "segment": "semi", "min": "140", "max": "420"},
    {"name": "Deepak Joshi", "phone": "919110000008", "segment": "semi", "min": "90", "max": "320"},
    {"name": "Vikram Singh", "phone": "919110000009", "segment": "occasional", "min": "120", "max": "500"},
    {"name": "Meena Kumari", "phone": "919110000010", "segment": "occasional", "min": "80", "max": "380"},
    {"name": "Arun Tiwari", "phone": "919110000011", "segment": "occasional", "min": "150", "max": "600"},
    {"name": "Pooja Shah", "phone": "919110000012", "segment": "occasional", "min": "70", "max": "300"},
    {"name": "Ramesh Gupta", "phone": "919110000013", "segment": "churned", "min": "300", "max": "500"},
    {"name": "Kavita Nair", "phone": "919110000014", "segment": "churned", "min": "140", "max": "350"},
    {"name": "Santosh Kumar", "phone": "919110000015", "segment": "churned", "min": "40", "max": "140"},
]


def customer_map() -> dict[str, dict[str, str]]:
    return {c["name"]: c for c in CUSTOMERS}


def _upi_app_and_ref(ts: datetime) -> tuple[str, str]:
    app = random.choices(["paytm", "phonepe", "gpay"], weights=[60, 25, 15], k=1)[0]
    if app == "paytm":
        return app, "".join(random.choices(string.digits, k=16))
    if app == "phonepe":
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return app, f"T{ts.strftime('%y%m%d%H%M%S')}{suffix}"
    body = "".join(random.choices(string.ascii_uppercase + string.digits, k=22))
    return app, body


def _weighted_time_for_day(day: datetime) -> datetime:
    bucket = random.choices(
        ["morning", "lunch", "afternoon", "evening", "night"],
        weights=[25, 10, 20, 40, 5],
        k=1,
    )[0]
    if bucket == "morning":
        hour = random.randint(7, 9)
    elif bucket == "lunch":
        hour = random.randint(10, 11)
    elif bucket == "afternoon":
        hour = random.randint(12, 15)
    elif bucket == "evening":
        hour = random.randint(16, 19)
    else:
        hour = random.randint(20, 21)
    return day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59), microsecond=0)


def _day_total_range(day: datetime) -> tuple[int, int]:
    weekday = day.weekday()
    if weekday == 0:
        return 2000, 2800
    if weekday in [1, 2, 3]:
        return 2800, 3800
    if weekday == 4:
        return 3500, 4500
    if weekday == 5:
        return 5000, 7000
    return 4000, 5500


def _pick_customer() -> dict[str, str]:
    weights = []
    for c in CUSTOMERS:
        if c["segment"] == "regular":
            weights.append(9)
        elif c["segment"] == "semi":
            weights.append(5)
        elif c["segment"] == "occasional":
            weights.append(2)
        else:
            weights.append(0)
    return random.choices(CUSTOMERS, weights=weights, k=1)[0]


def _random_amount_for_customer(c: dict[str, str]) -> float:
    low = int(c["min"])
    high = int(c["max"])
    return float(random.randint(low, high))


def _tx_record(merchant_id: int, c: dict[str, str], ts: datetime, amount: float, txn_ref: str | None = None) -> Transactions:
    app_name, generated_ref = _upi_app_and_ref(ts)
    tx_ref = txn_ref or generated_ref
    return Transactions(
        merchant_id=merchant_id,
        amount=float(amount),
        customer_name=c["name"],
        customer_phone=c["phone"],
        upi_id=f"{c['name'].lower().replace(' ', '.')}@{app_name}",
        transaction_ref=tx_ref,
        timestamp=ts,
        status="SUCCESS",
    )


def _build_14_day_transactions(merchant_id: int, now: datetime) -> list[Transactions]:
    txs: list[Transactions] = []
    for offset in range(14, 0, -1):
        day = (now - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        low, high = _day_total_range(day)
        day_target = random.randint(low, high)
        day_total = 0.0
        safety = 0
        while day_total < day_target and safety < 120:
            safety += 1
            c = _pick_customer()
            ts = _weighted_time_for_day(day)
            amount = _random_amount_for_customer(c)
            txs.append(_tx_record(merchant_id, c, ts, amount))
            day_total += amount
    return txs


def _build_churn_history(merchant_id: int, now: datetime) -> list[Transactions]:
    cmap = customer_map()
    anchors = [
        ("Ramesh Gupta", 15, 4),
        ("Kavita Nair", 12, 5),
        ("Santosh Kumar", 18, 6),
    ]
    txs: list[Transactions] = []
    for name, last_seen_days, visits in anchors:
        c = cmap[name]
        for i in range(visits):
            spread = last_seen_days + random.randint(1, 10) if i < visits - 1 else last_seen_days
            ts = (now - timedelta(days=spread)).replace(hour=random.randint(9, 20), minute=random.randint(0, 59), second=0, microsecond=0)
            amount = _random_amount_for_customer(c)
            txs.append(_tx_record(merchant_id, c, ts, amount))
    return txs


def _build_demo_transactions(merchant_id: int, now: datetime) -> list[Transactions]:
    cmap = customer_map()
    today = now.replace(second=0, microsecond=0)
    yesterday = (now - timedelta(days=1)).replace(second=0, microsecond=0)
    return [
        _tx_record(
            merchant_id,
            cmap["Suresh Yadav"],
            today.replace(hour=15, minute=30),
            450.0,
            txn_ref="T260321153045DEMO0001",
        ),
        _tx_record(
            merchant_id,
            cmap["Priya Mehta"],
            today.replace(hour=16, minute=0),
            280.0,
            txn_ref="T260321160022DEMO0002",
        ),
        _tx_record(
            merchant_id,
            cmap["Kamla Bai"],
            yesterday.replace(hour=18, minute=15),
            1200.0,
            txn_ref="4721839204751999",
        ),
    ]


def _build_udhaar_entries(merchant_id: int, now: datetime) -> list[UdhaarEntries]:
    cmap = customer_map()
    entries = [
        ("Suresh Yadav", "GIVEN", 350.0, "Ghar tak monthly ration", 5),
        ("Ramesh Gupta", "GIVEN", 600.0, "Weekly udhaar pending", 16),
        ("Kavita Nair", "GIVEN", 200.0, "Snacks and household items", 13),
        ("Deepak Joshi", "RECEIVED", 150.0, "Partial udhaar repayment", 3),
        ("Mohammed Rafiq", "GIVEN", 450.0, "Bulk grocery on credit", 8),
    ]
    out: list[UdhaarEntries] = []
    for name, udhaar_type, amount, note, days_ago in entries:
        c = cmap[name]
        dt = (now - timedelta(days=days_ago)).date()
        out.append(
            UdhaarEntries(
                merchant_id=merchant_id,
                customer_name=name,
                customer_phone=c["phone"],
                amount=amount,
                type=udhaar_type,
                note=note,
                date=dt,
            )
        )
    return out


def _build_expenses(merchant_id: int, now: datetime) -> list[ExpenseEntries]:
    items = [
        (7200.0, "STOCK", "Atta, chawal, dal wholesale lot", 13),
        (4300.0, "STOCK", "Cooking oil and masala refill", 11),
        (2650.0, "STOCK", "Dairy and eggs restock", 9),
        (8100.0, "STOCK", "Monthly staples restock", 6),
        (3200.0, "STOCK", "Beverages and snacks", 3),
        (1200.0, "ELECTRICITY", "Monthly electricity bill", 7),
        (420.0, "TRANSPORT", "Tempo delivery charges", 12),
        (360.0, "TRANSPORT", "Market pickup auto", 8),
        (480.0, "TRANSPORT", "Wholesale transport", 2),
        (250.0, "MISC", "Packaging and carry bags", 4),
    ]
    out: list[ExpenseEntries] = []
    for amount, category, note, days_ago in items:
        out.append(
            ExpenseEntries(
                merchant_id=merchant_id,
                amount=amount,
                category=category,
                note=note,
                date=(now - timedelta(days=days_ago)).date(),
            )
        )
    return out


def seed() -> None:
    random.seed(26032026)
    now = datetime.now()
    ensure_artha_schema(engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        merchant = db.scalar(select(Merchants).where(Merchants.phone == DEMO_MERCHANT_PHONE))
        if not merchant:
            merchant = db.scalar(select(Merchants).where(Merchants.phone == LEGACY_DEMO_MERCHANT_PHONE))
            if merchant:
                merchant.phone = DEMO_MERCHANT_PHONE
                db.add(merchant)
                db.commit()
                db.refresh(merchant)
        if merchant:
            merchant.name = "Sharma General Store"
            merchant.owner_name = "Rajiv Sharma"
            merchant.upi_id = "rajiv.sharma@paytm"
            merchant.location = "Pune, Maharashtra"
            merchant.paytm_merchant_id = "PTM_SHARMA_2024"
            db.add(merchant)
            db.flush()

            has_demo = db.scalar(
                select(Transactions.id).where(
                    Transactions.merchant_id == merchant.id,
                    Transactions.transaction_ref == "T260321153045DEMO0001",
                )
            )
            ud_count = db.scalar(select(UdhaarEntries.id).where(UdhaarEntries.merchant_id == merchant.id).limit(1))
            expense_count = db.scalar(select(ExpenseEntries.id).where(ExpenseEntries.merchant_id == merchant.id).limit(1))

            if has_demo and ud_count and expense_count:
                db.commit()
                print("Seed skipped: Artha demo dataset already exists")
                return

            db.execute(delete(Transactions).where(Transactions.merchant_id == merchant.id))
            db.execute(delete(UdhaarEntries).where(UdhaarEntries.merchant_id == merchant.id))
            db.execute(delete(ExpenseEntries).where(ExpenseEntries.merchant_id == merchant.id))
            db.commit()
        else:
            merchant = Merchants(
                phone=DEMO_MERCHANT_PHONE,
                name="Sharma General Store",
                owner_name="Rajiv Sharma",
                upi_id="rajiv.sharma@paytm",
                location="Pune, Maharashtra",
                paytm_merchant_id="PTM_SHARMA_2024",
            )
            db.add(merchant)
            db.flush()

        transactions: list[Transactions] = []
        transactions.extend(_build_14_day_transactions(merchant.id, now))
        transactions.extend(_build_churn_history(merchant.id, now))
        transactions.extend(_build_demo_transactions(merchant.id, now))

        by_ref: dict[str, Transactions] = {}
        for tx in sorted(transactions, key=lambda x: x.timestamp):
            by_ref[tx.transaction_ref] = tx
        final_transactions = list(by_ref.values())

        udhaar_entries = _build_udhaar_entries(merchant.id, now)
        expenses = _build_expenses(merchant.id, now)

        db.add_all(final_transactions)
        db.add_all(udhaar_entries)
        db.add_all(expenses)
        db.commit()

        print(
            f"Artha seed complete: {len(final_transactions)} transactions, 15 customers, "
            f"{len(udhaar_entries)} udhaar entries, {len(expenses)} expenses"
        )


if __name__ == "__main__":
    seed()
