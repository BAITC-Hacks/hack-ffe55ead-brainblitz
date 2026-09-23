"""One asynchronous OpenAI Responses adapter; calculations stay in simulation.py."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
from typing import Any

import httpx

from app.models import Analysis, AnalysisResult, SimulationResult, UnavailableReason


DEFAULT_BASE_URL = "https://api.openai.com/v1"
MAX_RESPONSE_BYTES = 128 * 1024
PROMPT_PATH = Path(__file__).parent / "prompts" / "analyst.txt"
MESSAGES: dict[UnavailableReason, str] = {
    "disabled": "AI-разбор отключён. Рассчитанные показатели остаются доступны.",
    "not_configured": "AI-разбор не настроен. Рассчитанные показатели остаются доступны.",
    "timeout": "AI-разбор не получен вовремя. Рассчитанные показатели остаются доступны.",
    "rate_limited": "AI-разбор временно недоступен из-за ограничения запросов. Рассчитанные показатели остаются доступны.",
    "provider_error": "Сервис AI-разбора недоступен. Рассчитанные показатели остаются доступны.",
    "invalid_response": "Ответ AI не прошёл проверку. Рассчитанные показатели остаются доступны.",
    "refused": "Модель отказалась сформировать разбор. Рассчитанные показатели остаются доступны.",
}


@dataclass(frozen=True)
class AISettings:
    api_key: str = field(default="", repr=False)
    model: str = ""
    base_url: str = field(default=DEFAULT_BASE_URL, repr=False)
    timeout_seconds: float = 12.0
    enabled: bool = True
    valid: bool = True

    @classmethod
    def from_env(cls) -> "AISettings":
        enabled = os.getenv("AI_ENABLED", "true").strip().lower()
        valid = enabled in {"true", "false"}
        try:
            timeout = float(os.getenv("AI_TIMEOUT_SECONDS", "12"))
            valid = valid and math.isfinite(timeout) and timeout > 0
        except ValueError:
            timeout, valid = 12.0, False
        base_url = os.getenv("AI_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        try:
            url = httpx.URL(base_url)
            valid = valid and bool(url.scheme == "https" and url.host)
            valid = valid and not (url.username or url.password or url.query or url.fragment)
        except httpx.InvalidURL:
            valid = False
        key = os.getenv("AI_API_KEY", "").strip()
        # Reject header injection or invalid header bytes without logging values.
        valid = valid and all(33 <= ord(char) <= 126 for char in key)
        return cls(
            api_key=key, model=os.getenv("AI_MODEL", "").strip(),
            base_url=base_url, timeout_seconds=timeout,
            enabled=enabled != "false", valid=valid,
        )

    @property
    def unavailable_reason(self) -> UnavailableReason | None:
        if not self.enabled:
            return "disabled"
        if not self.valid or not self.api_key or not self.model:
            return "not_configured"
        return None


def create_ai_client(settings: AISettings) -> httpx.AsyncClient:
    """One lifespan-owned client, no retries, no redirects or ambient proxies."""
    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(retries=0),
        timeout=httpx.Timeout(settings.timeout_seconds),
        follow_redirects=False, trust_env=False,
    )


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 pointer, with strict array indices and ~ escaping."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("Expected a JSON Pointer, not a fragment or relative path.")
    current = document
    for raw in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw):
            raise ValueError("Invalid JSON Pointer escape.")
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            # Check length before int() to handle untrusted huge indices safely.
            if len(token) > len(str(len(current))) or int(token) >= len(current):
                raise ValueError("JSON Pointer array index is out of bounds.")
            current = current[int(token)]
        else:
            raise ValueError("JSON Pointer does not resolve.")
    return current


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON value.")


def _load_json(raw: str | bytes) -> Any:
    return json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_invalid_constant)


def analysis_schema() -> dict[str, Any]:
    """Derive the wire schema from Pydantic; enforce text/size limits locally.

    The structural subset works with Structured Outputs models, including those
    that do not support minLength/maxLength/minItems/maxItems. No weaker local
    model is used; the response must pass every contract limit after parsing.
    """
    def structural(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: structural(item) for key, item in value.items()
                if key not in {"title", "minLength", "maxLength", "minItems", "maxItems"}
            }
        if isinstance(value, list):
            return [structural(item) for item in value]
        return value
    return structural(Analysis.model_json_schema())


class AIUnavailable(Exception):
    def __init__(self, reason: UnavailableReason):
        super().__init__(reason)
        self.reason = reason


def _extract_analysis(raw: bytes, simulation: dict[str, Any]) -> Analysis:
    """Parse only a complete assistant message, never reasoning or tool output."""
    try:
        response = _load_json(raw)
        if not isinstance(response, dict):
            raise ValueError("Expected a response object.")
        status = response.get("status")
        if status == "failed":
            raise AIUnavailable("provider_error")
        if status != "completed" or response.get("incomplete_details") is not None:
            raise ValueError("Incomplete provider output.")
        output = response.get("output")
        if not isinstance(output, list):
            raise ValueError("Missing output.")
        texts = []
        for item in output:
            if not isinstance(item, dict):
                raise ValueError("Invalid output item.")
            if item.get("type") == "reasoning":
                continue
            if item.get("type") != "message" or item.get("status", "completed") != "completed":
                raise ValueError("Unexpected or incomplete output item.")
            content = item.get("content")
            if not isinstance(content, list):
                raise ValueError("Invalid message content.")
            for part in content:
                if not isinstance(part, dict):
                    raise ValueError("Invalid content part.")
                if part.get("type") == "refusal":
                    raise AIUnavailable("refused")
                if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                    raise ValueError("Expected text output.")
                texts.append(part["text"])
        if len(texts) != 1:
            raise ValueError("Expected one complete JSON text.")
        analysis = Analysis.model_validate(_load_json(texts[0]))
        for statement in analysis.statements():
            for pointer in statement.evidence_paths:
                # The UI requires a concrete fact under the SimulationResult root.
                if not pointer.startswith("/"):
                    raise ValueError("Evidence must address a result field.")
                resolve_pointer(simulation, pointer)
        return analysis
    except (ValueError, TypeError, RecursionError):
        raise AIUnavailable("invalid_response") from None


class OpenAIAnalyst:
    def __init__(self, settings: AISettings, client: httpx.AsyncClient | None):
        self.settings = settings
        self.client = client
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.schema = analysis_schema()

    async def analyze(
        self, simulation: SimulationResult, config: Mapping[str, Any],
    ) -> AnalysisResult:
        # Numbers, versions, canonical selections and status never come from LLM.
        envelope = {
            name: getattr(simulation, name) for name in (
                "contract_version", "dataset_version", "rules_version",
                "selections", "baseline_score", "final_score",
            )
        }
        reason = self.settings.unavailable_reason
        analysis = None
        if reason is None:
            if self.client is None:
                raise RuntimeError("Configured analyst requires a lifespan-owned client.")
            facts = simulation.model_dump(mode="json")
            catalog = {
                "measures": [{key: measure[key] for key in (
                    "id", "name", "category", "scope", "lag_quarters",
                )} for measure in config["measures"]],
                "indicator_labels": dict(config["indicator_labels"]),
            }
            payload = {
                "model": self.settings.model,
                "instructions": self.prompt,
                "input": json.dumps({"simulation": facts, "catalog": catalog}, ensure_ascii=False),
                "text": {"format": {
                    "type": "json_schema", "name": "city_analysis",
                    "strict": True, "schema": self.schema,
                }},
                "store": False,
            }
            try:
                # Covers pool wait, connect, headers AND the complete response body.
                async with asyncio.timeout(self.settings.timeout_seconds):
                    async with self.client.stream(
                        "POST", self.settings.base_url + "/responses",
                        headers={"Authorization": "Bearer " + self.settings.api_key},
                        json=payload,
                    ) as response:
                        if response.status_code == 429:
                            raise AIUnavailable("rate_limited")
                        if not 200 <= response.status_code < 300:
                            raise AIUnavailable("provider_error")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_RESPONSE_BYTES:
                                raise AIUnavailable("invalid_response")
                    analysis = _extract_analysis(bytes(raw), facts)
            except (TimeoutError, httpx.TimeoutException):
                reason = "timeout"
            except httpx.HTTPError:
                reason = "provider_error"
            except AIUnavailable as exc:
                reason = exc.reason
        if reason is not None:
            return AnalysisResult(
                **envelope, status="unavailable", analysis=None,
                unavailable_reason=reason, message=MESSAGES[reason],
            )
        return AnalysisResult(
            **envelope, status="ok", analysis=analysis,
            unavailable_reason=None, message="",
        )
