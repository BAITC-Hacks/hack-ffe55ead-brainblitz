# API-контракт MVP «Аким на 5 часов»

Целевой контракт `1.0`, данные `city-v1`, правила `five-directions-v1`. Согласован со [спецификацией](spec.md). Статус: договор для следующего этапа реализации; не описание уже запущенного сервера.

## 1. Совместимость и общие соглашения

В ветке `codex/mvp-foundation` (`d79041f`) уже существуют `/config`, `/simulate`, `/health`, `SimulationRequest.selections` и основные поля ответа. Сохраняем их имена, включая `DistrictResult.id`, `before`, `after`, `changes`, `baseline_score`, `final_score`, `total_cost`, `remaining_budget`, `explanation`. Поле `decisions` из раннего плана **не используется**. Префикс `/api` не добавляется.

Намеренно меняются справочники: M1–M14 вместо прежних строковых ID мер; T1–C2 вместо пяти укрупнённых индикаторов; пять категорий из спецификации. Добавляются поля результатов и `/analyze`. Старые успешные ответы с другой формулой не являются реализацией этого контракта. При следующих изменениях контракта синхронно обновлять документацию и потребителей.

- Запросы и ответы: JSON UTF-8, `Content-Type: application/json`.
- ID регистрозависимы. Районы: `esil`, `almaty`, `saryarka`, `baikonur`, `nura`. Категории: `transport`, `environment`, `social`, `safety`, `services`.
- Все JSON-примеры ниже синтаксически полные, без многоточий. Числа — эталоны исходной модели, не результаты запуска ветки с каркасом.
- Денежные значения — целые условные единицы. Показатели/оценки — конечные JSON numbers, без намеренного округления. Float-артефакты до 1e-8 допустимы; UI форматирует два знака.
- Никаких cookies, токенов пользователя, сессий и БД для локального MVP. Секрет AI не входит в API-контракт браузера.
- Сервер не принимает пользовательские веса, стоимость, бюджет, исходные показатели, prompt или готовый Score. Неизвестные входные поля отклоняются.
- При сериализации результатов районы идут в порядке `esil, almaty, saryarka, baikonur, nura`, показатели — T1,T2,E1,E2,S1,S2,B1,B2,C1,C2. Меры сортируются по числовой части ID. Порядок выбора не влияет на расчёт.

| Метод | Путь | Успех | Назначение |
| --- | --- | --- | --- |
| GET | `/health` | 200 | Проверка процесса, без запроса к AI |
| GET | `/config` | 200 | Полный фиксированный каталог и исходные данные |
| POST | `/simulate` | 200 | Валидация и независимый от AI расчёт |
| POST | `/analyze` | 200 | Повторный расчёт тех же решений и AI-разбор |

## 2. Общий запрос SimulationRequest

Объект имеет единственное обязательное поле `selections`: массив ровно из пяти объектов Selection. Другие поля запрещены как на верхнем уровне, так и внутри Selection.

| Поле Selection | Тип | Правило |
| --- | --- | --- |
| `measure_id` | string | Обязательное, один из M1–M14, без повторов |
| `district_id` | string или null | Для district обязательно известное ID; для city допускается отсутствие или null |

Пустая строка не заменяет null. Значения других типов не преобразуются в строки. Категорию и scope определяет сервер по каталогу. Требуются ровно одна мера каждой категории, бюджет ≤100, отсутствие несовместимостей. Одинаковая мера в разных районах тоже считается повтором.

### Запрос A — корректный

```json
{
  "selections": [
    {"measure_id": "M1", "district_id": "esil"},
    {"measure_id": "M4", "district_id": "saryarka"},
    {"measure_id": "M7", "district_id": "esil"},
    {"measure_id": "M10", "district_id": "esil"},
    {"measure_id": "M12", "district_id": null}
  ]
}
```

### Запрос B — корректный

Изменяется только район M7. Этот запрос также используется в примере `/analyze`.

```json
{
  "selections": [
    {"measure_id": "M1", "district_id": "esil"},
    {"measure_id": "M4", "district_id": "saryarka"},
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "esil"},
    {"measure_id": "M12", "district_id": null}
  ]
}
```

