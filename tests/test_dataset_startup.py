"""Invalid server data must fail during startup, before partial responses."""

from fastapi.testclient import TestClient
import pytest

from app.main import create_app


@pytest.mark.parametrize("file_index,path,value", [
    (0, ("dataset_version",), "another-version"),
    (1, ("rules_version",), "another-ruleset"),
    (1, ("budget",), 101),
    (1, ("horizon_quarters",), 9),
    (0, ("weights", "T1"), 0.2),
    (0, ("weights", "T1"), -0.1),
    (0, ("weights", "T1"), True),
    (0, ("weights", "T1"), float("nan")),
    (0, ("districts", 0, "population_share"), 0.9),
    (0, ("districts", 0, "population_share"), -0.27),
    (0, ("districts", 0, "id"), "nura"),
    (0, ("districts", 0, "indicators", "T1"), -1),
    (0, ("districts", 0, "indicators", "T1"), 101),
    (0, ("districts", 0, "indicators", "T1"), "45"),
    (0, ("districts", 0, "indicators", "T1"), float("inf")),
    (1, ("measures", 0, "id"), "M2"),
    (1, ("measures", 0, "category"), "tourism"),
    (1, ("measures", 0, "scope"), "region"),
    (1, ("measures", 0, "cost"), -1),
    (1, ("measures", 0, "cost"), 18.5),
    (1, ("measures", 0, "cost"), True),
    (1, ("measures", 0, "lag_quarters"), -1),
    (1, ("measures", 0, "lag_quarters"), 9),
    (1, ("measures", 0, "lag_quarters"), 2.5),
    (1, ("measures", 0, "effects"), {}),
    (1, ("measures", 0, "effects"), {"unknown": 5}),
    (1, ("measures", 0, "effects"), {"T1": float("inf")}),
    (1, ("conflicts", 0, "measure_ids"), ["M1", "M99"]),
    (1, ("conflicts", 0, "measure_ids"), ["M1", "M1"]),
    (1, ("conflicts", 0, "condition"), "unknown"),
    (1, ("synergies", 0, "measure_ids"), ["M1", "M99"]),
    (1, ("synergies", 0, "target_measure_id"), "M7"),
    (1, ("synergies", 0, "target_measure_id"), "M2"),
    (1, ("synergies", 0, "effects"), {"unknown": 2}),
])
def test_corrupt_dataset_is_rejected_at_startup(write_dataset, file_index, path, value):
    def mutate(districts, measures):
        target = (districts, measures)[file_index]
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value

    data_dir = write_dataset(mutate)
    with pytest.raises(ValueError):
        with TestClient(create_app(data_dir=data_dir)):
            pytest.fail("Corrupt data must not reach a successful application startup")


@pytest.mark.parametrize("field", ["districts", "indicators"])
def test_missing_catalog_entry_is_rejected_at_startup(write_dataset, field):
    def mutate(districts, measures):
        districts[field].pop()

    data_dir = write_dataset(mutate)
    with pytest.raises(ValueError):
        with TestClient(create_app(data_dir=data_dir)):
            pytest.fail("Incomplete dataset started successfully")


def test_missing_measure_is_rejected_at_startup(write_dataset):
    data_dir = write_dataset(lambda districts, measures: measures["measures"].pop())
    with pytest.raises(ValueError):
        with TestClient(create_app(data_dir=data_dir)):
            pytest.fail("Incomplete catalog started successfully")


def test_duplicate_json_key_is_rejected_at_startup(write_dataset):
    data_dir = write_dataset(lambda districts, measures: None)
    path = data_dir / "districts.json"
    # A duplicate would silently overwrite a source value in an ordinary decoder.
    path.write_text(path.read_text(encoding="utf-8").replace('"T1": 45', '"T1": 45, "T1": 55', 1), encoding="utf-8")
    with pytest.raises(ValueError):
        with TestClient(create_app(data_dir=data_dir)):
            pytest.fail("Duplicate source keys started successfully")


def test_missing_dataset_does_not_use_fallback(tmp_path):
    with pytest.raises(FileNotFoundError):
        with TestClient(create_app(data_dir=tmp_path)):
            pytest.fail("Missing data must not be replaced with a simplified dataset")
