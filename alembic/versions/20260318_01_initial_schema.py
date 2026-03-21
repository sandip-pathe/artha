"""initial schema

Revision ID: 20260318_01
Revises:
Create Date: 2026-03-18 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260318_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("upi_id", sa.String(length=255), nullable=False),
        sa.Column("paytm_merchant_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index(op.f("ix_merchants_id"), "merchants", ["id"], unique=False)
    op.create_index(op.f("ix_merchants_phone"), "merchants", ["phone"], unique=False)

    op.create_table(
        "whatsapp_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index(op.f("ix_whatsapp_sessions_id"), "whatsapp_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_whatsapp_sessions_phone"), "whatsapp_sessions", ["phone"], unique=False)

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("customer_phone", sa.String(length=20), nullable=False),
        sa.Column("upi_id", sa.String(length=255), nullable=False),
        sa.Column("transaction_ref", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_ref"),
    )
    op.create_index(op.f("ix_transactions_id"), "transactions", ["id"], unique=False)
    op.create_index(op.f("ix_transactions_merchant_id"), "transactions", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_transactions_timestamp"), "transactions", ["timestamp"], unique=False)

    op.create_table(
        "fraud_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("layers_flagged", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("red_flags", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("raw_amount", sa.Float(), nullable=True),
        sa.Column("payment_app", sa.String(length=50), nullable=True),
        sa.Column("transaction_ref", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fraud_checks_id"), "fraud_checks", ["id"], unique=False)
    op.create_index(op.f("ix_fraud_checks_merchant_id"), "fraud_checks", ["merchant_id"], unique=False)

    op.create_table(
        "fraud_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fraud_check_id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("report_ref", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fraud_check_id"], ["fraud_checks.id"]),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_ref"),
    )
    op.create_index(op.f("ix_fraud_reports_fraud_check_id"), "fraud_reports", ["fraud_check_id"], unique=False)
    op.create_index(op.f("ix_fraud_reports_id"), "fraud_reports", ["id"], unique=False)
    op.create_index(op.f("ix_fraud_reports_merchant_id"), "fraud_reports", ["merchant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_fraud_reports_merchant_id"), table_name="fraud_reports")
    op.drop_index(op.f("ix_fraud_reports_id"), table_name="fraud_reports")
    op.drop_index(op.f("ix_fraud_reports_fraud_check_id"), table_name="fraud_reports")
    op.drop_table("fraud_reports")

    op.drop_index(op.f("ix_fraud_checks_merchant_id"), table_name="fraud_checks")
    op.drop_index(op.f("ix_fraud_checks_id"), table_name="fraud_checks")
    op.drop_table("fraud_checks")

    op.drop_index(op.f("ix_transactions_timestamp"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_merchant_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_id"), table_name="transactions")
    op.drop_table("transactions")

    op.drop_index(op.f("ix_whatsapp_sessions_phone"), table_name="whatsapp_sessions")
    op.drop_index(op.f("ix_whatsapp_sessions_id"), table_name="whatsapp_sessions")
    op.drop_table("whatsapp_sessions")

    op.drop_index(op.f("ix_merchants_phone"), table_name="merchants")
    op.drop_index(op.f("ix_merchants_id"), table_name="merchants")
    op.drop_table("merchants")
