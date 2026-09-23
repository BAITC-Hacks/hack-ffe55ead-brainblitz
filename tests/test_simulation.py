from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.main import create_app, load_config
from app.models import Selection
from app.simulation import apply_effects, simulate, summarize
from app.validator import ScenarioValidationError, validate_selections
from conftest import ROOT, assert_json_equal
from test_api import request


def selections(payload):
    return [Selection(**item) for item in payload["selections"]]


def test_pure_baseline(expected_config):
    indicators = {district["id"]: deepcopy(district["indicators"]) for district in expected_config["districts"]}
    scores, breakdown, critical, score = summarize(indicators, expected_config)
    assert scores == pytest.approx({"esil": 62.99, "almaty": 57.06, "saryarka": 54.65, "baikonur": 56.63, "nura": 49.18}, abs=1e-8, rel=0)
    assert breakdown.city_average == pytest.approx(56.8624, abs=1e-8, rel=0)
    assert breakdown.weakest_district_id == "nura"
    assert breakdown.weakest_district_score == pytest.approx(49.18, abs=1e-8, rel=0)
    assert breakdown.critical_count == 2
    assert_json_equal([item.model_dump() for item in critical], [
        {"district_id": "nura", "indicator": "S1", "value": 38},
        {"district_id": "nura", "indicator": "S2", "value": 35},
    ])
    assert score == pytest.approx(52.55768, abs=1e-8, rel=0)


@pytest.mark.parametrize("value,count", [(39.999999, 1), (40, 0), (40.000001, 0)])
def test_critical_threshold_is_strictly_below_40(expected_config, value, count):
    indicators = {district["id"]: {indicator: 50 for indicator in expected_config["indicators"]} for district in expected_config["districts"]}
    indicators["nura"]["S1"] = value
    _, breakdown, critical, score = summarize(indicators, expected_config)
    assert breakdown.critical_count == count
    assert len(critical) == count
    # Only S1 in a district with 16% population differs from an all-50 city.
    district_nura = 50 + 0.11 * (value - 50)
    expected = 0.7 * (50 + 0.16 * (district_nura - 50)) + 0.3 * district_nura - count
    assert score == pytest.approx(expected, abs=1e-8, rel=0)


def test_tie_uses_first_district_and_score_is_not_clipped(expected_config):
    indicators = {district["id"]: {indicator: 0 for indicator in expected_config["indicators"]} for district in expected_config["districts"]}
    _, breakdown, critical, score = summarize(indicators, expected_config)
    assert breakdown.weakest_district_id == "esil"
    assert len(critical) == 50
    assert score == -50


@pytest.mark.parametrize("lag,factor", [(0, 1), (1, 0.875), (2, 0.75), (3, 0.625), (4, 0.5), (8, 0)])
def test_lags_and_unlagged_synergy(expected_config, scenario_b, lag, factor):
    config = deepcopy(expected_config)
    next(measure for measure in config["measures"] if measure["id"] == "M10")["lag_quarters"] = lag
    after, effects, synergies = apply_effects(selections(scenario_b), config)
    assert after["esil"]["B1"] == pytest.approx(78 + 12 * factor + 2, abs=1e-8, rel=0)
    assert after["esil"]["B2"] == pytest.approx(60 + 2 * factor, abs=1e-8, rel=0)
    effect = next(item for item in effects if item.measure_id == "M10")
    assert_json_equal(effect.realized_effects, {"B1": 12 * factor, "B2": 2 * factor})
    assert_json_equal([item.model_dump() for item in synergies], [{"measure_ids": ["M10", "M12"], "district_id": "esil", "effects": {"B1": 2}}])


@pytest.mark.parametrize("measure_ids,district,indicator,expected", [
    (("M1", "M2"), "esil", "T1", 54.5),
    (("M5", "M6"), "nura", "E2", 77.25),
])
def test_original_same_category_synergies_remain_in_math_only(expected_config, measure_ids, district, indicator, expected):
    payload = request((measure_ids[0], district), (measure_ids[1], None))
    after, _, synergies = apply_effects(selections(payload), expected_config)
    assert after[district][indicator] == pytest.approx(expected, abs=1e-8, rel=0)
    assert len(synergies) == 1
    assert synergies[0].effects == {indicator: 2}


