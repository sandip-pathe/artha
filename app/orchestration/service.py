from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, TypedDict, cast

from openai import AsyncOpenAI
from sqlalchemy import select

from app.agent import SYSTEM_PROMPT, TOOLS, _extract_utr_and_amount, execute_tool
from app.db.models import Merchants
from app.db.session import SessionLocal
from app.metrics import metrics_store
from app.orchestration.cache import SemanticCache
from app.orchestration.state import GraphState, IntentPlan
from app.sessions import get_or_create_session, get_session_context

logger = logging.getLogger(__name__)

try:
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver  # type: ignore
except Exception:  # pragma: no cover
    AsyncRedisSaver = None  # type: ignore


class ChatResult(TypedDict):
    response_text: str
    intent: str
    tools_called: list[str]
    node_timings_ms: dict[str, float]
    cache_hit: bool


class ChatStreamEvent(TypedDict, total=False):
    type: str
    content: str
    name: str
    args: str
    result: str
    node: str


_OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
_PLANNER_MODEL = os.getenv("ARTHA_PLANNER_MODEL", "gpt-4o-mini")
_RESPONSE_MODEL = os.getenv("ARTHA_RESPONSE_MODEL", "gpt-4o")

_client = AsyncOpenAI(api_key=_OPENAI_KEY) if _OPENAI_KEY else None
_semantic_cache = SemanticCache()
_graph = None
GREETING_PATTERN = re.compile(
    r"^(hi+|hello|hey|namaste|kem cho|kya haal|good\s?(morning|evening|night)|"
    r"ok|okay|thanks|shukriya|dhanyawad|theek hai)[\s!.?]*$",
    re.IGNORECASE,
)


def _resolve_merchant_id(phone: str) -> int | None:
    with SessionLocal() as db:
        merchant = db.scalar(select(Merchants).where(Merchants.phone == phone))
        if merchant:
            return int(merchant.id)
        fallback = db.scalar(select(Merchants).order_by(Merchants.id).limit(1))
        return int(fallback.id) if fallback else None


def _tool_names() -> list[str]:
    names: list[str] = []
    for t in TOOLS:
        fn = t.get("function") or {}
        name = str(fn.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _tool_description_blob() -> str:
    lines: list[str] = []
    for t in TOOLS:
        fn = t.get("function") or {}
        name = str(fn.get("name") or "").strip()
        description = str(fn.get("description") or "").strip()
        if name:
            lines.append(f"- {name}: {description}")
    return "\n".join(lines)


_INTENT_PLANNER_PROMPT = (
    "You are an intent planner for a business AI assistant.\n"
    "Return STRICT JSON only with keys: intent, entities, tools_required, response_language, response_format, confidence, clarification_question.\n"
    "If confidence < 0.7, clarification_question must be non-empty and tools_required should be [].\n"
    "Available tools:\n"
    f"{_tool_description_blob()}\n"
    "Rules:\n"
    "- Do not hallucinate unavailable tools.\n"
    "- Prefer concise plans.\n"
    "- response_format in: voice,text,table,chart\n"
)


def _is_fast_path_message(message: str, input_type: str, ocr_text: str | None) -> bool:
    if input_type != "text" or (ocr_text and ocr_text.strip()):
        return False
    cleaned_msg = (message or "").strip().lower()
    if not cleaned_msg or len(cleaned_msg.split()) > 4:
        return False
    return bool(GREETING_PATTERN.match(cleaned_msg))


async def _fast_path_reply(message: str) -> str:
    if not _client:
        return "Namaste, main Artha hoon. Boliye kaise madad kar sakta hoon?"

    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=cast(
            Any,
            [
                {
                    "role": "system",
                    "content": "You are Artha, a helpful merchant assistant. Reply warmly in Hinglish. Keep it under 2 sentences.",
                },
                {"role": "user", "content": message},
            ],
        ),
        temperature=0.3,
        max_tokens=80,
    )
    return (response.choices[0].message.content or "").strip() or "Namaste, main Artha hoon. Kaise madad karun?"


