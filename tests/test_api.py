from copy import deepcopy
from itertools import permutations
import json

from fastapi.testclient import TestClient
import pytest

from app.main import app
from conftest import ROOT, assert_error, assert_json_equal


def request(*pairs):
    return {"selections": [{"measure_id": measure, "district_id": district} for measure, district in pairs]}


def test_health_and_global_application():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_complete_config_matches_contract(client, expected_config):
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert_json_equal(response.json(), expected_config)
    for key in ("budget", "horizon_quarters", "required_selection_count", "max_per_category"):
        assert type(response.json()[key]) is int


def test_complete_scenario_b_matches_contract(client, scenario_b, expected_b):
    response = client.post("/api/simulate", json=scenario_b)
    assert response.status_code == 200, response.text
    assert_json_equal(response.json(), expected_b)
    for key in ("total_cost", "remaining_budget"):
        assert type(response.json()[key]) is int
    assert response.json()["score_delta"] == pytest.approx(2.5126675, abs=1e-8, rel=0)


def test_scenario_a_and_unchanged_baseline(client, scenario_a, expected_b):
    response = client.post("/api/simulate", json=scenario_a)
    assert response.status_code == 200
    result = response.json()
    expected_a = deepcopy(expected_b)
    expected_a["selections"][2]["district_id"] = "esil"
    expected_a["final_score"] = 53.8250475
    expected_a["score_delta"] = 1.2673675
    expected_a["score_breakdown"]["after"] = {
        "city_average": 58.485425,
        "weakest_district_id": "nura",
        "weakest_district_score": 49.6175,
        "critical_count": 2,
    }
    expected_a["districts"][0]["after"]["S1"] = 58
    expected_a["districts"][0]["changes"]["S1"] = 10
    expected_a["districts"][0]["score_after"] = 66.935
    expected_a["districts"][4]["after"]["S1"] = 38
    expected_a["districts"][4]["changes"]["S1"] = 0
    expected_a["districts"][4]["score_after"] = 49.6175
    expected_a["critical_after"] = deepcopy(expected_a["critical_before"])
    expected_a["applied_effects"][2]["district_id"] = "esil"
    assert_json_equal(result, expected_a)
    assert result["baseline_score"] == pytest.approx(52.55768, abs=1e-8, rel=0)


def test_budget_exactly_100_is_accepted(client):
    payload = request(("M3", "nura"), ("M6", None), ("M7", "nura"), ("M10", "esil"), ("M12", None))
    response = client.post("/api/simulate", json=payload)
    assert response.status_code == 200
    assert response.json()["total_cost"] == 100
    assert response.json()["remaining_budget"] == 0


def test_budget_107_error_is_exact_contract_example(client, contract_examples):
    payload = request(("M3", "nura"), ("M5", "saryarka"), ("M7", "nura"), ("M10", "esil"), ("M14", None))
    response = client.post("/api/simulate", json=payload)
    assert_error(response, "BUDGET_EXCEEDED", ["selections"])
    expected = next(item for item in contract_examples if item.get("detail", [{}])[0].get("code") == "BUDGET_EXCEEDED")
    assert response.json() == expected


def test_conflict_error_is_exact_contract_example(client, scenario_b, contract_examples):
    scenario_b["selections"][1]["district_id"] = "nura"
    response = client.post("/api/simulate", json=scenario_b)
    assert_error(response, "INCOMPATIBLE_MEASURES", ["selections"])
    expected = next(item for item in contract_examples if item.get("detail", [{}])[0].get("code") == "INCOMPATIBLE_MEASURES")
    assert response.json() == expected


def test_category_error_is_exact_contract_example(client, contract_examples):
    payload = request(("M7", "nura"), ("M8", "nura"), ("M10", "nura"), ("M12", None), ("M5", "saryarka"))
    response = client.post("/api/simulate", json=payload)
    assert_error(response, "CATEGORY_COVERAGE", ["selections"])
    expected = next(item for item in contract_examples if item.get("detail", [{}])[0].get("code") == "CATEGORY_COVERAGE")
    assert response.json() == expected


