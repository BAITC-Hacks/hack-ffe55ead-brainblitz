"""Ordered, side-effect-free scenario validation and API error normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from fastapi.exceptions import RequestValidationError

from app.models import ErrorItem, ErrorResponse, Selection


class ScenarioValidationError(ValueError):
    """One public contract error; the HTTP layer translates it to status 422."""

    def __init__(self, item: ErrorItem):
        super().__init__(item.message)
        self.detail = [item.model_dump()]


def _reject(
    code: str, message: str, path: list[str | int], **context: Any
) -> NoReturn:
    raise ScenarioValidationError(
        ErrorItem(code=code, message=message, path=path, context=context)
    )


def validate_selections(
    selections: list[Selection], config: Mapping[str, Any]
) -> list[Selection]:
    """Validate structural models against the immutable server configuration.

    Error paths refer to the original input order. Sorting happens only after
    every stage succeeds, so normalization cannot change the first violation.
    """
    required_count = config["required_selection_count"]
    if len(selections) != required_count:
        _reject(
            "INVALID_SELECTION_COUNT",
            f"Выберите ровно {required_count} мероприятий.",
            ["selections"],
            required_count=required_count,
            actual_count=len(selections),
        )

    measures = {measure["id"]: measure for measure in config["measures"]}
    district_ids = {district["id"] for district in config["districts"]}

    for index, selection in enumerate(selections):
        if selection.measure_id not in measures:
            _reject(
                "UNKNOWN_MEASURE", "Неизвестный ID мероприятия.",
                ["selections", index, "measure_id"],
                measure_id=selection.measure_id,
            )

    seen: set[str] = set()
    for index, selection in enumerate(selections):
        if selection.measure_id in seen:
            _reject(
                "DUPLICATE_MEASURE", "Одно мероприятие нельзя выбирать повторно.",
                ["selections", index, "measure_id"],
                measure_id=selection.measure_id,
            )
        seen.add(selection.measure_id)

    for index, selection in enumerate(selections):
        measure = measures[selection.measure_id]
        path = ["selections", index, "district_id"]
        if measure["scope"] == "district":
            if selection.district_id is None:
                _reject(
                    "DISTRICT_REQUIRED", "Для локального мероприятия выберите район.",
                    path, measure_id=selection.measure_id,
                )
            if selection.district_id not in district_ids:
                _reject(
                    "UNKNOWN_DISTRICT", "Неизвестный ID района.", path,
                    district_id=selection.district_id,
                )
        elif selection.district_id is not None:
            _reject(
                "DISTRICT_NOT_ALLOWED", "Для городского мероприятия район не указывается.",
                path, measure_id=selection.measure_id, district_id=selection.district_id,
            )

    counts = {category: 0 for category in config["required_categories"]}
    for selection in selections:
        counts[measures[selection.measure_id]["category"]] += 1
    if any(count != 1 for count in counts.values()):
        _reject(
            "CATEGORY_COVERAGE",
            "Выберите ровно одно мероприятие каждого из пяти направлений.",
            ["selections"],
            missing_categories=[category for category, count in counts.items() if count == 0],
            category_counts=counts,
        )

    # Visit pairs in input order. Within a pair the public context uses the
    # catalog's stable order, matching M4/M7 and M5/M13 contract examples.
    for left_index, left in enumerate(selections):
        for right in selections[left_index + 1:]:
            selected_pair = {left.measure_id, right.measure_id}
            for conflict in config["conflicts"]:
                if set(conflict["measure_ids"]) != selected_pair:
                    continue
                ids = list(conflict["measure_ids"])
                if conflict["condition"] == "any_district":
                    _reject(
                        "INCOMPATIBLE_MEASURES", f"{ids[0]} и {ids[1]} нельзя выбрать вместе.",
                        ["selections"], measure_ids=ids,
                    )
                if left.district_id == right.district_id:
                    _reject(
                        "INCOMPATIBLE_MEASURES",
                        f"{ids[0]} и {ids[1]} нельзя выбрать в одном районе.",
                        ["selections"], measure_ids=ids, district_id=left.district_id,
                    )

    total_cost = sum(measures[item.measure_id]["cost"] for item in selections)
    budget = config["budget"]
    if total_cost > budget:
        over_by = total_cost - budget
        _reject(
            "BUDGET_EXCEEDED",
            f"Стоимость решений {total_cost} превышает бюджет {budget} на {over_by} единиц.",
            ["selections"], budget=budget, total_cost=total_cost, over_by=over_by,
        )
    return sorted(selections, key=lambda selection: int(selection.measure_id[1:]))


def _public_path(error: dict[str, Any]) -> list[str | int]:
    if error["type"] == "json_invalid":
        return []
    location = list(error.get("loc", ()))
    if location and location[0] == "body":
        location.pop(0)
    return location


def _input_order(path: list[str | int], body: Any) -> tuple[int, ...]:
    """Order Pydantic's schema-ordered errors by actual request traversal."""
    positions: list[int] = []
    current = body
    for part in path:
        if isinstance(current, dict):
            keys = list(current)
            positions.append(keys.index(part) if part in current else len(keys))
            current = current.get(part)
        elif isinstance(current, list) and isinstance(part, int):
            positions.append(part)
            current = current[part] if 0 <= part < len(current) else None
        else:
            positions.append(0)
            current = None
    return tuple(positions)


def normalize_request_error(
    exc: RequestValidationError, body: Any = None
) -> ErrorResponse:
    """Map every malformed request to one safe, stable contract error.

    Error messages never echo the request or Pydantic's raw input/context.
    The actual body is used solely to preserve the order of present fields.
    """
    if body is None:
        body = exc.body
    errors = exc.errors()
    error = min(errors, key=lambda item: _input_order(_public_path(item), body))
    path = _public_path(error)
    error_type = error["type"]
    code = "INVALID_REQUEST"
    context: dict[str, Any] = {}
    if error_type == "extra_forbidden":
        code = "UNEXPECTED_FIELD"
        message = "Неизвестное поле запроса."
    elif error_type == "json_invalid":
        message = "Тело запроса должно содержать корректный JSON."
    elif error_type == "missing":
        message = "Отсутствует обязательное поле запроса."
    elif error_type == "string_type":
        message = "Значение поля должно быть строкой."
    elif error_type == "list_type":
        message = "Поле selections должно быть массивом."
    elif error_type in {"model_type", "model_attributes_type", "dict_type"}:
        message = "Ожидается JSON-объект."
    else:
        message = "Неверный формат или тип данных запроса."
    return ErrorResponse(
        detail=[ErrorItem(code=code, message=message, path=path, context=context)]
    )