def _parse_plan(raw: str) -> IntentPlan:
    fallback: IntentPlan = {
        "intent": "general_query",
        "entities": {},
        "tools_required": [],
        "response_language": "hinglish",
        "response_format": "text",
        "confidence": 0.5,
        "clarification_question": "Aap exact kya dekhna chahte ho?",
    }
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return fallback
        entities_raw = data.get("entities")
        entities = entities_raw if isinstance(entities_raw, dict) else {}
        tools_required = data.get("tools_required") or []
        if not isinstance(tools_required, list):
            tools_required = []
        parsed: IntentPlan = {
            "intent": str(data.get("intent") or fallback["intent"]),
            "entities": entities,
            "tools_required": [str(t) for t in tools_required if str(t) in _tool_names()],
            "response_language": str(data.get("response_language") or "hinglish"),
            "response_format": str(data.get("response_format") or "text"),
            "confidence": float(data.get("confidence") or 0.0),
            "clarification_question": data.get("clarification_question") if data.get("clarification_question") else None,
        }
        return parsed
    except Exception:
        return fallback


def _build_tool_args(tool_name: str, state: GraphState) -> dict[str, Any]:
    entities = (state.get("intent_plan") or {}).get("entities") or {}
    raw_text = state.get("normalized_text", "")
    ocr_text = state.get("ocr_text") or ""

    if tool_name == "get_sales_summary":
        period = str(entities.get("time_period") or "today")
        if period not in {"today", "yesterday", "this_week", "last_week", "this_month"}:
            period = "today"
        return {"period": period}

    if tool_name == "search_payment":
        txn_ref = str(entities.get("txn_ref") or "").strip()
        amount = entities.get("amount")
        if not txn_ref:
            extracted_ref, extracted_amount = _extract_utr_and_amount(f"{ocr_text}\n{raw_text}")
            txn_ref = extracted_ref or ""
            if amount is None:
                amount = extracted_amount
        args: dict[str, Any] = {"txn_ref": txn_ref}
        if amount is not None:
            args["amount"] = amount
        return args

    if tool_name == "search_customer":
        name = str(entities.get("customer_name") or "").strip()
        if not name:
            name = raw_text.split(" ")[0] if raw_text else ""
        return {"name": name}

    if tool_name == "get_top_customers":
        return {"limit": int(entities.get("limit") or 5)}

    if tool_name == "get_churned_customers":
        return {"days_threshold": int(entities.get("days_threshold") or 10)}

    if tool_name == "log_udhaar":
        return {
            "customer_name": str(entities.get("customer_name") or "Unknown"),
            "amount": float(entities.get("amount") or 0.0),
            "type": str(entities.get("type") or "GIVEN").upper(),
            "note": str(entities.get("note") or ""),
        }

    if tool_name == "log_expense":
        return {
            "amount": float(entities.get("amount") or 0.0),
            "category": str(entities.get("category") or "GENERAL"),
            "note": str(entities.get("note") or raw_text),
        }

    if tool_name == "get_udhaar_summary":
        customer_name = entities.get("customer_name")
        return {"customer_name": str(customer_name)} if customer_name else {}

    if tool_name == "get_eod_summary":
        return {"date": str(entities.get("date") or "today")}

    if tool_name == "log_general_note":
        return {"note": raw_text, "category": str(entities.get("category") or "GENERAL")}

    return {}


def _timed(name: str, fn):
    async def wrapped(state: GraphState) -> GraphState:
        start = time.perf_counter()
        update = await fn(state)
        elapsed_ms = (time.perf_counter() - start) * 1000
        node_timings = dict(state.get("node_timings_ms") or {})
        node_timings[name] = round(elapsed_ms, 2)
        merged = dict(state)
        merged.update(update)
        merged["node_timings_ms"] = node_timings
        return cast(GraphState, merged)

    return wrapped


async def _node_normalize_input(state: GraphState) -> GraphState:
    text = (state.get("raw_text") or "").strip()
    ocr_text = (state.get("ocr_text") or "").strip()
    normalized = text
    if ocr_text:
        normalized = f"[OCR]\n{ocr_text}\n\n[USER]\n{text}".strip()
    return {"normalized_text": normalized}


async def _node_context_loader(state: GraphState) -> GraphState:
    phone = state.get("merchant_phone", "")
    with SessionLocal() as db:
        get_or_create_session(db, phone)
        session_context = get_session_context(db, phone)
    history = list(session_context.get("conversation_history", []))[-12:]
    merchant_id = _resolve_merchant_id(phone)
    return {"context": {"history": history, "merchant_id": merchant_id}}