## 3. GET /health

Без тела запроса. Ответ означает доступность процесса и не утверждает, что AI-провайдер доступен.

```json
{"status": "ok"}
```

## 4. GET /config

Без тела запроса. Ответ ConfigResponse, HTTP 200:

```json
{
  "contract_version": "1.0",
  "dataset_version": "city-v1",
  "rules_version": "five-directions-v1",
  "budget": 100,
  "horizon_quarters": 8,
  "required_selection_count": 5,
  "required_categories": ["transport", "environment", "social", "safety", "services"],
  "max_per_category": 1,
  "baseline_score": 52.55768,
  "categories": [
    {"id": "transport", "name": "Транспорт"},
    {"id": "environment", "name": "Экология"},
    {"id": "social", "name": "Соцсфера"},
    {"id": "safety", "name": "Безопасность"},
    {"id": "services", "name": "Сервисы"}
  ],
  "indicators": ["T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2"],
  "indicator_labels": {
    "T1": "Разгрузка дорог",
    "T2": "Доступность общественного транспорта",
    "E1": "Озеленение",
    "E2": "Качество воздуха",
    "S1": "Школы и детсады",
    "S2": "Поликлиники и первичная медпомощь",
    "B1": "Безопасность улиц",
    "B2": "Безопасность дорожного движения",
    "C1": "Надёжность ЖКХ",
    "C2": "Скорость решения обращений жителей"
  },
  "weights": {"T1": 0.1, "T2": 0.1, "E1": 0.09, "E2": 0.11, "S1": 0.11, "S2": 0.11, "B1": 0.09, "B2": 0.09, "C1": 0.1, "C2": 0.1},
  "districts": [
    {
      "id": "esil",
      "name": "Есиль",
      "population_share": 0.27,
      "indicators": {"T1": 45, "T2": 62, "E1": 68, "E2": 72, "S1": 48, "S2": 55, "B1": 78, "B2": 60, "C1": 75, "C2": 70}
    },
    {
      "id": "almaty",
      "name": "Алматы",
      "population_share": 0.24,
      "indicators": {"T1": 40, "T2": 75, "E1": 50, "E2": 55, "S1": 60, "S2": 65, "B1": 62, "B2": 52, "C1": 50, "C2": 60}
    },
    {
      "id": "saryarka",
      "name": "Сарыарка",
      "population_share": 0.2,
      "indicators": {"T1": 50, "T2": 70, "E1": 42, "E2": 40, "S1": 62, "S2": 68, "B1": 58, "B2": 55, "C1": 45, "C2": 55}
    },
    {
      "id": "baikonur",
      "name": "Байконур",
      "population_share": 0.13,
      "indicators": {"T1": 52, "T2": 68, "E1": 55, "E2": 50, "S1": 58, "S2": 60, "B1": 52, "B2": 58, "C1": 55, "C2": 58}
    },
    {
      "id": "nura",
      "name": "Нура",
      "population_share": 0.16,
      "indicators": {"T1": 55, "T2": 40, "E1": 45, "E2": 65, "S1": 38, "S2": 35, "B1": 55, "B2": 50, "C1": 60, "C2": 50}
    }
  ],
  "measures": [
    {"id": "M1", "name": "Выделенные полосы для автобусов", "category": "transport", "scope": "district", "cost": 18, "lag_quarters": 2, "effects": {"T1": 6, "T2": 9}},
    {
      "id": "M2",
      "name": "Умные светофоры (адаптивное управление)",
      "category": "transport",
      "scope": "city",
      "cost": 22,
      "lag_quarters": 2,
      "effects": {"T1": 4, "B2": 3}
    },
    {"id": "M3", "name": "Линия ЛРТ / расширение", "category": "transport", "scope": "district", "cost": 30, "lag_quarters": 4, "effects": {"T1": 16, "T2": 20, "E2": 4}},
    {"id": "M4", "name": "Парк / сквер", "category": "environment", "scope": "district", "cost": 15, "lag_quarters": 2, "effects": {"E1": 12, "E2": 3, "B1": 2}},
    {
      "id": "M5",
      "name": "Перевод частного сектора на чистое топливо",
      "category": "environment",
      "scope": "district",
      "cost": 25,
      "lag_quarters": 3,
      "effects": {"E2": 14, "C1": 4}
    },
    {
      "id": "M6",
      "name": "Городская программа озеленения и ветрозащитных полос",
      "category": "environment",
      "scope": "city",
      "cost": 20,
      "lag_quarters": 4,
      "effects": {"E1": 5, "E2": 3}
    },
    {"id": "M7", "name": "Школа + детсад (модульное строительство)", "category": "social", "scope": "district", "cost": 24, "lag_quarters": 3, "effects": {"S1": 16}},
    {"id": "M8", "name": "Центр семейного здоровья / поликлиника", "category": "social", "scope": "district", "cost": 20, "lag_quarters": 3, "effects": {"S2": 14}},
    {"id": "M9", "name": "Дворовые спорт-хабы", "category": "social", "scope": "district", "cost": 10, "lag_quarters": 1, "effects": {"S1": 3, "S2": 3, "B1": 3}},
    {
      "id": "M10",
      "name": "Освещение и камеры (расширение Safe City)",
      "category": "safety",
      "scope": "district",
      "cost": 12,
      "lag_quarters": 1,
      "effects": {"B1": 12, "B2": 2}
    },
    {
      "id": "M11",
      "name": "Безопасные переходы и школьные зоны",
      "category": "safety",
      "scope": "district",
      "cost": 10,
      "lag_quarters": 1,
      "effects": {"B2": 12, "T1": -2}
    },
    {"id": "M12", "name": "Единая цифровая платформа обращений", "category": "services", "scope": "city", "cost": 14, "lag_quarters": 1, "effects": {"C2": 5}},
    {"id": "M13", "name": "Модернизация тепло- и водосетей", "category": "services", "scope": "district", "cost": 28, "lag_quarters": 4, "effects": {"C1": 18, "E2": 2}},
    {
      "id": "M14",
      "name": "Аварийные бригады ЖКХ + раннее оповещение",
      "category": "services",
      "scope": "city",
      "cost": 16,
      "lag_quarters": 1,
      "effects": {"C1": 5, "C2": 2}
    }
  ],
  "conflicts": [
    {"measure_ids": ["M1", "M3"], "condition": "any_district"},
    {"measure_ids": ["M4", "M7"], "condition": "same_district"},
    {"measure_ids": ["M5", "M13"], "condition": "same_district"}
  ],
  "synergies": [
    {"measure_ids": ["M1", "M2"], "target_measure_id": "M1", "effects": {"T1": 2}},
    {"measure_ids": ["M10", "M12"], "target_measure_id": "M10", "effects": {"B1": 2}},
    {"measure_ids": ["M5", "M6"], "target_measure_id": "M5", "effects": {"E2": 2}}
  ]
}
```

