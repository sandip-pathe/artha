from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Merchants(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upi_id: Mapped[str] = mapped_column(String(255), nullable=False)
    paytm_merchant_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    transactions: Mapped[list[Transactions]] = relationship("Transactions", back_populates="merchant", cascade="all, delete-orphan")
    fraud_checks: Mapped[list[FraudChecks]] = relationship("FraudChecks", back_populates="merchant", cascade="all, delete-orphan")
    fraud_reports: Mapped[list[FraudReports]] = relationship("FraudReports", back_populates="merchant", cascade="all, delete-orphan")
    udhaar_entries: Mapped[list[UdhaarEntries]] = relationship("UdhaarEntries", back_populates="merchant", cascade="all, delete-orphan")
    expense_entries: Mapped[list[ExpenseEntries]] = relationship("ExpenseEntries", back_populates="merchant", cascade="all, delete-orphan")
    notes: Mapped[list[MerchantNotes]] = relationship("MerchantNotes", back_populates="merchant", cascade="all, delete-orphan")


class Transactions(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    upi_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_ref: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    merchant: Mapped[Merchants] = relationship("Merchants", back_populates="transactions")


class FraudChecks(Base):
    __tablename__ = "fraud_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    layers_flagged: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    red_flags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_app: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transaction_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    merchant: Mapped[Merchants] = relationship("Merchants", back_populates="fraud_checks")
    reports: Mapped[list[FraudReports]] = relationship("FraudReports", back_populates="fraud_check", cascade="all, delete-orphan")


class FraudReports(Base):
    __tablename__ = "fraud_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fraud_check_id: Mapped[int] = mapped_column(ForeignKey("fraud_checks.id"), nullable=False, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    report_ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    fraud_check: Mapped[FraudChecks] = relationship("FraudChecks", back_populates="reports")
    merchant: Mapped[Merchants] = relationship("Merchants", back_populates="fraud_reports")


class ChatSessions(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="NEW")
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UdhaarEntries(Base):
    __tablename__ = "udhaar_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    merchant: Mapped[Merchants] = relationship("Merchants", back_populates="udhaar_entries")


class ExpenseEntries(Base):
    __tablename__ = "expense_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    merchant: Mapped[Merchants] = relationship("Merchants", back_populates="expense_entries")


class MerchantNotes(Base):
    __tablename__ = "merchant_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="GENERAL")
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    merchant: Mapped[Merchants] = relationship("Merchants", back_populates="notes")


class ProcessedWebhookMessages(Base):
    __tablename__ = "processed_webhook_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