async def _node_intent_planner(state: GraphState) -> GraphState:
    if not _client:
        plan = _parse_plan("{}")
    else:
        resp = await _client.chat.completions.create(
            model=_PLANNER_MODEL,
            response_format={"type": "json_object"},
            temperature=0.1,
            messages=cast(
                Any,
                [
                {"role": "system", "content": _INTENT_PLANNER_PROMPT},
                {"role": "user", "content": state.get("normalized_text", "")},
                ],
            ),
        )
        content = (resp.choices[0].message.content or "{}").strip()
        plan = _parse_plan(content)
    needs_clarification = float(plan.get("confidence") or 0.0) < 0.7
    return {
        "intent_plan": plan,
        "needs_clarification": needs_clarification,
        "clarification_question": plan.get("clarification_question") if needs_clarification else None,
    }


async def _node_clarification(state: GraphState) -> GraphState:
    q = state.get("clarification_question") or "Aap thoda aur clear kar sakte ho?"
    return {
        "response_text": q,
        "tools_called": [],
        "tool_results": [],
    }


async def _run_tool(tool_name: str, args: dict[str, Any], merchant_id: int) -> dict[str, Any]:
    def _execute() -> dict[str, Any]:
        with SessionLocal() as db:
            result = execute_tool(tool_name, args, db, merchant_id)
            return {
                "name": tool_name,
                "args": args,
                "result": result,
            }

    return await asyncio.to_thread(_execute)


async def _node_tool_executor(state: GraphState) -> GraphState:
    plan = state.get("intent_plan") or {}
    merchant_id = int(((state.get("context") or {}).get("merchant_id") or 0))
    tools_required = list(plan.get("tools_required") or [])

    if not tools_required or merchant_id <= 0:
        return {"tools_called": [], "tool_results": []}

    calls: list[tuple[str, dict[str, Any]]] = []
    for tool_name in tools_required:
        calls.append((tool_name, _build_tool_args(tool_name, state)))

    results = await asyncio.gather(*[_run_tool(name, args, merchant_id) for name, args in calls])

    return {
        "tools_called": [x["name"] for x in results],
        "tool_results": results,
    }


def _route_after_planner(state: GraphState) -> str:
    if state.get("needs_clarification"):
        return "clarification"
    plan = state.get("intent_plan") or {}
    if plan.get("tools_required"):
        return "tool_executor"
    return "finalize"


async def _node_finalize_without_tools(state: GraphState) -> GraphState:
    return {"tools_called": [], "tool_results": []}


async def _build_graph_once():
    global _graph
    if _graph is not None:
        return _graph

    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(GraphState)
    builder.add_node("normalizer", _timed("normalizer", _node_normalize_input))
    builder.add_node("context_loader", _timed("context_loader", _node_context_loader))
    builder.add_node("intent_planner", _timed("intent_planner", _node_intent_planner))
    builder.add_node("clarification", _timed("clarification", _node_clarification))
    builder.add_node("tool_executor", _timed("tool_executor", _node_tool_executor))
    builder.add_node("finalize", _timed("finalize", _node_finalize_without_tools))

    builder.add_edge(START, "normalizer")
    builder.add_edge("normalizer", "context_loader")
    builder.add_edge("context_loader", "intent_planner")
    builder.add_conditional_edges(
        "intent_planner",
        _route_after_planner,
        {
            "clarification": "clarification",
            "tool_executor": "tool_executor",
            "finalize": "finalize",
        },
    )
    builder.add_edge("clarification", END)
    builder.add_edge("tool_executor", END)
    builder.add_edge("finalize", END)

    checkpointer = None
    if AsyncRedisSaver is not None:
        redis_url = (os.getenv("REDIS_URL", "") or "").strip()
        # Only enable Redis checkpointing when an explicit REDIS_URL is provided.
        if redis_url:
            try:
                checkpointer = AsyncRedisSaver.from_conn_string(redis_url)
            except Exception:
                checkpointer = None

    _graph = builder.compile(checkpointer=checkpointer)
    return _graph


async def _format_response_text(state: GraphState) -> str:
    if state.get("needs_clarification"):
        return state.get("clarification_question") or "Aap thoda aur clear kar sakte ho?"

    if not _client:
        return "OpenAI key missing."

    history = ((state.get("context") or {}).get("history") or [])[-12:]
    tool_results = state.get("tool_results") or []

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": state.get("normalized_text", "")})
    if tool_results:
        messages.append(
            {
                "role": "system",
                "content": f"Tool results JSON: {json.dumps(tool_results, ensure_ascii=True)}",
            }
        )

    response = await _client.chat.completions.create(
        model=_RESPONSE_MODEL,
        temperature=0.25,
        messages=cast(Any, messages),
    )
    return (response.choices[0].message.content or "").strip() or "Thoda busy hoon, 1 minute baad try karo."


