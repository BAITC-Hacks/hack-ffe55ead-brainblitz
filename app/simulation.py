from copy import deepcopy
from statistics import fmean

from app.models import DistrictResult, Selection, SimulationResponse
from app.validator import BUDGET, validate_selections


def quality_of_life_score(districts: list[dict]) -> float:
    values = [
        float(value)
        for district in districts
        for value in district["indicators"].values()
    ]
    return round(fmean(values), 2)


def _clamp(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 2)


def simulate(
    selections: list[Selection],
    districts: list[dict],
    measures: list[dict],
) -> SimulationResponse:
    working = deepcopy(districts)
    district_by_id = {district["id"]: district for district in working}
    measure_by_id = {measure["id"]: measure for measure in measures}

    total_cost = validate_selections(
        selections,
        measures,
        set(district_by_id),
    )
    baseline_score = quality_of_life_score(working)
    before = {
        district["id"]: deepcopy(district["indicators"])
        for district in working
    }

    # Sort by ID to guarantee order-independent output and arithmetic.
    for selection in sorted(selections, key=lambda item: item.measure_id):
        measure = measure_by_id[selection.measure_id]
        targets = (
            working
            if measure["scope"] == "city"
            else [district_by_id[selection.district_id]]
        )
        for district in targets:
            for indicator, delta in measure["effects"].items():
                district["indicators"][indicator] = _clamp(
                    district["indicators"][indicator] + float(delta)
                )

    selected_ids = {item.measure_id for item in selections}
    for measure in measures:
        synergy = measure.get("synergy")
        if (
            synergy
            and measure["id"] in selected_ids
            and set(synergy["requires"]).issubset(selected_ids)
        ):
            for district in working:
                for indicator, delta in synergy["effects"].items():
                    district["indicators"][indicator] = _clamp(
                        district["indicators"][indicator] + float(delta)
                    )

    results = []
    for district in working:
        old = before[district["id"]]
        new = district["indicators"]
        results.append(
            DistrictResult(
                id=district["id"],
                name=district["name"],
                before=old,
                after=new,
                changes={
                    key: round(float(new[key]) - float(old[key]), 2)
                    for key in old
                },
            )
        )

    final_score = quality_of_life_score(working)
    return SimulationResponse(
        baseline_score=baseline_score,
        final_score=final_score,
        total_cost=total_cost,
        remaining_budget=BUDGET - total_cost,
        districts=results,
        explanation=(
            f"The selected initiatives change the Quality of Life Score "
            f"from {baseline_score:.2f} to {final_score:.2f}."
        ),
    )
