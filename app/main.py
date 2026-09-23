import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.ai import explain_result
from app.models import SimulationRequest, SimulationResponse
from app.simulation import quality_of_life_score, simulate
from app.validator import BUDGET, ScenarioValidationError


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _load_json(name: str) -> dict:
    with (DATA_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


DISTRICTS = _load_json("districts.json")["districts"]
MEASURES = _load_json("measures.json")["measures"]

app = FastAPI(
    title="Akim for 5 Hours",
    version="0.1.0",
    description="Deterministic city budget simulation API.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config() -> dict:
    return {
        "budget": BUDGET,
        "baseline_score": quality_of_life_score(DISTRICTS),
        "districts": DISTRICTS,
        "indicators": list(DISTRICTS[0]["indicators"]),
        "measures": MEASURES,
    }


@app.post("/simulate", response_model=SimulationResponse)
def run_simulation(request: SimulationRequest) -> SimulationResponse:
    try:
        result = simulate(request.selections, DISTRICTS, MEASURES)
    except ScenarioValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    result.explanation = explain_result(result)
    return result
