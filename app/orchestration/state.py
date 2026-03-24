from __future__ import annotations

from typing import Any, TypedDict


class IntentPlan(TypedDict):
    intent: str
    entities: dict[str, Any]
    tools_required: list[str]
    response_language: str
    response_format: str
    confidence: float
    clarification_question: str | None


class GraphState(TypedDict, total=False):
    session_id: str
    merchant_phone: str
    input_type: str
    raw_text: str
    ocr_text: str | None
    normalized_text: str
    context: dict[str, Any]
    intent_plan: IntentPlan
    needs_clarification: bool
    clarification_question: str | None
    tool_results: list[dict[str, Any]]
    response_text: str
    tools_called: list[str]
    node_timings_ms: dict[str, float]
