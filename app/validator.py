from collections import Counter

from app.models import Selection


BUDGET = 100


class ScenarioValidationError(ValueError):
    """Raised when a proposed simulation violates a domain rule."""


def validate_selections(
    selections: list[Selection],
    measures: list[dict],
    district_ids: set[str],
) -> int:
    if len(selections) != 5:
        raise ScenarioValidationError("Select exactly five initiatives.")

    by_id = {measure["id"]: measure for measure in measures}
    selected_ids = [selection.measure_id for selection in selections]

    if len(selected_ids) != len(set(selected_ids)):
        raise ScenarioValidationError("Each initiative can be selected only once.")

    unknown = sorted(set(selected_ids) - set(by_id))
    if unknown:
        raise ScenarioValidationError(f"Unknown initiative(s): {', '.join(unknown)}.")

    category_counts = Counter(by_id[item]["category"] for item in selected_ids)
    overloaded = sorted(category for category, count in category_counts.items() if count > 2)
    if overloaded:
        raise ScenarioValidationError(
            f"No more than two initiatives may use a category: {', '.join(overloaded)}."
        )

    for selection in selections:
        measure = by_id[selection.measure_id]
        if measure["scope"] == "district":
            if selection.district_id not in district_ids:
                raise ScenarioValidationError(
                    f"{selection.measure_id} requires a valid district_id."
                )
        elif selection.district_id is not None:
            raise ScenarioValidationError(
                f"{selection.measure_id} is city-wide and cannot have a district_id."
            )

    selected = set(selected_ids)
    for measure_id in selected:
        conflicts = selected.intersection(by_id[measure_id].get("conflicts", []))
        if conflicts:
            conflict = sorted(conflicts)[0]
            raise ScenarioValidationError(
                f"Incompatible initiatives selected: {measure_id} and {conflict}."
            )

    total_cost = sum(int(by_id[item]["cost"]) for item in selected_ids)
    if total_cost > BUDGET:
        raise ScenarioValidationError(
            f"Budget exceeded: {total_cost} used, {BUDGET} available."
        )
    return total_cost
