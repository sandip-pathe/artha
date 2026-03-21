from __future__ import annotations

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/payguard")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]

engine_kwargs: dict = {
    "future": True,
    "pool_pre_ping": True,
}

if DATABASE_URL.startswith("postgresql"):
    # Keep connection attempts short in container healthchecks.
    engine_kwargs["connect_args"] = {"connect_timeout": 3}

try:
    engine = create_engine(DATABASE_URL, **engine_kwargs)
except Exception:
    # Keep service bootable so /health can respond even if DB URL is malformed.
    engine = create_engine("sqlite:///./payguard_fallback.db", future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