async def _stream_response_text(state: GraphState) -> AsyncIterator[ChatStreamEvent]:
    if state.get("needs_clarification"):
        yield {"type": "chunk", "content": state.get("clarification_question") or "Aap thoda aur clear kar sakte ho?"}
        return

    if not _client:
        yield {"type": "error", "content": "OpenAI key missing."}
        return

    history = ((state.get("context") or {}).get("history") or [])[-12:]
    tool_results = state.get("tool_results") or []
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": state.get("normalized_text", "")})
    if tool_results:
        messages.append({"role": "system", "content": f"Tool results JSON: {json.dumps(tool_results, ensure_ascii=True)}"})

    stream = await _client.chat.completions.create(
        model=_RESPONSE_MODEL,
        temperature=0.25,
        messages=cast(Any, messages),
        stream=True,
    )

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield {"type": "chunk", "content": delta.content}


async def _run_graph(state: GraphState) -> GraphState:
    graph = await _build_graph_once()
    session_id = state.get("session_id") or str(uuid.uuid4())
    timeout_s = float(os.getenv("ARTHA_GRAPH_TIMEOUT_SECONDS", "20"))
    out = await asyncio.wait_for(
        graph.ainvoke(state, config={"configurable": {"thread_id": session_id}}),
        timeout=timeout_s,
    )
    return out


async def run_langgraph_chat(
    phone: str,
    message: str,
    input_type: str = "text",
    ocr_text: str | None = None,
    session_id: str | None = None,
) -> ChatResult:
    request_start = time.perf_counter()
    session_id = session_id or phone
    merchant_id = _resolve_merchant_id(phone)
    if merchant_id is None:
        return {
            "response_text": "Merchant not found.",
            "intent": "error",
            "tools_called": [],
            "node_timings_ms": {},
            "cache_hit": False,
        }

    cache_hit = await _semantic_cache.lookup(merchant_id=merchant_id, message=message, threshold=0.92)
    if cache_hit and cache_hit.get("response_text"):
        total_latency_ms = round((time.perf_counter() - request_start) * 1000, 2)
        await metrics_store.record(
            {
                "session_id": session_id,
                "pipeline_used": "langgraph",
                "total_latency_ms": total_latency_ms,
                "node_durations_ms": {},
                "cache_hit": True,
            }
        )
        return {
            "response_text": str(cache_hit.get("response_text")),
            "intent": "semantic_cache_hit",
            "tools_called": [],
            "node_timings_ms": {},
            "cache_hit": True,
        }

    if _is_fast_path_message(message=message, input_type=input_type, ocr_text=ocr_text):
        fast_start = time.perf_counter()
        response_text = await _fast_path_reply(message)
        fast_ms = round((time.perf_counter() - fast_start) * 1000, 2)

        await _semantic_cache.store(merchant_id=merchant_id, message=message, response_text=response_text)
        await metrics_store.record(
            {
                "session_id": session_id,
                "pipeline_used": "langgraph_fast_path",
                "total_latency_ms": round((time.perf_counter() - request_start) * 1000, 2),
                "node_durations_ms": {"fast_path_llm": fast_ms},
                "cache_hit": False,
            }
        )
        return {
            "response_text": response_text,
            "intent": "fast_path_greeting",
            "tools_called": [],
            "node_timings_ms": {"fast_path_llm": fast_ms},
            "cache_hit": False,
        }

    state: GraphState = {
        "session_id": session_id,
        "merchant_phone": phone,
        "input_type": input_type,
        "raw_text": message,
        "ocr_text": ocr_text,
        "node_timings_ms": {},
    }
    try:
        graph_out = await _run_graph(state)
    except asyncio.TimeoutError:
        return {
            "response_text": "System slow chal raha hai. 30 second baad phir try karo.",
            "intent": "timeout",
            "tools_called": [],
            "node_timings_ms": {},
            "cache_hit": False,
        }
    except Exception:
        logger.exception("run_langgraph_chat failed")
        return {
            "response_text": "Abhi system issue aa gaya. Ek baar phir try karo.",
            "intent": "error",
            "tools_called": [],
            "node_timings_ms": {},
            "cache_hit": False,
        }

    fmt_start = time.perf_counter()
    response_text = await _format_response_text(graph_out)
    node_timings = dict(graph_out.get("node_timings_ms") or {})
    node_timings["response_formatter"] = round((time.perf_counter() - fmt_start) * 1000, 2)

    await _semantic_cache.store(merchant_id=merchant_id, message=message, response_text=response_text)

    total_latency_ms = round((time.perf_counter() - request_start) * 1000, 2)
    await metrics_store.record(
        {
            "session_id": session_id,
            "pipeline_used": "langgraph",
            "total_latency_ms": total_latency_ms,
            "node_durations_ms": node_timings,
            "cache_hit": False,
        }
    )

    return {
        "response_text": response_text,
        "intent": (graph_out.get("intent_plan") or {}).get("intent") or "general_query",
        "tools_called": list(graph_out.get("tools_called") or []),
        "node_timings_ms": node_timings,
        "cache_hit": False,
    }