Схема ConfigResponse: все приведённые поля обязательны, дополнительных полей нет. `contract_version`, `dataset_version`, `rules_version` — строки указанной версии. `budget`, `horizon_quarters`, `required_selection_count`, `max_per_category` — целые. `required_categories` — все пять категорий; `categories` — их объекты `{id, name}`. `indicators` — десять ID, `indicator_labels` — отображение всех десяти ID в строки, `weights` — отображение в числа.

`districts`: ровно пять объектов `{id, name, population_share, indicators}`. `indicators` содержит все десять чисел. `measures`: ровно 14 объектов `{id, name, category, scope, cost, lag_quarters, effects}`. Scope — `district` или `city`; `effects` — непустой словарь известных показателей и полных знаковых эффектов до лага. Лаг — целое 0–8.

`conflicts`: объекты `{measure_ids: [ID, ID], condition}`; condition — `any_district` или `same_district`. `synergies`: объекты `{measure_ids: [ID, ID], target_measure_id, effects}`; фиксированные эффекты в районе target_measure_id. Две пары синергий остаются в каталоге как исходные данные, но недоступны при max_per_category=1.

Суммы весов и долей равны 1. Сервер проверяет целостность каталога до обслуживания расчётов; при повреждённых данных не возвращает правдоподобные частичные результаты. Клиент использует конфигурацию для формы и предварительной подсказки бюджета, но серверная проверка обязательна.

