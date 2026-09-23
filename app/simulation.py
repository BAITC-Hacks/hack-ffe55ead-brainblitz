"""Pure calculations for the city-v1 dataset; no I/O, HTTP, or AI calls."""

from collections.abc import Mapping, Sequence
from math import fsum
from typing import Any

from app.models import (
    AppliedEffect,
    AppliedSynergy,
    CriticalIndicator,
    DistrictResult,
    ScoreBreakdown,
    Selection,
    SimulationResult,
)
from app.validator import validate_selections


def summarize(
    indicators: Mapping[str, Mapping[str, float]], config: Mapping[str, Any]
) -> tuple[dict[str, float], ScoreBreakdown, list[CriticalIndicator], float]:
    """Score an indicator snapshot, including the empty-action baseline."""
    district_scores = {
        district["id"]: fsum(
            config["weights"][key] * indicators[district["id"]][key]
            for key in config["indicators"]
        )
        for district in config["districts"]
    }
    city_average = fsum(
        district["population_share"] * district_scores[district["id"]]
        for district in config["districts"]
    )
    # dict insertion order follows the fixed district order, resolving ties.
    weakest = min(district_scores, key=district_scores.__getitem__)
    critical = [
        CriticalIndicator(
            district_id=district["id"], indicator=key,
            value=indicators[district["id"]][key],
        )
        for district in config["districts"]
        for key in config["indicators"]
        if indicators[district["id"]][key] < 40
    ]
    breakdown = ScoreBreakdown(
        city_average=city_average,
        weakest_district_id=weakest,
        weakest_district_score=district_scores[weakest],
        critical_count=len(critical),
    )
    score = 0.7 * city_average + 0.3 * district_scores[weakest] - len(critical)
    return district_scores, breakdown, critical, score


def apply_effects(
    selections: Sequence[Selection], config: Mapping[str, Any]
) -> tuple[dict[str, dict[str, float]], list[AppliedEffect], list[AppliedSynergy]]:
    """Apply the source model to known IDs; public simulate() validates first.

    This low-level function also permits testing the two source synergies that
    are unreachable under the current one-measure-per-category HTTP rules.
    """
    measures = {measure["id"]: measure for measure in config["measures"]}
    ordered = sorted(selections, key=lambda choice: int(choice.measure_id[1:]))
    selected = {choice.measure_id: choice for choice in ordered}
    after = {
        district["id"]: dict(district["indicators"])
        for district in config["districts"]
    }
    increments = {
        district_id: {key: [] for key in config["indicators"]}
        for district_id in after
    }
    applied_effects = []
    for choice in ordered:
        measure = measures[choice.measure_id]
        fraction = (
            config["horizon_quarters"] - measure["lag_quarters"]
        ) / config["horizon_quarters"]
        realized = {
            key: measure["effects"][key] * fraction
            for key in config["indicators"] if key in measure["effects"]
        }
        targets = list(after) if measure["scope"] == "city" else [choice.district_id]
        for district_id in targets:
            for key, effect in realized.items():
                increments[district_id][key].append(effect)
        applied_effects.append(AppliedEffect(
            measure_id=choice.measure_id, scope=measure["scope"],
            district_id=choice.district_id, realized_effects=realized,
        ))

    applied_synergies = []
    for synergy in config["synergies"]:
        if not all(measure_id in selected for measure_id in synergy["measure_ids"]):
            continue
        district_id = selected[synergy["target_measure_id"]].district_id
        effects = {
            key: synergy["effects"][key]
            for key in config["indicators"] if key in synergy["effects"]
        }
        for key, effect in effects.items():
            increments[district_id][key].append(effect)
        applied_synergies.append(AppliedSynergy(
            measure_ids=list(synergy["measure_ids"]),
            district_id=district_id, effects=effects,
        ))

    # Clip once, after positive/negative effects AND fixed synergy bonuses.
    for district_id, values in after.items():
        for key in config["indicators"]:
            values[key] = min(100.0, max(0.0, fsum(
                [values[key], *increments[district_id][key]]
            )))
    return after, applied_effects, applied_synergies


def simulate(
    selections: list[Selection], config: Mapping[str, Any]
) -> SimulationResult:
    """Validate and calculate one scenario without changing the shared data."""
    canonical = validate_selections(selections, config)
    before = {
        district["id"]: dict(district["indicators"])
        for district in config["districts"]
    }
    before_scores, before_summary, critical_before, baseline = summarize(before, config)
    after, applied_effects, applied_synergies = apply_effects(canonical, config)
    after_scores, after_summary, critical_after, final_score = summarize(after, config)
    prices = {measure["id"]: measure["cost"] for measure in config["measures"]}
    total_cost = sum(prices[choice.measure_id] for choice in canonical)
    districts = [
        DistrictResult(
            id=district["id"], name=district["name"],
            population_share=district["population_share"],
            before=before[district["id"]], after=after[district["id"]],
            changes={
                key: after[district["id"]][key] - before[district["id"]][key]
                for key in config["indicators"]
            },
            score_before=before_scores[district["id"]],
            score_after=after_scores[district["id"]],
        )
        for district in config["districts"]
    ]
    return SimulationResult(
        contract_version=config["contract_version"],
        dataset_version=config["dataset_version"], rules_version=config["rules_version"],
        selections=canonical, baseline_score=baseline, final_score=final_score,
        score_delta=final_score - baseline,
        total_cost=total_cost, remaining_budget=config["budget"] - total_cost,
        score_breakdown={"before": before_summary, "after": after_summary},
        districts=districts, critical_before=critical_before, critical_after=critical_after,
        applied_effects=applied_effects, applied_synergies=applied_synergies,
        explanation="Расчёт выполнен по учебной модели. Объяснение AI запрашивается отдельно.",
        explanation_source="rules",
    )
