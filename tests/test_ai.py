"""Provider transport is always mocked; expected facts come from the contract."""

import asyncio
from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError

from app.ai import (
    AISettings, MAX_RESPONSE_BYTES, OpenAIAnalyst, analysis_schema,
    create_ai_client, resolve_pointer,
)
from app.models import Analysis, AnalysisResult, SimulationResult


@pytest.fixture
def analysis_example(contract_examples):
    return deepcopy(next(item["analysis"] for item in contract_examples if item.get("status") == "ok" and "analysis" in item))


def completed(analysis):
    return {"status": "completed", "output": [{
        "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": json.dumps(analysis, ensure_ascii=False)}],
    }]}


def run_adapter(handler, expected_b, expected_config, **settings_overrides):
    settings = AISettings(api_key="test-key", model="test-model", **settings_overrides)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAIAnalyst(settings, client).analyze(
                SimulationResult.model_validate(expected_b), expected_config,
            )
    return asyncio.run(run())


def test_outgoing_request_uses_server_facts_and_structured_output(
    analysis_example, expected_b, expected_config,
):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=completed(analysis_example))

    result = run_adapter(handler, expected_b, expected_config)
    assert result.status == "ok"
    assert result.analysis.model_dump() == analysis_example
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["store"] is False
    assert "temperature" not in body and "stream" not in body
    facts = json.loads(body["input"])
    assert facts["simulation"] == expected_b
    assert facts["catalog"]["indicator_labels"]["S1"] == expected_config["indicator_labels"]["S1"]
    assert len(facts["catalog"]["measures"]) == 14
    assert "инструкции" in body["instructions"]
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {
        "summary", "strengths", "risks", "tradeoff", "reflection_question", "limitations",
    }
    assert "final_score" not in fmt["schema"]["properties"]
    assert expected_b["final_score"] == 55.0703475


@pytest.mark.parametrize("mutate", [
    lambda a: a.update(extra=True),
    lambda a: a.pop("tradeoff"),
    lambda a: a.update(summary="text"),
    lambda a: a["summary"].update(text=123),
    lambda a: a["summary"].update(text=""),
    lambda a: a["summary"].update(text="  \n\t"),
    lambda a: a["summary"].update(text="я" * 601),
    lambda a: a["summary"].update(evidence_paths=[]),
    lambda a: a["summary"].update(evidence_paths=["/final_score"] * 5),
    lambda a: a["summary"].update(evidence_paths=[3]),
    lambda a: a["summary"].update(evidence_ids=["final_score"]),
    lambda a: a.update(strengths=a["strengths"] * 2),
    lambda a: a.update(risks=a["risks"] * 3),
    lambda a: a.update(reflection_question="я" * 301),
    lambda a: a.update(reflection_question=" "),
    lambda a: a.update(limitations=[]),
    lambda a: a.update(limitations=[" "]),
    lambda a: a.update(limitations=["я" * 301]),
    lambda a: a.update(limitations=["синтетика"] * 3),
    lambda a: a.update(summary={"text": "я " * 181, "evidence_paths": ["/final_score"]}),
])
def test_invalid_schema_and_limits_are_unavailable(
    mutate, analysis_example, expected_b, expected_config,
):
    mutate(analysis_example)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=completed(analysis_example))
    result = run_adapter(handler, expected_b, expected_config)
    assert result.unavailable_reason == "invalid_response"
    assert result.analysis is None
    assert result.final_score == 55.0703475
    assert len(calls) == 1


@pytest.mark.parametrize("path", [
    "", "districts/4/after/S1", "#/final_score", "/simulation/final_score",
    "/districts/-1/after/S1", "/districts/04/after/S1", "/districts/+4/after/S1",
    "/districts/4.0/after/S1", "/districts/٤/after/S1", "/districts/5/after/S1",
    "/districts/-/after/S1", "/districts/4/after/missing", "/final_score/child",
    "/districts/4/after/S1~", "/districts/4/after/S1~2", "/critical_after/1",
    "/analysis/summary", pytest.param("/districts/" + "9" * 5000, id="oversized-index"),
])
def test_invalid_evidence_is_rejected(path, analysis_example, expected_b, expected_config):
    analysis_example["summary"]["evidence_paths"] = [path]
    result = run_adapter(
        lambda r: httpx.Response(200, json=completed(analysis_example)), expected_b, expected_config,
    )
    assert result.unavailable_reason == "invalid_response"


def test_json_pointer_rfc_escaping_and_container_values():
    document = {"a/b": {"~key": [None, {"": 40}]}, "~1": 7, "": "empty", "0": False}
    assert resolve_pointer(document, "/a~1b/~0key/1/") == 40
    assert resolve_pointer(document, "/a~1b/~0key/0") is None
    assert resolve_pointer(document, "/~01") == 7
    assert resolve_pointer(document, "/") == "empty"
    assert resolve_pointer(document, "/0") is False
    assert resolve_pointer(document, "") is document
    assert resolve_pointer(document, "/a~1b/~0key") == [None, {"": 40}]


@pytest.mark.parametrize("raw", [
    b"not json", b"null", b"[]", b'{"status":"completed",', b'\xff',
    b'{"status":"completed","status":"completed","output":[]}',
    b'{"status":"completed","output":NaN}',
    json.dumps({"status": "incomplete", "output": [], "incomplete_details": {"reason": "max_output_tokens"}}).encode(),
    json.dumps({"status": "completed", "output": []}).encode(),
    json.dumps({"status": "completed", "output": [{"type": "message", "content": None}]}).encode(),
])
def test_invalid_provider_envelope(raw, expected_b, expected_config):
    result = run_adapter(lambda r: httpx.Response(200, content=raw), expected_b, expected_config)
    assert result.unavailable_reason == "invalid_response"


