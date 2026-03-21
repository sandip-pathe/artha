from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Confidence = Literal["HIGH", "MEDIUM", "LOW"]
Verdict = Literal["GENUINE", "SUSPICIOUS", "CANNOT_VERIFY"]


@dataclass(slots=True)
class LayerResult:
    layer: str
    flagged: bool
    confidence: Confidence
    detail: str
    red_flags: list[str] = field(default_factory=list)
    metadata: dict[str, str | float | int | None] = field(default_factory=dict)


@dataclass(slots=True)
class FraudResult:
    verdict: Verdict
    confidence: Confidence
    layers: list[LayerResult]
    layers_flagged: list[str]
    red_flags: list[str]
    amount_detected: float | None
    payment_app_detected: str | None
    transaction_ref: str | None
