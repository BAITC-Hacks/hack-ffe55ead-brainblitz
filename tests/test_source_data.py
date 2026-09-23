"""Independent transcription of the original «Датасет районов.docx» tables.

Source SHA-256: 434128bfede06afe4d115c13a82fce874a3cf494a24679e1b227b88d4a8aba86.
The constants below were transcribed from the attached document, not generated
from data/*.json, an application function, or the API contract's JSON examples.
The DOCX is not required to run the tests. District/category IDs are the agreed
API names; the original document gives their Russian names. The team's stricter
one-per-direction rule is intentional and is tested separately from source data.
"""

import pytest


INDICATORS = ("T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2")
WEIGHTS = (0.10, 0.10, 0.09, 0.11, 0.11, 0.11, 0.09, 0.09, 0.10, 0.10)
LABELS = (
    "Разгрузка дорог",
    "Доступность общественного транспорта",
    "Озеленение",
    "Качество воздуха",
    "Школы и детсады",
    "Поликлиники и первичная медпомощь",
    "Безопасность улиц",
    "Безопасность дорожного движения",
    "Надёжность ЖКХ",
    "Скорость решения обращений жителей",
)

# Source table column order: district, population, T1..C2.
DISTRICTS = (
    ("esil", "Есиль", 0.27, (45, 62, 68, 72, 48, 55, 78, 60, 75, 70)),
    ("almaty", "Алматы", 0.24, (40, 75, 50, 55, 60, 65, 62, 52, 50, 60)),
    ("saryarka", "Сарыарка", 0.20, (50, 70, 42, 40, 62, 68, 58, 55, 45, 55)),
    ("baikonur", "Байконур", 0.13, (52, 68, 55, 50, 58, 60, 52, 58, 55, 58)),
    ("nura", "Нура", 0.16, (55, 40, 45, 65, 38, 35, 55, 50, 60, 50)),
)
CATEGORIES = (
    ("transport", "Транспорт"),
    ("environment", "Экология"),
    ("social", "Соцсфера"),
    ("safety", "Безопасность"),
    ("services", "Сервисы"),
)

# ID, name, category, scope, cost, lag, FULL effects before applying the lag.
MEASURES = (
    ("M1", "Выделенные полосы для автобусов", "transport", "district", 18, 2,
     {"T1": 6, "T2": 9}),
    ("M2", "Умные светофоры (адаптивное управление)", "transport", "city", 22, 2,
     {"T1": 4, "B2": 3}),
    ("M3", "Линия ЛРТ / расширение", "transport", "district", 30, 4,
     {"T1": 16, "T2": 20, "E2": 4}),
    ("M4", "Парк / сквер", "environment", "district", 15, 2,
     {"E1": 12, "E2": 3, "B1": 2}),
    ("M5", "Перевод частного сектора на чистое топливо", "environment", "district", 25, 3,
     {"E2": 14, "C1": 4}),
    ("M6", "Городская программа озеленения и ветрозащитных полос", "environment", "city", 20, 4,
     {"E1": 5, "E2": 3}),
    ("M7", "Школа + детсад (модульное строительство)", "social", "district", 24, 3,
     {"S1": 16}),
    ("M8", "Центр семейного здоровья / поликлиника", "social", "district", 20, 3,
     {"S2": 14}),
    ("M9", "Дворовые спорт-хабы", "social", "district", 10, 1,
     {"S1": 3, "S2": 3, "B1": 3}),
    ("M10", "Освещение и камеры (расширение Safe City)", "safety", "district", 12, 1,
     {"B1": 12, "B2": 2}),
    ("M11", "Безопасные переходы и школьные зоны", "safety", "district", 10, 1,
     {"B2": 12, "T1": -2}),
    ("M12", "Единая цифровая платформа обращений", "services", "city", 14, 1,
     {"C2": 5}),
    ("M13", "Модернизация тепло- и водосетей", "services", "district", 28, 4,
     {"C1": 18, "E2": 2}),
    ("M14", "Аварийные бригады ЖКХ + раннее оповещение", "services", "city", 16, 1,
     {"C1": 5, "C2": 2}),
)


def test_indicator_labels_and_all_weights_match_original_document(dataset_files):
    actual = dataset_files["districts.json"]
    assert actual["indicators"] == list(INDICATORS)
    assert actual["weights"] == dict(zip(INDICATORS, WEIGHTS, strict=True))
    assert actual["indicator_labels"] == dict(zip(INDICATORS, LABELS, strict=True))


def test_catalog_ids_names_and_order_match_document_and_fixed_contract(dataset_files):
    assert [item["id"] for item in dataset_files["districts.json"]["districts"]] == [
        row[0] for row in DISTRICTS
    ]
    assert [item["id"] for item in dataset_files["measures.json"]["measures"]] == [
        row[0] for row in MEASURES
    ]
    assert dataset_files["measures.json"]["categories"] == [
        {"id": category, "name": name} for category, name in CATEGORIES
    ]


@pytest.mark.parametrize("district_id,name,population,values", DISTRICTS, ids=[row[0] for row in DISTRICTS])
def test_every_district_value_matches_original_document(dataset_files, district_id, name, population, values):
    actual = next(item for item in dataset_files["districts.json"]["districts"] if item["id"] == district_id)
    assert actual == {
        "id": district_id,
        "name": name,
        "population_share": population,
        "indicators": dict(zip(INDICATORS, values, strict=True)),
    }


@pytest.mark.parametrize("measure_id,name,category,scope,cost,lag,effects", MEASURES, ids=[row[0] for row in MEASURES])
def test_every_measure_field_matches_original_document(dataset_files, measure_id, name, category, scope, cost, lag, effects):
    actual = next(item for item in dataset_files["measures.json"]["measures"] if item["id"] == measure_id)
    assert actual == {
        "id": measure_id,
        "name": name,
        "category": category,
        "scope": scope,
        "cost": cost,
        "lag_quarters": lag,
        "effects": effects,
    }


def test_all_synergy_targets_and_fixed_bonuses_match_original_document(dataset_files):
    assert dataset_files["measures.json"]["synergies"] == [
        {"measure_ids": ["M1", "M2"], "target_measure_id": "M1", "effects": {"T1": 2}},
        {"measure_ids": ["M10", "M12"], "target_measure_id": "M10", "effects": {"B1": 2}},
        {"measure_ids": ["M5", "M6"], "target_measure_id": "M5", "effects": {"E2": 2}},
    ]


def test_all_conflict_pairs_and_conditions_match_original_document(dataset_files):
    assert dataset_files["measures.json"]["conflicts"] == [
        {"measure_ids": ["M1", "M3"], "condition": "any_district"},
        {"measure_ids": ["M4", "M7"], "condition": "same_district"},
        {"measure_ids": ["M5", "M13"], "condition": "same_district"},
    ]


def test_source_common_rules_and_intentional_stricter_direction_rule(dataset_files):
    actual = dataset_files["measures.json"]
    assert actual["budget"] == 100
    assert actual["horizon_quarters"] == 8
    assert actual["required_selection_count"] == 5
    # Source permits <= 2 per direction; the team explicitly chose all 5 directions.
    assert actual["max_per_category"] == 1
    assert actual["required_categories"] == [category for category, _ in CATEGORIES]
    assert actual["rules_version"] == "five-directions-v1"
    assert actual["dataset_version"] == dataset_files["districts.json"]["dataset_version"] == "city-v1"
