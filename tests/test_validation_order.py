"""The contract returns one error, selected by stage before input order."""

from conftest import assert_error
from test_api import request


def test_format_before_count(client, scenario_b):
    scenario_b["selections"].pop()
    scenario_b["selections"][0]["cost"] = 0
    assert_error(client.post("/api/simulate", json=scenario_b), "UNEXPECTED_FIELD", ["selections", 0, "cost"])


def test_count_before_unknown_measure(client, scenario_b):
    scenario_b["selections"].pop()
    scenario_b["selections"][0]["measure_id"] = "unknown"
    assert_error(client.post("/api/simulate", json=scenario_b), "INVALID_SELECTION_COUNT", ["selections"])


def test_unknown_measure_before_earlier_duplicate(client, scenario_b):
    scenario_b["selections"][1]["measure_id"] = "M1"
    scenario_b["selections"][4]["measure_id"] = "unknown"
    assert_error(client.post("/api/simulate", json=scenario_b), "UNKNOWN_MEASURE", ["selections", 4, "measure_id"])


def test_duplicate_before_earlier_district_error(client, scenario_b):
    scenario_b["selections"][0]["district_id"] = None
    scenario_b["selections"][4]["measure_id"] = "M1"
    assert_error(client.post("/api/simulate", json=scenario_b), "DUPLICATE_MEASURE", ["selections", 4, "measure_id"])


def test_district_before_category(client, scenario_b):
    scenario_b["selections"][0]["measure_id"] = "M9"
    scenario_b["selections"][1]["district_id"] = "unknown"
    assert_error(client.post("/api/simulate", json=scenario_b), "UNKNOWN_DISTRICT", ["selections", 1, "district_id"])


def test_categories_before_global_incompatibility(client):
    payload = request(("M1", "esil"), ("M3", "nura"), ("M7", "esil"), ("M10", "esil"), ("M12", None))
    error = assert_error(client.post("/api/simulate", json=payload), "CATEGORY_COVERAGE", ["selections"])
    assert error["context"]["missing_categories"] == ["environment"]


def test_conflict_before_budget(client):
    payload = request(("M3", "esil"), ("M5", "nura"), ("M7", "nura"), ("M10", "esil"), ("M13", "nura"))
    error = assert_error(client.post("/api/simulate", json=payload), "INCOMPATIBLE_MEASURES", ["selections"])
    assert error["context"] == {"measure_ids": ["M5", "M13"], "district_id": "nura"}


def test_unknown_measure_uses_input_order(client, scenario_b):
    scenario_b["selections"][3]["measure_id"] = "first_unknown"
    scenario_b["selections"][4]["measure_id"] = "second_unknown"
    assert_error(client.post("/api/simulate", json=scenario_b), "UNKNOWN_MEASURE", ["selections", 3, "measure_id"])


def test_district_stage_uses_input_order_across_error_types(client, scenario_b):
    scenario_b["selections"][0]["district_id"] = "unknown"
    scenario_b["selections"][1]["district_id"] = None
    assert_error(client.post("/api/simulate", json=scenario_b), "UNKNOWN_DISTRICT", ["selections", 0, "district_id"])


def test_missing_categories_follow_config_order(client):
    payload = request(("M7", "nura"), ("M8", "nura"), ("M9", "esil"), ("M10", "esil"), ("M12", None))
    error = assert_error(client.post("/api/simulate", json=payload), "CATEGORY_COVERAGE", ["selections"])
    assert error["context"]["missing_categories"] == ["transport", "environment"]


def test_format_errors_follow_original_object_key_order(client, scenario_b):
    scenario_b["selections"][0]["measure_id"] = 123
    payload = {"unexpected": True, **scenario_b}
    assert_error(client.post("/api/simulate", json=payload), "UNEXPECTED_FIELD", ["unexpected"])
    # Reversing the object keys makes the nested type error the first one.
    payload = {**scenario_b, "unexpected": True}
    assert_error(client.post("/api/simulate", json=payload), "INVALID_REQUEST", ["selections", 0, "measure_id"])
