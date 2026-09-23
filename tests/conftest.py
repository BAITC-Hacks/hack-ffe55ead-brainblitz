"""Independent contract examples are the HTTP acceptance-test oracle."""

from copy import deepcopy
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def contract_examples():
    text = (ROOT / "docs" / "api-contract.md").read_text(encoding="utf-8")
    return [json.loads(block) for block in re.findall(r"```json\s*\n(.*?)\n```", text, re.S)]


@pytest.fixture
def expected_config(contract_examples):
    return deepcopy(next(item for item in contract_examples if "weights" in item))


@pytest.fixture
def expected_b(contract_examples):
    return deepcopy(next(item for item in contract_examples if "score_breakdown" in item))


@pytest.fixture
def scenario_b():
    return json.loads((ROOT / "examples" / "scenario_b.json").read_text(encoding="utf-8"))


@pytest.fixture
def scenario_a():
    return json.loads((ROOT / "examples" / "scenario_a.json").read_text(encoding="utf-8"))


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def dataset_files():
    return {
        name: json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        for name in ("districts.json", "measures.json")
    }


@pytest.fixture
def write_dataset(tmp_path, dataset_files):
    def write(mutate):
        copied = deepcopy(dataset_files)
        mutate(copied["districts.json"], copied["measures.json"])
        for name, data in copied.items():
            (tmp_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return tmp_path

    return write


def assert_json_equal(actual, expected, path="$"):
    """Compare every key/value, allowing only specified absolute float error."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert set(actual) == set(expected), path
        for key in expected:
            assert_json_equal(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), path
        assert len(actual) == len(expected), path
        for index, (value, oracle) in enumerate(zip(actual, expected, strict=True)):
            assert_json_equal(value, oracle, f"{path}[{index}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool), path
        assert actual == pytest.approx(expected, abs=1e-8, rel=0), path
    else:
        assert actual == expected, path


def assert_error(response, code, path):
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], list) and len(body["detail"]) == 1
    error = body["detail"][0]
    assert set(error) == {"code", "message", "path", "context"}
    assert error["code"] == code
    assert error["path"] == path
    assert isinstance(error["message"], str) and error["message"].strip()
    assert re.search("[А-Яа-яЁё]", error["message"])
    assert isinstance(error["context"], dict)
    return error