## 5. POST /simulate

Тело — SimulationRequest. Валидация и вычисление не вызывают AI. Успешный ответ SimulationResponse, HTTP 200. Ниже полный результат для B:

```json
{
  "contract_version": "1.0",
  "dataset_version": "city-v1",
  "rules_version": "five-directions-v1",
  "selections": [
    {"measure_id": "M1", "district_id": "esil"},
    {"measure_id": "M4", "district_id": "saryarka"},
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "esil"},
    {"measure_id": "M12", "district_id": null}
  ],
  "baseline_score": 52.55768,
  "final_score": 55.0703475,
  "score_delta": 2.5126675,
  "total_cost": 83,
  "remaining_budget": 17,
  "score_breakdown": {
    "before": {"city_average": 56.8624, "weakest_district_id": "nura", "weakest_district_score": 49.18, "critical_count": 2},
    "after": {"city_average": 58.364425, "weakest_district_id": "nura", "weakest_district_score": 50.7175, "critical_count": 1}
  },
  "districts": [
    {
      "id": "esil",
      "name": "Есиль",
      "population_share": 0.27,
      "before": {"T1": 45, "T2": 62, "E1": 68, "E2": 72, "S1": 48, "S2": 55, "B1": 78, "B2": 60, "C1": 75, "C2": 70},
      "after": {"T1": 49.5, "T2": 68.75, "E1": 68, "E2": 72, "S1": 48, "S2": 55, "B1": 90.5, "B2": 61.75, "C1": 75, "C2": 74.375},
      "changes": {"T1": 4.5, "T2": 6.75, "E1": 0, "E2": 0, "S1": 0, "S2": 0, "B1": 12.5, "B2": 1.75, "C1": 0, "C2": 4.375},
      "score_before": 62.99,
      "score_after": 65.835
    },
    {
      "id": "almaty",
      "name": "Алматы",
      "population_share": 0.24,
      "before": {"T1": 40, "T2": 75, "E1": 50, "E2": 55, "S1": 60, "S2": 65, "B1": 62, "B2": 52, "C1": 50, "C2": 60},
      "after": {"T1": 40, "T2": 75, "E1": 50, "E2": 55, "S1": 60, "S2": 65, "B1": 62, "B2": 52, "C1": 50, "C2": 64.375},
      "changes": {"T1": 0, "T2": 0, "E1": 0, "E2": 0, "S1": 0, "S2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 4.375},
      "score_before": 57.06,
      "score_after": 57.4975
    },
    {
      "id": "saryarka",
      "name": "Сарыарка",
      "population_share": 0.2,
      "before": {"T1": 50, "T2": 70, "E1": 42, "E2": 40, "S1": 62, "S2": 68, "B1": 58, "B2": 55, "C1": 45, "C2": 55},
      "after": {"T1": 50, "T2": 70, "E1": 51, "E2": 42.25, "S1": 62, "S2": 68, "B1": 59.5, "B2": 55, "C1": 45, "C2": 59.375},
      "changes": {"T1": 0, "T2": 0, "E1": 9, "E2": 2.25, "S1": 0, "S2": 0, "B1": 1.5, "B2": 0, "C1": 0, "C2": 4.375},
      "score_before": 54.65,
      "score_after": 56.28
    },
    {
      "id": "baikonur",
      "name": "Байконур",
      "population_share": 0.13,
      "before": {"T1": 52, "T2": 68, "E1": 55, "E2": 50, "S1": 58, "S2": 60, "B1": 52, "B2": 58, "C1": 55, "C2": 58},
      "after": {"T1": 52, "T2": 68, "E1": 55, "E2": 50, "S1": 58, "S2": 60, "B1": 52, "B2": 58, "C1": 55, "C2": 62.375},
      "changes": {"T1": 0, "T2": 0, "E1": 0, "E2": 0, "S1": 0, "S2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 4.375},
      "score_before": 56.63,
      "score_after": 57.0675
    },
    {
      "id": "nura",
      "name": "Нура",
      "population_share": 0.16,
      "before": {"T1": 55, "T2": 40, "E1": 45, "E2": 65, "S1": 38, "S2": 35, "B1": 55, "B2": 50, "C1": 60, "C2": 50},
      "after": {"T1": 55, "T2": 40, "E1": 45, "E2": 65, "S1": 48, "S2": 35, "B1": 55, "B2": 50, "C1": 60, "C2": 54.375},
      "changes": {"T1": 0, "T2": 0, "E1": 0, "E2": 0, "S1": 10, "S2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 4.375},
      "score_before": 49.18,
      "score_after": 50.7175
    }
  ],
  "critical_before": [{"district_id": "nura", "indicator": "S1", "value": 38}, {"district_id": "nura", "indicator": "S2", "value": 35}],
  "critical_after": [{"district_id": "nura", "indicator": "S2", "value": 35}],
  "applied_effects": [
    {"measure_id": "M1", "scope": "district", "district_id": "esil", "realized_effects": {"T1": 4.5, "T2": 6.75}},
    {"measure_id": "M4", "scope": "district", "district_id": "saryarka", "realized_effects": {"E1": 9, "E2": 2.25, "B1": 1.5}},
    {"measure_id": "M7", "scope": "district", "district_id": "nura", "realized_effects": {"S1": 10}},
    {"measure_id": "M10", "scope": "district", "district_id": "esil", "realized_effects": {"B1": 10.5, "B2": 1.75}},
    {"measure_id": "M12", "scope": "city", "district_id": null, "realized_effects": {"C2": 4.375}}
  ],
  "applied_synergies": [{"measure_ids": ["M10", "M12"], "district_id": "esil", "effects": {"B1": 2}}],
  "explanation": "Расчёт выполнен по учебной модели. Объяснение AI запрашивается отдельно.",
  "explanation_source": "rules"
}
```

