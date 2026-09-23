"""One FastAPI application serving the contract-v2 mathematical backend."""

import json
import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from math import isclose
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.models import ConfigResponse, ErrorResponse, SimulationRequest, SimulationResult
from app.simulation import simulate, summarize
from app.validator import ScenarioValidationError, normalize_request_error

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_VERSION = "2.0"
DISTRICTS = ("esil", "almaty", "saryarka", "baikonur", "nura")
INDICATORS = ("T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2")
CATEGORIES = ("transport", "environment", "social", "safety", "services")
DISTRICT_FIELDS = {
    "dataset_version", "indicators", "indicator_labels", "weights", "districts",
}
MEASURE_FIELDS = {
    "dataset_version", "rules_version", "budget", "horizon_quarters",
    "required_selection_count", "required_categories", "max_per_category",
    "categories", "measures", "conflicts", "synergies",
}
LOGGER = logging.getLogger(__name__)


def freeze(value: Any) -> Any:
    """Recursively freeze the one shared snapshot, not just its outer dict."""
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Create fresh JSON containers for HTTP serialization."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate dataset key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Non-finite dataset number: {value}")


def _read_data(path: Path, required: set[str]) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        data = json.load(source, object_pairs_hook=_json_pairs, parse_constant=_invalid_constant)
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError(f"Invalid fields in {path.name}")
    return data


def _check_integrity(config: dict[str, Any]) -> None:
    """Cross-reference checks complement Pydantic's field-level validation."""
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    require(config["dataset_version"] == "city-v1", "Unsupported dataset version")
    require(config["rules_version"] == "five-directions-v1", "Unsupported rules version")
    require(config["budget"] == 100, "Budget must be 100")
    require(config["horizon_quarters"] == 8, "Horizon must be 8")
    require(config["required_selection_count"] == 5, "Five selections required")
    require(config["max_per_category"] == 1, "One measure per category required")
    require(tuple(config["indicators"]) == INDICATORS, "Invalid indicator IDs/order")
    require(tuple(config["required_categories"]) == CATEGORIES, "Invalid required categories")
    require(tuple(item["id"] for item in config["categories"]) == CATEGORIES, "Invalid categories")
    require(tuple(item["id"] for item in config["districts"]) == DISTRICTS, "Invalid district IDs/order")
    require(set(config["weights"]) == set(INDICATORS), "Invalid weight keys")
    require(set(config["indicator_labels"]) == set(INDICATORS), "Invalid indicator labels")
    require(isclose(sum(config["weights"].values()), 1.0, abs_tol=1e-12, rel_tol=0), "Weights must sum to 1")
    require(all(weight >= 0 for weight in config["weights"].values()), "Negative weight")
    require(isclose(sum(d["population_share"] for d in config["districts"]), 1.0, abs_tol=1e-12, rel_tol=0), "Population shares must sum to 1")
    for district in config["districts"]:
        require(0 <= district["population_share"] <= 1, "Invalid population share")
        require(set(district["indicators"]) == set(INDICATORS), "Invalid district indicators")
        require(all(0 <= n <= 100 for n in district["indicators"].values()), "Indicator outside 0..100")
    measures = {measure["id"]: measure for measure in config["measures"]}
    require(len(config["measures"]) == 14 and set(measures) == {f"M{i}" for i in range(1, 15)}, "Exactly 14 unique measures required")
    config["measures"].sort(key=lambda measure: int(measure["id"][1:]))
    for measure in config["measures"]:
        require(measure["category"] in CATEGORIES, "Unknown measure category")
        require(measure["scope"] in ("district", "city"), "Unknown measure scope")
        require(type(measure["cost"]) is int and measure["cost"] >= 0, "Invalid cost")
        require(type(measure["lag_quarters"]) is int and 0 <= measure["lag_quarters"] <= 8, "Invalid lag")
        require(bool(measure["effects"]) and set(measure["effects"]) <= set(INDICATORS), "Invalid effect keys")
    for kind in ("conflicts", "synergies"):
        seen = set()
        for item in config[kind]:
            pair = item["measure_ids"]
            require(len(pair) == 2 and len(set(pair)) == 2 and set(pair) <= set(measures), f"Invalid {kind} pair")
            require(frozenset(pair) not in seen, f"Duplicate {kind} pair")
            seen.add(frozenset(pair))
            if kind == "conflicts":
                require(item["condition"] in ("any_district", "same_district"), "Unknown conflict condition")
                if item["condition"] == "same_district":
                    require(all(measures[mid]["scope"] == "district" for mid in pair), "Local conflict needs local measures")
            else:
                target = item["target_measure_id"]
                require(target in pair and measures[target]["scope"] == "district", "Invalid synergy target")
                require(bool(item["effects"]) and set(item["effects"]) <= set(INDICATORS), "Invalid synergy effects")


def load_config(data_dir: Path) -> Mapping[str, Any]:
    districts = _read_data(data_dir / "districts.json", DISTRICT_FIELDS)
    measures = _read_data(data_dir / "measures.json", MEASURE_FIELDS)
    if districts["dataset_version"] != measures["dataset_version"]:
        raise ValueError("Dataset versions do not match")
    raw = {**districts, **measures, "contract_version": CONTRACT_VERSION, "baseline_score": 0.0}
    # Validate all scalar types/ranges/finite numbers before doing arithmetic.
    parsed = ConfigResponse.model_validate(raw).model_dump()
    _check_integrity(parsed)
    indicators = {district["id"]: district["indicators"] for district in parsed["districts"]}
    parsed["baseline_score"] = summarize(indicators, parsed)[3]
    return freeze(parsed)


def create_app(data_dir: Path | None = None) -> FastAPI:
    source_dir = Path(data_dir) if data_dir is not None else ROOT / "data"

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.config = load_config(source_dir)
        yield

    application = FastAPI(title="Аким на 5 часов", version=CONTRACT_VERSION, lifespan=lifespan)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        error = normalize_request_error(exc, exc.body)
        return JSONResponse(status_code=422, content=error.model_dump())

    @application.exception_handler(ScenarioValidationError)
    async def invalid_scenario(request: Request, exc: ScenarioValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.detail})

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        LOGGER.error("Unexpected backend error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": [{
            "code": "INTERNAL_ERROR",
            "message": "Не удалось выполнить расчёт. Повторите попытку.",
            "path": [], "context": {},
        }]})

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/config", response_model=ConfigResponse)
    def config(request: Request):
        return thaw(request.app.state.config)

    @application.post(
        "/api/simulate", response_model=SimulationResult,
        responses={422: {"model": ErrorResponse}},
    )
    def run_simulation(payload: SimulationRequest, request: Request):
        return simulate(payload.selections, request.app.state.config)

    # The frontend is maintained separately. Serve it when its files exist;
    # the API can start and be tested before that folder has been added.
    static_dir = ROOT / "static"
    if static_dir.is_dir():
        application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/", include_in_schema=False)
    def index():
        index_file = static_dir / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="Frontend ещё не добавлен.")
        return FileResponse(index_file)

    return application


app = create_app()
