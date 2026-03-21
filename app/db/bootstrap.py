from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_artha_schema(engine: Engine) -> None:
    ddl_statements = [
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS owner_name VARCHAR(255)",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS location VARCHAR(255)",
        """
        CREATE TABLE IF NOT EXISTS udhaar_entries (
            id SERIAL PRIMARY KEY,
            merchant_id INTEGER NOT NULL REFERENCES merchants(id),
            customer_name VARCHAR(255) NOT NULL,
            customer_phone VARCHAR(20),
            amount DOUBLE PRECISION NOT NULL,
            type VARCHAR(20) NOT NULL,
            note TEXT,
            date DATE NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS expense_entries (
            id SERIAL PRIMARY KEY,
            merchant_id INTEGER NOT NULL REFERENCES merchants(id),
            amount DOUBLE PRECISION NOT NULL,
            category VARCHAR(30) NOT NULL,
            note TEXT,
            date DATE NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS merchant_notes (
            id SERIAL PRIMARY KEY,
            merchant_id INTEGER NOT NULL REFERENCES merchants(id),
            category VARCHAR(50) NOT NULL DEFAULT 'GENERAL',
            note TEXT NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS processed_webhook_messages (
            id SERIAL PRIMARY KEY,
            message_id VARCHAR(128) NOT NULL UNIQUE,
            phone VARCHAR(20),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """,
    ]

    with engine.begin() as conn:
        for stmt in ddl_statements:
            conn.execute(text(stmt))
