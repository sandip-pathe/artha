from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatSessions


def get_or_create_session(db: Session, phone: str) -> tuple[ChatSessions, bool]:
	session = db.scalar(select(ChatSessions).where(ChatSessions.phone == phone))
	if session:
		return session, False

	session = ChatSessions(phone=phone, state="NEW", context_json={})
	db.add(session)
	db.commit()
	db.refresh(session)
	return session, True


def set_pending_more(db: Session, phone: str, pending_text: str) -> None:
	session, _ = get_or_create_session(db, phone)
	context_json = dict(session.context_json or {})
	context_json["pending_more"] = pending_text
	session.context_json = context_json
	db.add(session)
	db.commit()


def pop_pending_more(db: Session, phone: str) -> str | None:
	session = db.scalar(select(ChatSessions).where(ChatSessions.phone == phone))
	if not session:
		return None

	context_json = dict(session.context_json or {})
	pending = context_json.pop("pending_more", None)
	session.context_json = context_json
	db.add(session)
	db.commit()
	return pending


def get_session_context(db: Session, phone: str) -> dict:
	session, _ = get_or_create_session(db, phone)
	return dict(session.context_json or {})


def update_session_context(db: Session, phone: str, context_json: dict) -> None:
	session, _ = get_or_create_session(db, phone)
	session.context_json = dict(context_json)
	db.add(session)
	db.commit()


def append_conversation_pair(db: Session, phone: str, user_text: str, assistant_text: str) -> None:
	session, _ = get_or_create_session(db, phone)
	context_json = dict(session.context_json or {})
	history = list(context_json.get("conversation_history", []))
	history.append({"role": "user", "content": user_text})
	history.append({"role": "assistant", "content": assistant_text})
	context_json["conversation_history"] = history[-12:]
	session.context_json = context_json
	db.add(session)
	db.commit()


def set_pending_recheck(db: Session, phone: str, pending: dict | None) -> None:
	session, _ = get_or_create_session(db, phone)
	context_json = dict(session.context_json or {})
	if pending is None:
		context_json.pop("pending_recheck", None)
	else:
		context_json["pending_recheck"] = pending
	session.context_json = context_json
	db.add(session)
	db.commit()


def get_pending_recheck(db: Session, phone: str) -> dict | None:
	session = db.scalar(select(ChatSessions).where(ChatSessions.phone == phone))
	if not session:
		return None
	context_json = dict(session.context_json or {})
	pending = context_json.get("pending_recheck")
	if isinstance(pending, dict):
		return pending
	return None