@pytest.mark.parametrize("body,path", [
    (None, []), ([], []), ({}, ["selections"]),
    ({"selections": None}, ["selections"]),
    ({"selections": {}}, ["selections"]),
    ({"selections": [None]}, ["selections", 0]),
    ({"selections": [{}]}, ["selections", 0, "measure_id"]),
    ({"selections": [{"measure_id": 1}]}, ["selections", 0, "measure_id"]),
    ({"selections": [{"measure_id": True}]}, ["selections", 0, "measure_id"]),
    ({"selections": [{"measure_id": None}]}, ["selections", 0, "measure_id"]),
    ({"selections": [{"measure_id": "M1", "district_id": 123}]}, ["selections", 0, "district_id"]),
    ({"selections": [{"measure_id": "M1", "district_id": False}]}, ["selections", 0, "district_id"]),
])
def test_invalid_request_types_are_not_coerced(client, body, path):
    response = client.post("/api/simulate", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert_error(response, "INVALID_REQUEST", path)


def test_malformed_json_has_contract_envelope(client):
    response = client.post("/api/simulate", content='{"selections": [', headers={"Content-Type": "application/json"})
    error = assert_error(response, "INVALID_REQUEST", [])
    assert error["context"] == {}


@pytest.mark.parametrize("field", ["total_cost", "budget", "effects", "weights", "final_score", "prompt", "decisions", "dataset_version"])
def test_client_cannot_supply_calculated_or_extra_fields(client, scenario_b, field):
    scenario_b[field] = 0
    assert_error(client.post("/api/simulate", json=scenario_b), "UNEXPECTED_FIELD", [field])


@pytest.mark.parametrize("field", ["cost", "scope", "category", "effects", "lag_quarters"])
def test_selection_rejects_extra_fields(client, scenario_b, field):
    scenario_b["selections"][0][field] = 0
    assert_error(client.post("/api/simulate", json=scenario_b), "UNEXPECTED_FIELD", ["selections", 0, field])


@pytest.mark.parametrize("count", [0, 4, 6])
def test_exactly_five_selections_required(client, scenario_b, count):
    scenario_b["selections"] = (scenario_b["selections"] * 2)[:count]
    assert_error(client.post("/api/simulate", json=scenario_b), "INVALID_SELECTION_COUNT", ["selections"])


@pytest.mark.parametrize("measure", ["M0", "M15", "m1", "M01", "", " M1 "])
def test_unknown_measure_ids(client, scenario_b, measure):
    scenario_b["selections"][0]["measure_id"] = measure
    assert_error(client.post("/api/simulate", json=scenario_b), "UNKNOWN_MEASURE", ["selections", 0, "measure_id"])


def test_duplicate_measure_even_in_different_districts(client, scenario_b):
    scenario_b["selections"][2] = {"measure_id": "M1", "district_id": "nura"}
    assert_error(client.post("/api/simulate", json=scenario_b), "DUPLICATE_MEASURE", ["selections", 2, "measure_id"])


@pytest.mark.parametrize("omit", [True, False])
def test_local_measure_requires_district(client, scenario_b, omit):
    if omit:
        scenario_b["selections"][0].pop("district_id")
    else:
        scenario_b["selections"][0]["district_id"] = None
    assert_error(client.post("/api/simulate", json=scenario_b), "DISTRICT_REQUIRED", ["selections", 0, "district_id"])


@pytest.mark.parametrize("district", ["", "Есиль", "Esil", "unknown", " esil "])
def test_unknown_local_district_ids(client, scenario_b, district):
    scenario_b["selections"][0]["district_id"] = district
    assert_error(client.post("/api/simulate", json=scenario_b), "UNKNOWN_DISTRICT", ["selections", 0, "district_id"])


@pytest.mark.parametrize("district", ["esil", "unknown", ""])
def test_city_measure_forbids_every_non_null_district(client, scenario_b, district):
    scenario_b["selections"][4]["district_id"] = district
    assert_error(client.post("/api/simulate", json=scenario_b), "DISTRICT_NOT_ALLOWED", ["selections", 4, "district_id"])


def test_city_district_omission_is_normalized_to_null(client, scenario_b, expected_b):
    scenario_b["selections"][4].pop("district_id")
    response = client.post("/api/simulate", json=scenario_b)
    assert response.status_code == 200
    assert_json_equal(response.json(), expected_b)


def test_second_local_conflict(client):
    payload = request(("M1", "esil"), ("M5", "nura"), ("M9", "esil"), ("M11", "esil"), ("M13", "nura"))
    error = assert_error(client.post("/api/simulate", json=payload), "INCOMPATIBLE_MEASURES", ["selections"])
    assert error["context"] == {"measure_ids": ["M5", "M13"], "district_id": "nura"}
    payload["selections"][4]["district_id"] = "saryarka"
    assert client.post("/api/simulate", json=payload).status_code == 200


@pytest.mark.parametrize("method,path", [("get", "/config"), ("post", "/simulate")])
def test_legacy_paths_do_not_exist(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_all_selection_permutations_have_identical_response(client, scenario_b):
    original = client.post("/api/simulate", json=scenario_b).json()
    for ordering in permutations(scenario_b["selections"]):
        response = client.post("/api/simulate", json={"selections": list(ordering)})
        assert response.status_code == 200
        assert response.json() == original


def test_repeated_interleaved_calls_do_not_mutate_dataset(client, scenario_a, scenario_b):
    files_before = {path.name: path.read_bytes() for path in (ROOT / "data").glob("*.json")}
    config_before = client.get("/api/config").json()
    first = client.post("/api/simulate", json=scenario_b).json()
    client.post("/api/simulate", json=scenario_a)
    client.post("/api/simulate", json={"selections": []})
    assert client.post("/api/simulate", json=scenario_b).json() == first
    assert client.get("/api/config").json() == config_before
    assert {path.name: path.read_bytes() for path in (ROOT / "data").glob("*.json")} == files_before