### Схема SimulationResponse

Все поля примера обязательны; дополнительных полей нет.

| Поля | Тип и смысл |
| --- | --- |
| `contract_version`, `dataset_version`, `rules_version` | Строки версий |
| `selections` | Нормализованный список Selection; district_id присутствует, для city null; сортировка M1…M14 |
| `baseline_score`, `final_score`, `score_delta` | Numbers; score_delta = final_score − baseline_score |
| `total_cost`, `remaining_budget` | Целые; remaining_budget = 100 − total_cost |
| `score_breakdown` | Объект с `before` и `after`, оба типа ScoreBreakdown |
| `districts` | Пять DistrictResult в фиксированном порядке |
| `critical_before`, `critical_after` | Массивы CriticalIndicator в порядке района, затем показателя; могут быть пустыми |
| `applied_effects` | Пять AppliedEffect в порядке ID мероприятия |
| `applied_synergies` | Массив AppliedSynergy; может быть пустым |
| `explanation` | Детерминированная строка, не AI-разбор |
| `explanation_source` | Константа `rules` |

ScoreBreakdown: `{city_average: number, weakest_district_id: DistrictID, weakest_district_score: number, critical_count: integer}`. Слабейший определяется по минимуму взвешенной оценки района; при ничьей выбирается первый в фиксированном порядке. Score пересчитывается из этих четырёх полей по формуле спецификации.

DistrictResult: `{id, name, population_share, before, after, changes, score_before, score_after}`. Карты before/after/changes содержат ровно десять ID показателей. changes = after − before. score_before/after — районные взвешенные оценки, не городские Score.

CriticalIndicator: `{district_id, indicator, value}`; value строго меньше 40. Пустой массив означает отсутствие критических пар, а не ошибку.

AppliedEffect: `{measure_id, scope, district_id, realized_effects}`. realized_effects — словарь эффектов после коэффициента лага, до синергий и clip. Для city район null и эффект применяется отдельно к каждому району. Это не независимый вклад меры в итоговый Score.

AppliedSynergy: `{measure_ids: [ID, ID], district_id, effects}`. Эффекты фиксированные, без лага и до clip; пара записывается один раз.

