from __future__ import annotations

import json
import math
import os
import inspect
from typing import Any

from openai import AsyncOpenAI
import redis.asyncio as redis_async


SEMANTIC_CACHE_KEY_PREFIX = "semantic_cache"


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    denom = _norm(a) * _norm(b)
    if denom == 0:
        return 0.0
    return _dot(a, b) / denom


class SemanticCache:
    def __init__(self) -> None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis: Any = redis_async.from_url(redis_url, decode_responses=True)
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None
        self.embedding_model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    async def _embed(self, text: str) -> list[float] | None:
        if not self.client:
            return None
        response = await self.client.embeddings.create(model=self.embedding_model, input=text)
        if not response.data:
            return None
        return list(response.data[0].embedding)

    def _key(self, merchant_id: int) -> str:
        return f"{SEMANTIC_CACHE_KEY_PREFIX}:{merchant_id}"

    async def lookup(self, merchant_id: int, message: str, threshold: float = 0.92) -> dict[str, Any] | None:
        probe = await self._embed(message)
        if not probe:
            return None

        key = self._key(merchant_id)
        try:
            candidates_obj = self.redis.lrange(key, 0, 199)
            if inspect.isawaitable(candidates_obj):
                candidates = await candidates_obj
            else:
                candidates = candidates_obj
        except Exception:
            return None
        best_match: dict[str, Any] | None = None
        best_score = -1.0

        for raw in candidates:
            try:
                item = json.loads(raw)
                emb = item.get("embedding")
                if not isinstance(emb, list):
                    continue
                score = cosine_similarity(probe, [float(v) for v in emb])
                if score > best_score:
                    best_score = score
                    best_match = item
            except Exception:
                continue

        if best_match and best_score >= threshold:
            return {
                "similarity": best_score,
                "response_text": str(best_match.get("response_text") or "").strip(),
            }
        return None

    async def store(self, merchant_id: int, message: str, response_text: str) -> None:
        embedding = await self._embed(message)
        if not embedding:
            return
        key = self._key(merchant_id)
        payload = {
            "embedding": embedding,
            "message": message,
            "response_text": response_text,
        }
        try:
            lpush_obj = self.redis.lpush(key, json.dumps(payload))
            if inspect.isawaitable(lpush_obj):
                await lpush_obj

            ltrim_obj = self.redis.ltrim(key, 0, 199)
            if inspect.isawaitable(ltrim_obj):
                await ltrim_obj
        except Exception:
            return