@pytest.mark.parametrize("raw_text", ["{", "```json\n{}\n```", "[]", "null", '{"summary":{},"summary":{}}'])
def test_invalid_inner_json(raw_text, expected_b, expected_config):
    response = completed({})
    response["output"][0]["content"][0]["text"] = raw_text
    result = run_adapter(lambda r: httpx.Response(200, json=response), expected_b, expected_config)
    assert result.unavailable_reason == "invalid_response"


def test_explicit_refusal_does_not_expose_provider_text(expected_b, expected_config):
    response = {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "refusal", "refusal": "PRIVATE_PROVIDER_MESSAGE"},
    ]}]}
    result = run_adapter(lambda r: httpx.Response(200, json=response), expected_b, expected_config)
    assert result.unavailable_reason == "refused"
    assert "PRIVATE_PROVIDER_MESSAGE" not in result.model_dump_json()


def test_oversized_body_is_invalid(expected_b, expected_config):
    result = run_adapter(
        lambda r: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)), expected_b, expected_config,
    )
    assert result.unavailable_reason == "invalid_response"


def test_total_deadline_cancels_trickling_body(expected_b, expected_config):
    calls, closed = [], []

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                yield b" "
                await asyncio.sleep(0.005)
        async def aclose(self):
            closed.append(True)

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=SlowBody())

    result = run_adapter(handler, expected_b, expected_config, timeout_seconds=0.03)
    assert result.unavailable_reason == "timeout"
    assert len(calls) == 1 and closed == [True]


def test_transport_errors_and_statuses_never_log_secrets(expected_b, expected_config, caplog):
    for status in (302, 400, 401, 403, 404, 429, 500, 503):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(status, text="secret-provider-detail", headers={"Location": "https://other.example"})
        result = run_adapter(handler, expected_b, expected_config)
        assert result.unavailable_reason == ("rate_limited" if status == 429 else "provider_error")
        assert len(calls) == 1
        assert "secret-provider-detail" not in result.model_dump_json()
    assert "test-key" not in caplog.text and "secret-provider-detail" not in caplog.text


@pytest.fixture
def clean_ai_env(monkeypatch):
    for key in ("AI_API_KEY", "AI_MODEL", "AI_BASE_URL", "AI_TIMEOUT_SECONDS", "AI_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_MODEL", "test-model")
    return monkeypatch


def test_settings_defaults_and_secret_repr(clean_ai_env):
    settings = AISettings.from_env()
    assert settings.enabled is True and settings.timeout_seconds == 12
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.unavailable_reason is None
    assert "test-key" not in repr(settings)
    clean_ai_env.delenv("AI_MODEL")
    assert AISettings.from_env().unavailable_reason == "not_configured"


@pytest.mark.parametrize("name,value", [
    ("AI_TIMEOUT_SECONDS", "0"), ("AI_TIMEOUT_SECONDS", "-1"),
    ("AI_TIMEOUT_SECONDS", "nan"), ("AI_TIMEOUT_SECONDS", "inf"),
    ("AI_TIMEOUT_SECONDS", "oops"), ("AI_ENABLED", "maybe"),
    ("AI_BASE_URL", "http://example.com/v1"), ("AI_BASE_URL", "https://user:pass@example.com/v1"),
    ("AI_BASE_URL", "https://example.com/v1?key=secret"), ("AI_BASE_URL", "https://example.com/v1#secret"),
    ("AI_BASE_URL", ""), ("AI_API_KEY", "a\r\nAuthorization: b"),
])
def test_invalid_settings_degrade_without_startup_failure(clean_ai_env, name, value):
    clean_ai_env.setenv(name, value)
    assert AISettings.from_env().unavailable_reason == "not_configured"
    clean_ai_env.setenv("AI_ENABLED", "false")
    assert AISettings.from_env().unavailable_reason == "disabled"


def test_custom_base_is_used_once(analysis_example, expected_b, expected_config):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=completed(analysis_example))
    result = run_adapter(handler, expected_b, expected_config, base_url="https://organizer.example/api/v1")
    assert result.status == "ok"
    assert calls == ["https://organizer.example/api/v1/responses"]


def test_180_word_boundary_is_inclusive():
    payload = {
        "summary": {"text": "я " * 89, "evidence_paths": ["/final_score"]},
        "strengths": [], "risks": [],
        "tradeoff": {"text": "я " * 89, "evidence_paths": ["/final_score"]},
        "reflection_question": "Вопрос?", "limitations": ["Синтетика."],
    }
    Analysis.model_validate(payload)
    payload["reflection_question"] += " Ещё?"
    with pytest.raises(ValidationError):
        Analysis.model_validate(payload)


def test_analysis_result_rejects_inconsistent_status(contract_examples):
    example = deepcopy(next(item for item in contract_examples if item.get("status") == "ok" and "analysis" in item))
    for change in ({"message": "error"}, {"analysis": None}, {"unavailable_reason": "timeout"}, {"status": "unavailable"}):
        with pytest.raises(ValidationError):
            AnalysisResult.model_validate({**example, **change})


def test_real_client_has_no_redirects_and_closes():
    async def run():
        client = create_ai_client(AISettings())
        assert client.follow_redirects is False
        assert client.timeout.read == 12
        await client.aclose()
        assert client.is_closed
    asyncio.run(run())
