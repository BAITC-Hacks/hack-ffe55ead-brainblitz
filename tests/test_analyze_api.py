"""HTTP acceptance checks for real-provider wiring, using only a mock transport.

The successful response oracle is the checked-in public contract, not simulate().
No test in this module can contact a paid API, even if the shell has real keys.
"""

import asyncio
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import httpx
import pytest

import app.main as main_module
from conftest import assert_error, assert_json_equal


AI_ENVIRONMENT = (
    "AI_API_KEY", "AI_MODEL", "AI_BASE_URL", "AI_TIMEOUT_SECONDS", "AI_ENABLED",
)


@pytest.fixture(autouse=True)
def isolate_ai_environment(monkeypatch):
    for name in AI_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    # Model/key names here are mock-only and do not assert real model access.
    monkeypatch.setenv("AI_ENABLED", "true")
    monkeypatch.setenv("AI_API_KEY", "fake-test-key")
    monkeypatch.setenv("AI_MODEL", "mock-only-model")


@pytest.fixture
def expected_analysis_result(contract_examples):
    return deepcopy(next(
        item for item in contract_examples
        if item.get("status") == "ok" and "analysis" in item
    ))


def completed_response(analysis):
    return {
        "status": "completed",
        "output": [{"type": "message", "content": [{
            "type": "output_text", "text": json.dumps(analysis, ensure_ascii=False),
        }]}],
    }


@pytest.fixture
def provider(monkeypatch, expected_analysis_result):
    """Patch the lifespan factory; retain client/request evidence for assertions."""
    def install(response=None, *, status=200, error=None):
        calls = []

        async def handle(request):
            calls.append(request)
            if error is not None:
                raise error
            body = response if response is not None else completed_response(
                expected_analysis_result["analysis"]
            )
            return httpx.Response(status, json=body)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        monkeypatch.setattr(main_module, "create_ai_client", lambda settings: client)
        return client, calls

    return install


def assert_unavailable(response, oracle, reason):
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(oracle)
    for field in (
        "contract_version", "dataset_version", "rules_version", "selections",
        "baseline_score", "final_score",
    ):
        assert_json_equal(body[field], oracle[field], field)
    assert body["status"] == "unavailable"
    assert body["analysis"] is None
    assert body["unavailable_reason"] == reason
    assert isinstance(body["message"], str) and body["message"].strip()
    assert "fake-test-key" not in response.text
    return body


@pytest.mark.parametrize("reorder", [False, True])
def test_success_matches_full_contract_and_server_normalizes_selections(
    provider, scenario_b, expected_analysis_result, reorder,
):
    http_client, calls = provider()
    if reorder:
        scenario_b["selections"][4].pop("district_id")
        scenario_b["selections"].reverse()
    with TestClient(main_module.create_app()) as client:
        response = client.post("/api/analyze", json=scenario_b)
        assert response.status_code == 200, response.text
        assert_json_equal(response.json(), expected_analysis_result)
        assert len(calls) == 1
        assert calls[0].method == "POST"
        assert calls[0].url.path == "/v1/responses"
    assert http_client.is_closed


INVALID_CASES = [
    ("empty", "INVALID_SELECTION_COUNT", ["selections"]),
    ("four", "INVALID_SELECTION_COUNT", ["selections"]),
    ("six", "INVALID_SELECTION_COUNT", ["selections"]),
    ("unknown_measure", "UNKNOWN_MEASURE", ["selections", 0, "measure_id"]),
    ("duplicate", "DUPLICATE_MEASURE", ["selections", 2, "measure_id"]),
    ("missing_district", "DISTRICT_REQUIRED", ["selections", 0, "district_id"]),
    ("null_district", "DISTRICT_REQUIRED", ["selections", 0, "district_id"]),
    ("unknown_district", "UNKNOWN_DISTRICT", ["selections", 0, "district_id"]),
    ("city_district", "DISTRICT_NOT_ALLOWED", ["selections", 4, "district_id"]),
    ("categories", "CATEGORY_COVERAGE", ["selections"]),
    ("conflict", "INCOMPATIBLE_MEASURES", ["selections"]),
    ("second_conflict", "INCOMPATIBLE_MEASURES", ["selections"]),
    ("over_budget", "BUDGET_EXCEEDED", ["selections"]),
    ("wrong_type", "INVALID_REQUEST", ["selections", 0, "measure_id"]),
]