def test_city_effects_reach_all_districts_and_m11_can_reduce_transport(client):
    payload = request(("M2", None), ("M6", None), ("M9", "nura"), ("M11", "esil"), ("M14", None))
    response = client.post("/api/simulate", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["applied_synergies"] == []
    for district in result["districts"]:
        changes = district["changes"]
        assert changes["T1"] == pytest.approx(1.25 if district["id"] == "esil" else 3, abs=1e-8, rel=0)
        assert changes["B2"] == pytest.approx(12.75 if district["id"] == "esil" else 2.25, abs=1e-8, rel=0)
        assert changes["E1"] == pytest.approx(2.5, abs=1e-8, rel=0)
        assert changes["E2"] == pytest.approx(1.5, abs=1e-8, rel=0)
        assert changes["C1"] == pytest.approx(4.375, abs=1e-8, rel=0)
        assert changes["C2"] == pytest.approx(1.75, abs=1e-8, rel=0)
    effect = next(item for item in result["applied_effects"] if item["measure_id"] == "M11")
    assert effect["realized_effects"]["T1"] == -1.75


def test_clip_occurs_only_after_summing_positive_and_negative_effects(write_dataset):
    def mutate(districts, measures):
        districts["districts"][0]["indicators"]["T1"] = 99
        districts["districts"][0]["indicators"]["B2"] = 99

    data_dir = write_dataset(mutate)
    payload = request(("M2", None), ("M6", None), ("M9", "nura"), ("M11", "esil"), ("M14", None))
    with TestClient(create_app(data_dir=data_dir)) as client:
        response = client.post("/api/simulate", json=payload)
        assert response.status_code == 200
        # 99+3-1.75=100.25 -> 100. Sequential clipping would incorrectly give 98.25.
        assert response.json()["districts"][0]["after"]["T1"] == 100
        assert response.json()["districts"][0]["changes"]["T1"] == 1
        assert response.json()["districts"][0]["after"]["B2"] == 100


def test_clip_lower_boundary_does_not_change_recorded_effect(write_dataset):
    def mutate(districts, measures):
        districts["districts"][0]["indicators"]["T1"] = 1

    data_dir = write_dataset(mutate)
    payload = request(("M1", "nura"), ("M6", None), ("M9", "nura"), ("M11", "esil"), ("M14", None))
    with TestClient(create_app(data_dir=data_dir)) as client:
        response = client.post("/api/simulate", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert result["districts"][0]["after"]["T1"] == 0
        assert result["districts"][0]["changes"]["T1"] == -1
        effect = next(item for item in result["applied_effects"] if item["measure_id"] == "M11")
        assert effect["realized_effects"]["T1"] == -1.75


def test_synergy_then_clip_records_full_synergy(write_dataset, scenario_b):
    def mutate(districts, measures):
        districts["districts"][0]["indicators"]["B1"] = 89

    data_dir = write_dataset(mutate)
    with TestClient(create_app(data_dir=data_dir)) as client:
        result = client.post("/api/simulate", json=scenario_b).json()
    assert result["districts"][0]["after"]["B1"] == 100
    assert result["districts"][0]["changes"]["B1"] == 11
    assert result["applied_synergies"][0]["effects"] == {"B1": 2}


def test_pure_simulation_validates_and_does_not_mutate_input(expected_config, scenario_b, expected_b):
    original_config = deepcopy(expected_config)
    chosen = selections(scenario_b)
    original_selections = [item.model_dump() for item in chosen]
    assert_json_equal(simulate(chosen, expected_config).model_dump(), expected_b)
    assert expected_config == original_config
    assert [item.model_dump() for item in chosen] == original_selections
    with pytest.raises(ValueError):
        simulate(chosen[:-1], expected_config)


def test_loaded_snapshot_is_immutable(scenario_b, expected_b):
    config = load_config(ROOT / "data")
    with pytest.raises(TypeError):
        config["districts"][0]["indicators"]["T1"] = 100
    assert_json_equal(simulate(selections(scenario_b), config).model_dump(), expected_b)


def test_global_conflict_remains_rule_beyond_current_category_constraint(expected_config):
    # In the published config CATEGORY_COVERAGE rejects M1+M3 first. This
    # controlled category change isolates the underlying any-district rule.
    config = deepcopy(expected_config)
    next(measure for measure in config["measures"] if measure["id"] == "M3")["category"] = "environment"
    payload = request(("M1", "esil"), ("M3", "nura"), ("M7", "nura"), ("M10", "esil"), ("M12", None))
    with pytest.raises(ScenarioValidationError) as captured:
        validate_selections(selections(payload), config)
    assert captured.value.detail[0]["code"] == "INCOMPATIBLE_MEASURES"
    assert captured.value.detail[0]["context"] == {"measure_ids": ["M1", "M3"]}