Для A контракт тот же. Эталоны: total_cost=83, remaining_budget=17, final_score=53.8250475, score_delta=1.2673675, city_average после=58.485425, weakest_district_score после=49.6175, critical_count после=2. Полный JSON A можно получить заменой district_id у M7 в запросе, но нельзя механически заменить только final_score в ответе B: меняются районные показатели и разбор.

## 6. POST /analyze

Тело — тот же SimulationRequest. Сервер заново валидирует и вычисляет SimulationResponse; браузер не передаёт ему готовый результат. Только после успешной валидации выполняется один AI-запрос с рассчитанными фактами.

AnalysisResponse содержит обязательные поля: `contract_version`, `dataset_version`, `rules_version`, нормализованные `selections`, `baseline_score`, `final_score`, `status`, `analysis`, `unavailable_reason`, `message`. Дополнительных полей нет. Версии и числовые значения совпадают с результатом `/simulate` для того же набора.

status — `ok` или `unavailable`. При ok: analysis — Analysis, unavailable_reason — null, message — пустая строка. При unavailable: analysis — null, reason — одно из значений таблицы ниже, message — безопасное русское сообщение. Внешние технические детали и ключи не выводятся.

Analysis: `{summary, strengths, risks, tradeoff, reflection_question, limitations}`. summary и tradeoff — EvidenceStatement; strengths и risks — массивы 0–2 EvidenceStatement. EvidenceStatement имеет `{text: string, evidence_paths: string[]}`; text непустой, до 600 символов; от одной до четырёх ссылок. reflection_question — непустая строка до 300 символов; limitations — массив 1–2 непустых строк до 300 символов каждая. Общий объём всех текстов analysis — не более 180 слов, считая разделение по пробельным символам.

`evidence_paths` — JSON Pointer относительно корня **SimulationResponse**, заново рассчитанного сервером для этого запроса, без префикса `/simulation`. Пример `/districts/4/after/S1` означает S1 Нуры после мер. Путь должен существовать; ссылки на сам AI-текст не допускаются. Они проверяются сервером; корректная ссылка ещё не гарантирует верность её интерпретации. UI использует тот же результат `/simulate` только при совпадении попытки, selections и версий.

AI не изменяет числа, не придумывает эффекты, не обещает реального городского результата и не объявляет сценарий оптимальным. Если разбор не проходит проверки, возвращается unavailable. Пример ниже — ожидаемый формат и допустимое содержание, а не заранее полученный живой ответ модели.

```json
{
  "contract_version": "1.0",
  "dataset_version": "city-v1",
  "rules_version": "five-directions-v1",
  "selections": [
    {"measure_id": "M1", "district_id": "esil"},
    {"measure_id": "M4", "district_id": "saryarka"},
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "esil"},
    {"measure_id": "M12", "district_id": null}
  ],
  "baseline_score": 52.55768,
  "final_score": 55.0703475,
  "status": "ok",
  "analysis": {
    "summary": {
      "text": "Сценарий улучшает итоговую оценку и устраняет один критический провал в Нуре.",
      "evidence_paths": ["/baseline_score", "/final_score", "/score_breakdown/before/critical_count", "/score_breakdown/after/critical_count"]
    },
    "strengths": [
      {"text": "Школа выводит обеспеченность Нуры выше критического порога.", "evidence_paths": ["/districts/4/before/S1", "/districts/4/after/S1"]},
      {"text": "Освещение и платформа обращений дают дополнительный эффект безопасности в Есиле.", "evidence_paths": ["/applied_synergies/0"]}
    ],
    "risks": [{"text": "Доступность первичной медпомощи в Нуре остаётся критической.", "evidence_paths": ["/critical_after/0"]}],
    "tradeoff": {
      "text": "Школа улучшает обеспеченность образованием, но не закрывает сохраняющийся дефицит медицинской помощи.",
      "evidence_paths": ["/districts/4/changes/S1", "/districts/4/changes/S2", "/critical_after/0"]
    },
    "reflection_question": "Как изменился бы результат, если вместо школы выбрать поликлинику в Нуре?",
    "limitations": ["Выводы относятся к учебной модели на синтетических данных."]
  },
  "unavailable_reason": null,
  "message": ""
}
```