def invalid_payload(case, valid):
    payload = deepcopy(valid)
    selections = payload["selections"]
    if case in {"empty", "four", "six"}:
        payload["selections"] = (selections * 2)[:{"empty": 0, "four": 4, "six": 6}[case]]
    elif case == "unknown_measure":
        selections[0]["measure_id"] = "M999"
    elif case == "duplicate":
        selections[2] = {"measure_id": "M1", "district_id": "nura"}
    elif case == "missing_district":
        selections[0].pop("district_id")
    elif case == "null_district":
        selections[0]["district_id"] = None
    elif case == "unknown_district":
        selections[0]["district_id"] = "unknown"
    elif case == "city_district":
        selections[4]["district_id"] = "esil"
    elif case == "categories":
        selections[0] = {"measure_id": "M8", "district_id": "nura"}
    elif case == "conflict":
        selections[1]["district_id"] = "nura"
    elif case == "second_conflict":
        selections[1] = {"measure_id": "M5", "district_id": "nura"}
        selections[2] = {"measure_id": "M9", "district_id": "esil"}
        selections[3] = {"measure_id": "M11", "district_id": "esil"}
        selections[4] = {"measure_id": "M13", "district_id": "nura"}
    elif case == "over_budget":
        selections[0] = {"measure_id": "M3", "district_id": "nura"}
        selections[1] = {"measure_id": "M5", "district_id": "saryarka"}
        selections[4] = {"measure_id": "M14", "district_id": None}
    elif case == "wrong_type":
        selections[0]["measure_id"] = 1
    else:
        raise AssertionError(f"Unknown test case: {case}")
    return payload


@pytest.mark.parametrize("case,code,path", INVALID_CASES)
def test_invalid_choices_match_simulate_first_error_without_provider_call(
    provider, scenario_b, case, code, path,
):
    _, calls = provider()
    payload = invalid_payload(case, scenario_b)
    with TestClient(main_module.create_app()) as client:
        analysis = client.post("/api/analyze", json=payload)
        simulation = client.post("/api/simulate", json=payload)
    assert_error(analysis, code, path)
    assert analysis.json() == simulation.json()
    assert calls == []


@pytest.mark.parametrize("field", [
    "total_cost", "budget", "effects", "weights", "final_score", "prompt",
    "decisions", "dataset_version",
])
def test_client_facts_are_rejected_before_provider(provider, scenario_b, field):
    _, calls = provider()
    scenario_b[field] = 0
    with TestClient(main_module.create_app()) as client:
        result = client.post("/api/analyze", json=scenario_b)
        reference = client.post("/api/simulate", json=scenario_b)
    assert_error(result, "UNEXPECTED_FIELD", [field])
    assert result.json() == reference.json()
    assert calls == []


@pytest.mark.parametrize("field", ["cost", "scope", "category", "effects", "lag_quarters"])
def test_extra_selection_fields_never_reach_provider(provider, scenario_b, field):
    _, calls = provider()
    scenario_b["selections"][0][field] = 0
    with TestClient(main_module.create_app()) as client:
        result = client.post("/api/analyze", json=scenario_b)
        reference = client.post("/api/simulate", json=scenario_b)
    assert_error(result, "UNEXPECTED_FIELD", ["selections", 0, field])
    assert result.json() == reference.json()
    assert calls == []


@pytest.mark.parametrize("body,path", [
    ('{"selections": [', []), ("null", []), ("[]", []),
    ("{}", ["selections"]), ('{"selections":null}', ["selections"]),
])
def test_malformed_requests_share_contract_and_make_no_call(provider, body, path):
    _, calls = provider()
    with TestClient(main_module.create_app()) as client:
        result = client.post("/api/analyze", content=body, headers={"Content-Type": "application/json"})
        reference = client.post("/api/simulate", content=body, headers={"Content-Type": "application/json"})
    assert_error(result, "INVALID_REQUEST", path)
    assert result.json() == reference.json()
    assert calls == []


