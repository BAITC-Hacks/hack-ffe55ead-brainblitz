"""Public request and response schemas for API contract 2.0.

Selections use strict strings, not ID enums: business validation must run in the
documented order after the entire request has passed structural validation.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictInt,
    StrictStr,
    model_validator,
)


DistrictID = Literal["esil", "almaty", "saryarka", "baikonur", "nura"]
CategoryID = Literal["transport", "environment", "social", "safety", "services"]
IndicatorID = Literal["T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2"]
MeasureID = Literal[
    "M1", "M2", "M3", "M4", "M5", "M6", "M7",
    "M8", "M9", "M10", "M11", "M12", "M13", "M14",
]
Scope = Literal["district", "city"]
INDICATOR_IDS = ("T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2")


def _complete_indicators(values: dict) -> dict:
    if set(values) != set(INDICATOR_IDS):
        raise ValueError("Exactly the ten configured indicator IDs are required.")
    return {indicator: values[indicator] for indicator in INDICATOR_IDS}


IndicatorValues = Annotated[
    dict[IndicatorID, FiniteFloat], AfterValidator(_complete_indicators)
]
IndicatorLabels = Annotated[
    dict[IndicatorID, StrictStr], AfterValidator(_complete_indicators)
]
Effects = Annotated[dict[IndicatorID, FiniteFloat], Field(min_length=1)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Selection(ContractModel):
    measure_id: StrictStr
    district_id: StrictStr | None = None


class SimulationRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    selections: list[Selection]


class Versions(ContractModel):
    contract_version: Literal["2.0"]
    dataset_version: Literal["city-v1"]
    rules_version: Literal["five-directions-v1"]


class Category(ContractModel):
    id: CategoryID
    name: StrictStr


class District(ContractModel):
    id: DistrictID
    name: StrictStr
    population_share: Annotated[FiniteFloat, Field(ge=0, le=1)]
    indicators: IndicatorValues


class Measure(ContractModel):
    id: MeasureID
    name: StrictStr
    category: CategoryID
    scope: Scope
    cost: NonNegativeInt
    lag_quarters: Annotated[StrictInt, Field(ge=0, le=8)]
    effects: Effects


class Conflict(ContractModel):
    measure_ids: Annotated[list[MeasureID], Field(min_length=2, max_length=2)]
    condition: Literal["any_district", "same_district"]


class Synergy(ContractModel):
    measure_ids: Annotated[list[MeasureID], Field(min_length=2, max_length=2)]
    target_measure_id: MeasureID
    effects: Effects


class ConfigResponse(Versions):
    budget: NonNegativeInt
    horizon_quarters: Annotated[StrictInt, Field(gt=0)]
    required_selection_count: Annotated[StrictInt, Field(gt=0)]
    required_categories: Annotated[list[CategoryID], Field(min_length=5, max_length=5)]
    max_per_category: Annotated[StrictInt, Field(gt=0)]
    baseline_score: FiniteFloat
    categories: Annotated[list[Category], Field(min_length=5, max_length=5)]
    indicators: Annotated[list[IndicatorID], Field(min_length=10, max_length=10)]
    indicator_labels: IndicatorLabels
    weights: IndicatorValues
    districts: Annotated[list[District], Field(min_length=5, max_length=5)]
    measures: Annotated[list[Measure], Field(min_length=14, max_length=14)]
    conflicts: list[Conflict]
    synergies: list[Synergy]


class ScoreBreakdown(ContractModel):
    city_average: FiniteFloat
    weakest_district_id: DistrictID
    weakest_district_score: FiniteFloat
    critical_count: NonNegativeInt


class ScoreBreakdowns(ContractModel):
    before: ScoreBreakdown
    after: ScoreBreakdown


class DistrictResult(ContractModel):
    id: DistrictID
    name: StrictStr
    population_share: Annotated[FiniteFloat, Field(ge=0, le=1)]
    before: IndicatorValues
    after: IndicatorValues
    changes: IndicatorValues
    score_before: FiniteFloat
    score_after: FiniteFloat


class CriticalIndicator(ContractModel):
    district_id: DistrictID
    indicator: IndicatorID
    value: Annotated[FiniteFloat, Field(lt=40)]


class AppliedEffect(ContractModel):
    measure_id: MeasureID
    scope: Scope
    district_id: DistrictID | None
    realized_effects: Effects


class AppliedSynergy(ContractModel):
    measure_ids: Annotated[list[MeasureID], Field(min_length=2, max_length=2)]
    district_id: DistrictID
    effects: Effects


class SimulationResult(Versions):
    selections: Annotated[list[Selection], Field(min_length=5, max_length=5)]
    baseline_score: FiniteFloat
    final_score: FiniteFloat
    score_delta: FiniteFloat
    total_cost: NonNegativeInt
    remaining_budget: NonNegativeInt
    score_breakdown: ScoreBreakdowns
    districts: Annotated[list[DistrictResult], Field(min_length=5, max_length=5)]
    critical_before: list[CriticalIndicator]
    critical_after: list[CriticalIndicator]
    applied_effects: Annotated[list[AppliedEffect], Field(min_length=5, max_length=5)]
    applied_synergies: list[AppliedSynergy]
    explanation: StrictStr
    explanation_source: Literal["rules"]


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Text must contain non-whitespace characters.")
    return value


ShortAnalysisText = Annotated[
    StrictStr, Field(min_length=1, max_length=300), AfterValidator(_nonblank)
]


class EvidenceStatement(ContractModel):
    text: Annotated[
        StrictStr, Field(min_length=1, max_length=600), AfterValidator(_nonblank)
    ]
    evidence_paths: Annotated[list[StrictStr], Field(min_length=1, max_length=4)]


class Analysis(ContractModel):
    summary: EvidenceStatement
    strengths: Annotated[list[EvidenceStatement], Field(max_length=2)]
    risks: Annotated[list[EvidenceStatement], Field(max_length=2)]
    tradeoff: EvidenceStatement
    reflection_question: ShortAnalysisText
    limitations: Annotated[list[ShortAnalysisText], Field(min_length=1, max_length=2)]

    def statements(self) -> list[EvidenceStatement]:
        return [self.summary, *self.strengths, *self.risks, self.tradeoff]

    @model_validator(mode="after")
    def check_word_count(self) -> "Analysis":
        texts = [item.text for item in self.statements()]
        texts.extend([self.reflection_question, *self.limitations])
        if sum(len(text.split()) for text in texts) > 180:
            raise ValueError("Analysis must not exceed 180 words.")
        return self


UnavailableReason = Literal[
    "disabled", "not_configured", "timeout", "rate_limited",
    "provider_error", "invalid_response", "refused",
]


class AnalysisResult(Versions):
    selections: Annotated[list[Selection], Field(min_length=5, max_length=5)]
    baseline_score: FiniteFloat
    final_score: FiniteFloat
    status: Literal["ok", "unavailable"]
    analysis: Analysis | None
    unavailable_reason: UnavailableReason | None
    message: StrictStr

    @model_validator(mode="after")
    def check_status(self) -> "AnalysisResult":
        if self.status == "ok":
            if self.analysis is None or self.unavailable_reason is not None or self.message != "":
                raise ValueError("Successful analysis requires data and no failure message.")
        elif self.analysis is not None or self.unavailable_reason is None or not self.message.strip():
            raise ValueError("Unavailable analysis requires a reason and a message, without data.")
        return self


ErrorCode = Literal[
    "INVALID_REQUEST", "UNEXPECTED_FIELD", "INVALID_SELECTION_COUNT",
    "UNKNOWN_MEASURE", "DUPLICATE_MEASURE", "DISTRICT_REQUIRED",
    "UNKNOWN_DISTRICT", "DISTRICT_NOT_ALLOWED", "CATEGORY_COVERAGE",
    "INCOMPATIBLE_MEASURES", "BUDGET_EXCEEDED", "INTERNAL_ERROR",
]


class ErrorItem(ContractModel):
    code: ErrorCode
    message: Annotated[StrictStr, Field(min_length=1)]
    path: list[StrictStr | StrictInt]
    context: dict[str, Any]


class ErrorResponse(ContractModel):
    detail: Annotated[list[ErrorItem], Field(min_length=1, max_length=1)]


class HealthResponse(ContractModel):
    status: Literal["ok"]
