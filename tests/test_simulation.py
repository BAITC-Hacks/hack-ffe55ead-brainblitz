import json
from pathlib import Path

import pytest

from app.models import Selection
from app.simulation import quality_of_life_score, simulate
from app.validator import ScenarioValidationError


ROOT = Path(__file__).resolve().parent.parent


def load_data(name: str) -> list[dict]:
    with (ROOT / "data" / name).open(encoding="utf-8") as file:
        payload = json.load(file)
    return next(iter(payload.values()))


DISTRICTS = load_data("districts.json")
MEASURES = load_data("measures.json")
REFERENCE = [
    Selection(measure_id="priority_bus_lanes"),
    Selection(measure_id="district_clinic", district_id="saryarka"),
    Selection(measure_id="neighborhood_park", district_id="baikonur"),
    Selection(measure_id="school_modernization", district_id="almaty"),
    Selection(measure_id="smart_street_lighting"),
]


def test_baseline_score() -> None:
    assert quality_of_life_score(DISTRICTS) == 52.56


def test_reference_scenario() -> None:
    result = simulate(REFERENCE, DISTRICTS, MEASURES)
    assert result.final_score == 56.54
    assert result.total_cost == 98


def test_result_is_order_independent() -> None:
    forward = simulate(REFERENCE, DISTRICTS, MEASURES)
    backward = simulate(list(reversed(REFERENCE)), DISTRICTS, MEASURES)
    assert forward == backward


def test_conflicting_measures_are_rejected() -> None:
    selections = [
        Selection(measure_id="priority_bus_lanes"),
        Selection(measure_id="car_lane_expansion"),
        Selection(measure_id="district_clinic", district_id="almaty"),
        Selection(measure_id="neighborhood_park", district_id="baikonur"),
        Selection(measure_id="school_modernization", district_id="esil"),
    ]
    with pytest.raises(ScenarioValidationError, match="Incompatible"):
        simulate(selections, DISTRICTS, MEASURES)