@pytest.mark.parametrize("mode,reason", [
    ("disabled", "disabled"), ("no_key", "not_configured"),
    ("no_model", "not_configured"), ("no_settings", "not_configured"),
])
def test_missing_configuration_and_disabled_do_not_affect_core_endpoints(
    monkeypatch, scenario_b, expected_analysis_result, mode, reason,
):
    if mode == "disabled":
        monkeypatch.setenv("AI_ENABLED", "false")
    elif mode == "no_key":
        monkeypatch.delenv("AI_API_KEY")
    elif mode == "no_model":
        monkeypatch.delenv("AI_MODEL")
    elif mode == "no_settings":
        monkeypatch.delenv("AI_API_KEY")
        monkeypatch.delenv("AI_MODEL")

    def forbidden_client(settings):
        raise AssertionError("No provider client should be created in this mode")

    monkeypatch.setattr(main_module, "create_ai_client", forbidden_client)
    with TestClient(main_module.create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/config").status_code == 200
        assert client.post("/api/simulate", json=scenario_b).status_code == 200
        assert_unavailable(
            client.post("/api/analyze", json=scenario_b), expected_analysis_result, reason,
        )
        # Validation comes first even when no provider is configured.
        assert_error(
            client.post("/api/analyze", json={"selections": []}),
            "INVALID_SELECTION_COUNT", ["selections"],
        )


@pytest.mark.parametrize("status,reason", [
    (429, "rate_limited"), (401, "provider_error"), (403, "provider_error"),
    (500, "provider_error"), (503, "provider_error"),
])
def test_provider_failure_keeps_server_results_and_does_not_retry(
    provider, scenario_b, expected_analysis_result, status, reason,
):
    _, calls = provider(
        {"error": {"message": "fake-test-key must not be exposed"}}, status=status,
    )
    with TestClient(main_module.create_app()) as client:
        result = client.post("/api/analyze", json=scenario_b)
    assert_unavailable(result, expected_analysis_result, reason)
    assert len(calls) == 1


@pytest.mark.parametrize("failure,reason", [
    (httpx.ReadTimeout("secret fake-test-key"), "timeout"),
    (httpx.ConnectError("secret fake-test-key"), "provider_error"),
])
def test_network_failure_keeps_server_results_and_does_not_retry(
    provider, scenario_b, expected_analysis_result, failure, reason,
):
    _, calls = provider(error=failure)
    with TestClient(main_module.create_app()) as client:
        result = client.post("/api/analyze", json=scenario_b)
    assert_unavailable(result, expected_analysis_result, reason)
    assert len(calls) == 1


def test_explicit_refusal_is_unavailable(provider, scenario_b, expected_analysis_result):
    _, calls = provider({
        "status": "completed",
        "output": [{"type": "message", "content": [{
            "type": "refusal", "refusal": "fake-test-key should not escape",
        }]}],
    })
    with TestClient(main_module.create_app()) as client:
        result = client.post("/api/analyze", json=scenario_b)
    assert_unavailable(result, expected_analysis_result, "refused")
    assert len(calls) == 1


def test_model_cannot_supply_response_envelope_or_replace_scores(
    provider, scenario_b, expected_analysis_result,
):
    model_envelope = deepcopy(expected_analysis_result)
    model_envelope.update({
        "contract_version": "forged", "baseline_score": -123, "final_score": 999,
        "selections": [],
    })
    _, calls = provider(completed_response(model_envelope))
    with TestClient(main_module.create_app()) as client:
        result = client.post("/api/analyze", json=scenario_b)
    assert_unavailable(result, expected_analysis_result, "invalid_response")
    assert len(calls) == 1


def test_scenario_a_is_recomputed_not_reused_from_previous_b(
    provider, scenario_a, scenario_b, expected_analysis_result,
):
    # The mock gives a structurally valid small response for both scenarios.
    analysis = deepcopy(expected_analysis_result["analysis"])
    analysis["strengths"] = []
    analysis["risks"] = []
    analysis["summary"] = {"text": "Результат рассчитан моделью.", "evidence_paths": ["/final_score"]}
    analysis["tradeoff"] = {"text": "Остались критические показатели.", "evidence_paths": ["/critical_after"]}
    _, calls = provider(completed_response(analysis))
    with TestClient(main_module.create_app()) as client:
        first = client.post("/api/analyze", json=scenario_b).json()
        second = client.post("/api/analyze", json=scenario_a).json()
    assert first["status"] == second["status"] == "ok"
    assert first["final_score"] == pytest.approx(55.0703475, abs=1e-8, rel=0)
    assert second["baseline_score"] == pytest.approx(52.55768, abs=1e-8, rel=0)
    assert second["final_score"] == pytest.approx(53.8250475, abs=1e-8, rel=0)
    assert second["selections"] == scenario_a["selections"]
    assert len(calls) == 2


def test_internal_math_failure_is_500_and_never_calls_provider(
    monkeypatch, provider, scenario_b,
):
    _, calls = provider()

    def broken_simulation(*args, **kwargs):
        raise RuntimeError("test mathematical failure")

    monkeypatch.setattr(main_module, "simulate", broken_simulation)
    with TestClient(main_module.create_app(), raise_server_exceptions=False) as client:
        response = client.post("/api/analyze", json=scenario_b)
    assert response.status_code == 500
    assert response.json() == {"detail": [{
        "code": "INTERNAL_ERROR",
        "message": "Не удалось выполнить расчёт. Повторите попытку.",
        "path": [], "context": {},
    }]}
    assert calls == []


def test_slow_provider_does_not_block_health_or_simulation_and_client_closes(
    monkeypatch, scenario_b, expected_analysis_result,
):
    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def handle(request):
            calls.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(200, json=completed_response(expected_analysis_result["analysis"]))

        upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        monkeypatch.setattr(main_module, "create_ai_client", lambda settings: upstream)
        application = main_module.create_app()
        async with application.router.lifespan_context(application):
            assert not upstream.is_closed
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://testserver",
            ) as client:
                waiting = asyncio.create_task(client.post("/api/analyze", json=scenario_b))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=2)
                    health, simulation = await asyncio.wait_for(asyncio.gather(
                        client.get("/health"), client.post("/api/simulate", json=scenario_b),
                    ), timeout=2)
                    assert not waiting.done()
                    assert health.json() == {"status": "ok"}
                    assert simulation.status_code == 200
                    assert simulation.json()["final_score"] == pytest.approx(55.0703475, abs=1e-8, rel=0)
                    release.set()
                    result = await asyncio.wait_for(waiting, timeout=2)
                    assert_json_equal(result.json(), expected_analysis_result)
                finally:
                    release.set()
                    if not waiting.done():
                        waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
        assert len(calls) == 1
        assert upstream.is_closed

    asyncio.run(exercise())