### AI недоступен — HTTP 200 с явным статусом

Недоступность AI не превращает допустимый набор в ошибку расчёта. Сервер не выдумывает успешный разбор. Уже показанный `/simulate` остаётся на экране.

```json
{
  "contract_version": "1.0",
  "dataset_version": "city-v1",
  "rules_version": "five-directions-v1",
  "selections": [
    {"measure_id": "M1", "district_id": "esil"},
    {"measure_id": "M4", "district_id": "saryarka"},
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "esil"},
    {"measure_id": "M12", "district_id": null}
  ],
  "baseline_score": 52.55768,
  "final_score": 55.0703475,
  "status": "unavailable",
  "analysis": null,
  "unavailable_reason": "timeout",
  "message": "AI-разбор не получен вовремя. Рассчитанные показатели остаются доступны."
}
```

| unavailable_reason | Причина |
| --- | --- |
| `disabled` | AI отключён настройкой сервера |
| `not_configured` | Нет ключа или модели |
| `timeout` | Превышен общий лимит ожидания |
| `rate_limited` | Провайдер ограничил запросы |
| `provider_error` | Ошибка доступа или другая ошибка провайдера |
| `invalid_response` | Некорректный JSON, схема, evidence_paths или длина |
| `refused` | Модель явно отказалась отвечать |

Общий timeout AI — целевые 12 секунд, без автоматических повторов. Режим unavailable — деградация, а не выполнение обязательной AI-функции: приёмка требует хотя бы успешных живых разборов A/B. Ошибки валидации для `/analyze` совпадают с `/simulate` и не вызывают провайдера.

## 7. Ошибки запросов

Для обоих POST используется HTTP 422 и единый envelope `detail`: массив ровно с одной первой ошибкой. ErrorItem: обязательные `code` (enum таблицы), `message` (непустая русская строка), `path` (массив строк/целых, путь от корня запроса), `context` (JSON-объект параметров ошибки; может быть пустым).

Не возвращать поле Score в ошибке. Клиент ориентируется на code, а не парсит текст message. Стандартные ошибки FastAPI/Pydantic потребуется привести к этой форме; это план изменения, а не текущее поведение каркаса.

Порядок стадий: формат/тип/лишние поля → количество → неизвестные ID мер → повторы → районы → покрытие категорий → несовместимости → бюджет. Внутри стадии выбирать первое нарушение в порядке входа; пропущенные категории перечислять в порядке конфигурации. При нескольких проблемах не обещать все ошибки сразу. M1+M3 отклонится уже на категории; глобальный запрет всё равно остаётся правилом модели.

| code | Условие | Типичный path |
| --- | --- | --- |
| `INVALID_REQUEST` | Невалидный JSON, отсутствие selections, неверные типы | `[]` или путь поля |
| `UNEXPECTED_FIELD` | Лишнее поле, включая decisions или total_cost | Путь лишнего поля |
| `INVALID_SELECTION_COUNT` | Не пять элементов | `["selections"]` |
| `UNKNOWN_MEASURE` | Нет такого measure_id | `["selections", i, "measure_id"]` |
| `DUPLICATE_MEASURE` | Повтор выбранной меры | Путь второго measure_id |
| `DISTRICT_REQUIRED` | Район отсутствует или null у локальной меры | Путь district_id |
| `UNKNOWN_DISTRICT` | Неизвестный строковый район локальной меры | Путь district_id |
| `DISTRICT_NOT_ALLOWED` | Ненулевой район у городской меры | Путь district_id |
| `CATEGORY_COVERAGE` | Нет ровно одной меры каждой категории | `["selections"]` |
| `INCOMPATIBLE_MEASURES` | Запрещённая пара | `["selections"]` |
| `BUDGET_EXCEEDED` | Стоимость больше 100 | `["selections"]` |

### Превышение бюджета: полный запрос и ответ

```json
{
  "selections": [
    {"measure_id": "M3", "district_id": "nura"},
    {"measure_id": "M5", "district_id": "saryarka"},
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "esil"},
    {"measure_id": "M14", "district_id": null}
  ]
}
```