async def stream_langgraph_chat(
    phone: str,
    message: str,
    input_type: str = "text",
    ocr_text: str | None = None,
    session_id: str | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    request_start = time.perf_counter()
    session_id = session_id or phone
    merchant_id = _resolve_merchant_id(phone)
    if merchant_id is None:
        yield {"type": "error", "content": "Merchant not found."}
        return

    cache_hit = await _semantic_cache.lookup(merchant_id=merchant_id, message=message, threshold=0.92)
    if cache_hit and cache_hit.get("response_text"):
        text = str(cache_hit.get("response_text"))
        await metrics_store.record(
            {
                "session_id": session_id,
                "pipeline_used": "langgraph",
                "total_latency_ms": round((time.perf_counter() - request_start) * 1000, 2),
                "node_durations_ms": {},
                "cache_hit": True,
            }
        )
        yield {"type": "chunk", "content": text}
        return

    if _is_fast_path_message(message=message, input_type=input_type, ocr_text=ocr_text):
        fast_start = time.perf_counter()
        text = await _fast_path_reply(message)
        fast_ms = round((time.perf_counter() - fast_start) * 1000, 2)

        if text.strip():
            await _semantic_cache.store(merchant_id=merchant_id, message=message, response_text=text.strip())

        await metrics_store.record(
            {
                "session_id": session_id,
                "pipeline_used": "langgraph_fast_path",
                "total_latency_ms": round((time.perf_counter() - request_start) * 1000, 2),
                "node_durations_ms": {"fast_path_llm": fast_ms},
                "cache_hit": False,
            }
        )
        yield {"type": "chunk", "content": text}
        return

    state: GraphState = {
        "session_id": session_id,
        "merchant_phone": phone,
        "input_type": input_type,
        "raw_text": message,
        "ocr_text": ocr_text,
        "node_timings_ms": {},
    }

    try:
        graph_out = await _run_graph(state)
    except asyncio.TimeoutError:
        yield {"type": "error", "content": "System slow chal raha hai. 30 second baad phir try karo."}
        return
    except Exception:
        logger.exception("stream_langgraph_chat failed")
        yield {"type": "error", "content": "Abhi system issue aa gaya. Ek baar phir try karo."}
        return
    for event in graph_out.get("tool_results") or []:
        yield {"type": "tool_call", "name": str(event.get("name") or ""), "args": json.dumps(event.get("args") or {}, ensure_ascii=True)}
        yield {"type": "tool_result", "result": json.dumps(event.get("result") or {}, ensure_ascii=True)}

    fmt_start = time.perf_counter()
    aggregated = ""
    async for evt in _stream_response_text(graph_out):
        if evt.get("type") == "chunk":
            aggregated += evt.get("content", "")
        yield evt
    node_timings = dict(graph_out.get("node_timings_ms") or {})
    node_timings["response_formatter"] = round((time.perf_counter() - fmt_start) * 1000, 2)

    if aggregated.strip():
        await _semantic_cache.store(merchant_id=merchant_id, message=message, response_text=aggregated.strip())

    await metrics_store.record(
        {
            "session_id": session_id,
            "pipeline_used": "langgraph",
            "total_latency_ms": round((time.perf_counter() - request_start) * 1000, 2),
            "node_durations_ms": node_timings,
            "cache_hit": False,
        }
    )
