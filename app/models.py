from typing import Literal

from pydantic import BaseModel, Field, model_validator


IndicatorName = Literal["mobility", "safety", "environment", "healthcare", "education"]


class Selection(BaseModel):
    measure_id: str
    district_id: str | None = None


class SimulationRequest(BaseModel):
    selections: list[Selection] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def unique_measures(self) -> "SimulationRequest":
        ids = [item.measure_id for item in self.selections]
        if len(ids) != len(set(ids)):
            raise ValueError("Each initiative can be selected only once.")
        return self


class DistrictResult(BaseModel):
    id: str
    name: str
    before: dict[IndicatorName, float]
    after: dict[IndicatorName, float]
    changes: dict[IndicatorName, float]


class SimulationResponse(BaseModel):
    baseline_score: float
    final_score: float
    total_cost: int
    remaining_budget: int
    districts: list[DistrictResult]
    explanation: str