HTTP 422:

```json
{
  "detail": [
    {
      "code": "BUDGET_EXCEEDED",
      "message": "Стоимость решений 107 превышает бюджет 100 на 7 единиц.",
      "path": ["selections"],
      "context": {"budget": 100, "total_cost": 107, "over_by": 7}
    }
  ]
}
```

### Конфликт участка

В запросе B заменить district_id у M4 с saryarka на nura, остальные решения сохранить. Категории и бюджет допустимы, но M4 и M7 используют один участок в одном районе. HTTP 422:

```json
{
  "detail": [
    {
      "code": "INCOMPATIBLE_MEASURES",
      "message": "M4 и M7 нельзя выбрать в одном районе.",
      "path": ["selections"],
      "context": {"measure_ids": ["M4", "M7"], "district_id": "nura"}
    }
  ]
}
```

### Пример документа не проходит принятое правило категорий

Запрос: M7 nura, M8 nura, M10 nura, M12 null, M5 saryarka. Стоимость допустима, но результат не рассчитывается. HTTP 422:

```json
{
  "detail": [
    {
      "code": "CATEGORY_COVERAGE",
      "message": "Выберите ровно одно мероприятие каждого из пяти направлений.",
      "path": ["selections"],
      "context": {"missing_categories": ["transport"], "category_counts": {"transport": 0, "environment": 1, "social": 2, "safety": 1, "services": 1}}
    }
  ]
}
```

### Внутренняя ошибка

HTTP 500, безопасный ответ без stack trace и секретов:

```json
{"detail": [{"code": "INTERNAL_ERROR", "message": "Не удалось выполнить расчёт. Повторите попытку.", "path": [], "context": {}}]}
```

INTERNAL_ERROR применяется только к 500. Не использовать его вместо ожидаемых ошибок выбора или недоступности AI. Сетевую ошибку до получения HTTP-ответа frontend обрабатывает отдельно, не предполагая наличие JSON.

## 8. UI и независимая разработка

1. Загрузить `/config`, построить форму из каталога; не хранить альтернативные цены во frontend.
2. Проверить заполнение и бюджет для удобства пользователя; финальное решение принимает сервер.
3. При расчёте зафиксировать snapshot selections и локальный номер попытки. Заблокировать повторную отправку той же операции.
4. Вызвать `/simulate`, сразу показать числа. Невалидный набор не отправлять в `/analyze`.
5. Вызвать `/analyze` с тем же snapshot. AI-loading относится только к текстовому разбору.
6. При изменении выбора увеличить номер попытки и пометить прежний результат устаревшим. Ответ с прежним номером игнорировать, включая ситуацию изменения и возврата выбора.
7. Сверить нормализованные selections и версии, прежде чем присоединять AI к расчёту. При несовпадении показать необходимость пересчёта, а не чужой разбор.
8. Показать unavailable отдельно, сохранив числа. AI-текст выводить как текст, не raw HTML.

Frontend может использовать JSON-примеры как mock-ответы до готовности backend. Mock и записи не выдаются за живой AI. Рабочие структуры приложения остаются `app/models.py`, `validator.py`, `simulation.py`, `main.py`, `ai.py`; отдельные сервисы не нужны.

## 9. Проверка контракта

- Полные JSON-примеры разбираются стандартным JSON-парсером.
- У A/B ровно пять разных категорий, стоимость 83 и одна сработавшая синергия M10+M12.
- Для B: `final_score=55.0703475`, `score_delta=2.5126675`, одна критическая пара nura/S2 со значением 35.
- Числа согласованы с весами, population_share, before/after и critical_count; нет расчёта LLM.
- Все evidence_paths из примера `/analyze` разрешаются относительно SimulationResponse B.
- Перестановка selections не меняет результат и его канонический порядок; повторные запросы не изменяют базу.
- Пустой набор не является способом запросить базу: baseline берётся из `/config`.
- Недопустимый пример документа возвращает CATEGORY_COVERAGE, а не 56.54307.
- Существующий backend ещё должен быть приведён к контракту; эти проверки документов не означают, что API-тесты приложения уже проходят.
