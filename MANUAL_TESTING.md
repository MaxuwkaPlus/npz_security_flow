# План ручного тестирования backend

Пошаговое прохождение каждой ручки API в порядке сценария через встроенную
Swagger-страницу **`http://localhost:8000/docs`** — там видно и что отправляешь,
и что пришло в ответ, без ручного парсинга JSON в терминале. У каждого шага
указано: в каком теге `/docs` искать ручку, что вставить в `Request body`/поля
пути, какой ответ ожидать и откуда взять значение для следующего шага.
Ожидания выведены из опубликованной конфигурации сценария — порогов, allowlist
и правил, — а не из подогнанного прогона.

Требования к поведению: [техническое задание](docs/BACKEND_PROJECT_SPEC.md).
Предметный сценарий: [сценарий тренажёра](docs/TRAINER_SCENARIO.md).

---

## 0. Запуск

```bash
cd backend
uv sync
rm -f var/npz_security_flow.db*            # чистая БД
export DATABASE_URL="sqlite+aiosqlite:///./var/npz_security_flow.db"
export SIMULATION_SPEED_FACTOR=10          # 65 минут сценария ≈ 6.5 минут реальных
uv run alembic upgrade head
uv run python -m app.cli seed
uv run uvicorn app.main:app --port 8000
```

**Ожидаемо:** `seed` печатает три строки с идентификаторами установки, сценария и
политики оценки. Повторный `seed` печатает **те же идентификаторы** — публикация
идемпотентна.

Откройте в браузере **`http://localhost:8000/docs`** — дальше весь план ведётся
через эту страницу. Ручки сгруппированы по тегам: **service** (health/ready),
**catalog** (сценарии, установка), **sessions** (сессия, команды, наблюдения,
тревоги, SAGAT, NASA-TLX), **reports** (отчёт).

Для каждой ручки одинаковый порядок действий: разверните строку → **Try it
out** → заполните `Parameters`/`Request body` → **Execute** → результат
смотрите в блоке **Server response → Response body**.

О скорости симуляции: `10` — чтобы успевать читать показания и вводить команды;
`60`–`300` — чтобы быстро увидеть весь цикл. Всё симуляционное время ниже
указано в секундах сценария, а не реальных.

Часть проверок в `/docs` не делается принципиально — это не недостаток
документа, а особенность API:

- **показания приборов** (расходы, температуры, уровни) отдаются только через
  WebSocket (раздел 11) или снимками в БД — в REST-ответах их нет, поэтому в
  разделах 5–8 используется вспомогательный Python-скрипт, читающий БД напрямую;
- **скрытая причина возмущения** нарочно не имеет ни одной ручки — подглядеть
  её можно только прямым запросом к БД (раздел 8), в обход API;
- **WebSocket** Swagger не умеет вызывать — для раздела 11 нужен отдельный
  скрипт.

Это те же самые исключения, что перечислены в архитектурных правилах проекта:
скрытое состояние не должно быть достижимо через публичный API.

---

## Карта переменных

Один раз собранная шпаргалка: из какого шага и какого поля **Response body**
скопировать значение и в какое поле следующей ручки (path-параметр в
`Parameters` или ключ в `Request body`) его вставить. В примерах ниже такие
места помечены `<ТАК>`.

| Плейсхолдер | Копируем из шага | Поле `Response body` | Вставляем на шаге | Куда именно |
|---|---|---|---|---|
| `<SC>` | 1.3 `GET /scenarios` | `[0].id` | 1.4, 1.5→`<INST>`, 2.1 | путь `scenario_version_id`; тело `scenario_version_id` |
| `<INST>` | 1.4 `GET /scenarios/{id}` | `.installation_version_id` | 1.5 | путь `installation_version_id` |
| `<SID>` | 2.1 `POST /sessions` | `.id` | все шаги 2–13 | путь `session_id` |
| `<AID>` | 4.2 `POST .../actions` | `.id` | 4.2 (отмена) | путь `action_id` |
| `<AL>` | 7.1 `GET .../alarms` | `[0].id` | 7.2 | путь `alarm_id` |
| `<CP>` | 9.1 `GET .../sagat/current` | `.id` | 9.2 | путь `checkpoint_id` |
| `<V>` | любой ответ о сессии | `.version_no` | `/pause`, `/resume` и т.д. | тело `expected_version` (опц.) |

Правило простое: **каждый `id` из `Response body` одной ручки становится
параметром следующей**. Ниже — по шагам.

---

## 1. Каталог

### 1.1 `GET /health` (тег **service**)

**Parameters:** нет. **Execute** без изменений.

**Response body:**
```json
{ "status": "ok" }
```

### 1.2 `GET /ready` (тег **service**)

**Response body:**
```json
{ "status": "ready" }
```
Означает, что проверено соединение с БД.

### 1.3 `GET /scenarios` (тег **catalog**)

**Parameters:** нет.

**Response body** (пример — у вас будет другой `id`, он генерируется при
первом `seed` на вашей БД и дальше не меняется; `scenario_code`, `name`,
`duration_ms` — те же, они заданы конфигурацией):

```json
[
  {
    "id": "cff13aba-b665-43fc-8f2f-7a365c47f8a7",
    "scenario_code": "ELOU-AVT-FULL-RUN",
    "version": 1,
    "name": "Сквозной сценарий ЭЛОУ-АВТ",
    "description": "Пуск установки, вывод в устойчивый режим, скрытое снижение расхода одной сырьевой ветви, диагностика, восстановление и downstream-проверки.",
    "duration_ms": 3900000,
    "installation_version_id": "e3b826ef-28fe-4580-9863-3c3e630d61a0"
  }
]
```

**Забираем:** `[0].id` → `<SC>`, используется на шаге 1.4 (путь) и 2.1 (тело).
Заодно видно `[0].installation_version_id` — тот же, что вы получите отдельно
на шаге 1.4, можно скопировать сразу как `<INST>` и пропустить 1.4.

### 1.4 `GET /scenarios/{scenario_version_id}` (тег **catalog**)

**Parameters:** поле `scenario_version_id` → вставьте `<SC>` из 1.3.

**Response body** (пример, сокращено):
```json
{
  "id": "cff13aba-b665-43fc-8f2f-7a365c47f8a7",
  "scenario_code": "ELOU-AVT-FULL-RUN",
  "version": 1,
  "duration_ms": 3900000,
  "installation_version_id": "e3b826ef-28fe-4580-9863-3c3e630d61a0",
  "levels": [
    { "level_no": 1, "sensor_delay_ms": 0, "nuisance_alarm_rate": 0.4, "reaction_deadline_ms": 120000, "development_speed_factor": 0.8, "hints_enabled": true },
    { "level_no": 2, "sensor_delay_ms": 2500, "nuisance_alarm_rate": 2.0, "reaction_deadline_ms": 90000, "development_speed_factor": 1.0, "hints_enabled": true },
    { "level_no": 3, "sensor_delay_ms": 6000, "nuisance_alarm_rate": 4.5, "reaction_deadline_ms": 60000, "development_speed_factor": 1.6, "hints_enabled": false }
  ],
  "stages": [
    { "code": "precheck", "order_no": 1, "timeout_ms": 240000, "required_checks": ["feed_system_ready", "heat_exchangers_ready", "elou_ready", "atmospheric_ready"] }
  ]
}
```

**Ожидаемо:** три уровня `1/2/3`, двадцать этапов от `precheck` до
`final_stabilization` (в примере показан только первый).

**Проверка утечки:** нигде в ответе **нет** слов `disturbance`, `hidden`,
`pump_capacity_loss`, `valve_stiction`, `target_selector`.

**Забираем:** `.installation_version_id` → `<INST>`, используется на шаге 1.5
(путь).

### 1.5 `GET /installations/{installation_version_id}/topology` (тег **catalog**)

**Parameters:** поле `installation_version_id` → вставьте `<INST>` из 1.4.

**Response body** (пример, сокращено):
```json
{
  "installation_version_id": "e3b826ef-28fe-4580-9863-3c3e630d61a0",
  "installation_code": "ELOU-AVT",
  "version": 1,
  "name": "ЭЛОУ-АВТ",
  "equipment": [
    {
      "code": "FRC-405",
      "equipment_type": "controller",
      "display_name": "Регулятор расхода ветви 2",
      "parent_code": "FEED-SYSTEM",
      "tags": [
        { "code": "branch_2_flow_tph", "unit": "т/ч", "value_type": "float", "normal_min": 90.0, "normal_max": 105.0, "warning_min": 88.0, "warning_max": null, "critical_min": 88.0, "critical_max": null }
      ]
    }
  ],
  "edges": [
    { "from_code": "FEED-SYSTEM", "to_code": "T-1_T-11", "stream_code": "raw_feed", "stream_type": "process", "branch_no": 2 }
  ]
}
```

**Ожидаемо:** около 52 аппаратов и 50 связей (в примере — по одному, для
формата). Среди кодов есть `FRC-404/405/406`, `T-1_T-11`, `ELOU`, `V-15`,
`K-1`, `FURNACES`, `K-2`, `PRODUCTS`. Новых переменных шаг не даёт.

### 1.6 Несуществующий путь (негативная проверка, вне `/docs`)

Откройте напрямую в браузере: `http://localhost:8000/api/v1/nope`.

**Ожидаемо:** `404`, тело `{"error":{"code":"HTTP_ERROR",...,"request_id":"..."}}`.

---

## 2. Жизненный цикл сессии

### 2.1 `POST /sessions` (тег **sessions**)

**Request body** — `scenario_version_id` берём из `<SC>` (1.3), остальное
придумываем сами: `operator_id` — любая строка (используем `op-1`, она
понадобится в 12.2), `level_no` — 1..3, `random_seed` — фиксируем, чтобы
прохождение было воспроизводимо (понадобится в разделе 13):

```json
{
  "request_id": "c1",
  "operator_id": "op-1",
  "scenario_version_id": "<SC>",
  "level_no": 1,
  "random_seed": 7
}
```

**Response body:**
```json
{
  "id": "6f1a...-session",
  "operator_id": "op-1",
  "instructor_id": null,
  "scenario_version_id": "<SC>",
  "level_no": 1,
  "status": "ready",
  "sim_time_ms": 0,
  "sequence_no": 2,
  "current_stage_code": "precheck",
  "version_no": 1,
  "final_outcome": null
}
```

**Ожидаемо:** `201`, `status: "ready"` — конфигурация фиксируется прямо при
создании. В ответе **нет** полей `random_seed`, `hidden`, `target_branch`.

**Забираем:** `.id` → `<SID>`, используется в путях всех шагов 2.2–13.
`.version_no` можно запомнить как `<V>` для проверки в 2.6.

### 2.2 Валидация при создании (без новых переменных)

Повторяйте **Try it out** на той же ручке `POST /sessions`, меняя тело:

| Request body | Ожидаемо |
|---|---|
| тот же `request_id: "c1"`, что и в 2.1 | тот же `id` сессии, что и в 2.1 — вторая сессия не создаётся |
| `level_no: 0` или `4` | `422`, код `VALIDATION_ERROR` |
| `scenario_version_id: "не-uuid"` | `404`, код `SCENARIO_NOT_FOUND` |

### 2.3 `POST /sessions/{session_id}/pause` до старта (негативная проверка)

**Parameters:** `session_id` → `<SID>` из 2.1. **Request body:**
```json
{ "request_id": "p0" }
```

**Ожидаемо:** `409`, код `SESSION_TRANSITION_NOT_ALLOWED`, `details.status: "ready"`.

### 2.4 `POST /sessions/{session_id}/start`

**Parameters:** `session_id` → `<SID>`. **Request body:**
```json
{ "request_id": "s1" }
```

**Ожидаемо:** `status: "running"`. С этого момента идёт симуляционное время —
фоновый tick-раннер запущен.

### 2.5 Пауза останавливает время

Три вызова подряд, все с `session_id = <SID>`:

1. `POST /sessions/{session_id}/pause`, тело `{"request_id":"p1"}`.
2. Подождите 10 секунд реального времени.
3. `GET /sessions/{session_id}/state` — сравните `sim_time_ms` с тем, что было
   в ответе шага 1: **должно быть то же число**.
4. `POST /sessions/{session_id}/resume`, тело `{"request_id":"p2"}`.

**Ожидаемо:** между `pause` и `resume` `sim_time_ms` **стоит на месте**.
Повторный `pause` с тем же `request_id: "p1"` возвращает прежний ответ и не
создаёт второй переход. `GET /sessions/{session_id}` (без `/state`) отдаёт то
же самое — это один и тот же хендлер.

### 2.6 Проверка версии

**Parameters:** `session_id` → `<SID>`. Сначала `GET /sessions/{session_id}/state`,
заберите `.version_no` — допустим, получили `4`. Затем `POST
/sessions/{session_id}/pause` с телом, где `expected_version` заведомо
устаревший:

```json
{ "request_id": "x1", "expected_version": 1 }
```

**Ожидаемо:** `409`, код `SESSION_VERSION_MISMATCH`, в `details` видны
`expected_version` и `actual_version`.

---

## 3. Осмотр установки — этап `precheck`

**Parameters везде:** `session_id` → `<SID>` из 2.1. Этап ждёт четыре явные
проверки, без них закроется таймаутом на 240-й секунде симуляции.

### 3.1 `POST /sessions/{session_id}/observations` ×4 (тег **sessions**)

Отправьте по очереди четыре тела (каждый раз **Execute** заново):
```json
{ "request_id": "o-FEED-SYSTEM", "observation_type": "inspect_equipment", "target_code": "FEED-SYSTEM" }
```
```json
{ "request_id": "o-T-1_T-11", "observation_type": "inspect_equipment", "target_code": "T-1_T-11" }
```
```json
{ "request_id": "o-ELOU", "observation_type": "inspect_equipment", "target_code": "ELOU" }
```
```json
{ "request_id": "o-K-2", "observation_type": "inspect_equipment", "target_code": "K-2" }
```

После — `GET /sessions/{session_id}/state`.

| Вход | Ожидаемо |
|---|---|
| четыре наблюдения выше | `201` на каждое; `current_stage_code` в финальном `GET /state` меняется на `feed_preparation` **до** 240 с симуляции |
| `observation_type: "peek"` | `422`, `UNKNOWN_OBSERVATION_TYPE` |
| `target_code: "N-1"` при `observation_type: "verify_result"` | `422`, `OBSERVATION_TARGET_NOT_ALLOWED` |
| повтор с тем же `request_id` | прежний ответ, дубля нет |

Допустимые адреса `verify_result` (пригодятся в разделе 8): `FEED-SYSTEM`,
`T-1_T-11`, `ELOU`, `V-15`, `K-1`, `FURNACES`, `K-2`, `PRODUCTS`. Новых
переменных шаг не даёт.

---

## 4. Валидация команд

**Parameters везде:** `session_id` → `<SID>` из 2.1.

### 4.1 `POST /sessions/{session_id}/actions` — некорректные команды

Отправьте по очереди (каждый раз новый `request_id`):

| Request body | Ожидаемо |
|---|---|
| `{"request_id":"bad1","action_type":"open_secret_bypass","target_code":"N-1"}` | `202`, `status: "rejected"`, `rejection_reason: "unknown_action_type"` |
| `{"request_id":"bad2","action_type":"set_control_valve","target_code":"K-2"}` | `202`, `rejected`, `target_not_allowed` |
| `{"request_id":"bad3","action_type":"set_control_valve","target_code":"FRC-404","value":{"opening_pct":140}}` | `202`, `rejected`, `value_out_of_range` |
| `{"request_id":"bad4","action_type":"set_control_valve","target_code":"FRC-404"}` (без `value`) | `202`, `rejected`, `missing_value` |
| любая команда сразу после `pause` (2.5, шаг 1) | `409`, `SESSION_NOT_RUNNING` — не забудьте потом снова `resume` |

Отклонённая команда **записывается в журнал** — она войдёт в отчёт (раздел
12), — но на установку не влияет. Забирать из ответов здесь нечего.

### 4.2 Отмена команды

`POST /sessions/{session_id}/actions`, тело:
```json
{ "request_id": "cancel-me", "action_type": "set_control_valve", "target_code": "FRC-404", "value": {"opening_pct": 50} }
```

**Забираем:** `.id` из `Response body` → `<AID>`.

`POST /sessions/{session_id}/actions/{action_id}/cancel` — `Parameters`:
`session_id` = `<SID>`, `action_id` = `<AID>`. `Request body`: `{}`.

| Вход | Ожидаемо |
|---|---|
| отмена принятой команды (`<AID>`) | `status: "cancelled"`, клапан **не** уходит на 50 % |
| повторная отмена того же `<AID>` | прежний ответ |
| отмена уже применённой командой (подождать шаг симуляции перед отменой) | `409`, `ACTION_ALREADY_RESOLVED` |

---

## 5. Пуск установки и причинно-следственная цепочка

**Parameters везде:** `session_id` → `<SID>` из 2.1. Подавайте команды **по
одной** через `POST /sessions/{session_id}/actions` и смотрите состояние между
ними — это основная проверка того, что модель причинна, а не рисует числа.
Новых переменных раздел не производит.

Показания приборов через `/docs` не видны (REST их не отдаёт), поэтому между
командами смотрите последний снимок напрямую в БД:

```bash
uv run python -c "
import asyncio,json
from sqlalchemy import select
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ProcessSnapshot
from app.settings import Settings
async def m():
    db=Database(Settings())
    async with db.session_factory() as s:
        sn=await s.scalar(select(ProcessSnapshot).order_by(ProcessSnapshot.sim_time_ms.desc()).limit(1))
        print(sn.sim_time_ms//1000,'с, этап',sn.stage_code)
        print(json.dumps(sn.visible_values_json,ensure_ascii=False,indent=2))
        print(json.dumps(sn.derived_values_json,ensure_ascii=False,indent=2))
    await db.dispose()
asyncio.run(m())"
```

### 5.1 Сырьевой насос

**Request body:**
```json
{ "request_id": "a1", "action_type": "start_feed_pump", "target_code": "N-1" }
```

| Момент | Ожидаемо |
|---|---|
| сразу после команды (`Response body`) | `status: "accepted"`, а не «applied» — применит ближайший шаг симуляции |
| +5 с (снимок из БД) | `feed_pump_state: RUNNING`, давление на выкиде растёт к 6.0 бар, расходы ветвей **малы** — единицы т/ч |
| +60 с | каждая ветвь примерно 50–90 т/ч: расход нарастает постепенно, а не скачком |
| +180 с | около 95–100 т/ч на ветвь, `total_feed_flow_tph` ≈ 300 |

### 5.2 Температура после Т-1…Т-11 — только наблюдение (снимок из БД)

**Ожидаемо:** `branch_N_t11_outlet_temp_c` от 25 °C растёт примерно до **130 °C**
и там остаётся. Предел регламента — 140 °C, при штатном расходе он не
превышается. Прогрев занимает около 15 минут симуляции.

### 5.3 Промывочная вода на ЭЛОУ

**Request body:**
```json
{ "request_id": "a2", "action_type": "set_wash_water", "target_code": "ELOU", "value": {"ratio": 0.075} }
```

| Вход | Ожидаемо |
|---|---|
| `ratio: 0.075` | `elou_wash_water_ratio: 0.075` — регламент 5–10 %; этап `elou_feed_and_water` закрывается успехом |
| `ratio: 0.5` | значение обрезается до `0.20` — максимум конфигурации |

**Уровни ЭЛОУ:** `elou_stage1_min_level_mm` растёт от 0 примерно до **3820 мм**.
Пока аппарат наполняется, уровень законно ниже 3500 мм — **тревоги блокировки
быть не должно**. Защита взводится только после вывода ступени в работу, то
есть от 3700 мм.

### 5.4 Насосы Н-20 и колонна К-1

**Request body:**
```json
{ "request_id": "a3", "action_type": "start_transfer_pump", "target_code": "N-20" }
```

**Ожидаемо:** до этой команды `k1_feed_flow_ratio` равен 0 и `k1_bottom_temp_c`
равен 0, сколько бы ни шёл поток — без откачки из Е-15 сырьё до колонны не
доходит. После команды К-1 наполняется: давление около 1.6 бар, низ около
268 °C, уровень около 50 %.

### 5.5 Печи

**Request body:**
```json
{ "request_id": "a4", "action_type": "set_furnace_heat_load", "target_code": "FURNACES", "value": {"heat_load_pct": 100} }
```

| Момент | Ожидаемо |
|---|---|
| до розжига | `furnace_heat_load_pct: 0`, `furnace_heat_to_feed_ratio: 0`, температура на выходе равна низу К-1 |
| после розжига | выход около 340 °C, `furnace_heat_to_feed_ratio` ≈ **1.0**, низ К-2 около 338 °C, `k2_stability_index` стремится к 1.0 |

Этап `furnaces` требует соотношение в диапазоне 0.95–1.05 — при погашенных
печах он **не** закроется успехом.

---

## 6. Выход на режим и запуск возмущения

Дождитесь (снимок из БД, как в разделе 5, или `GET /sessions/{session_id}/state`
на вкладке **sessions**), пока `current_stage_code` дойдёт до `stable_mode`, а
затем сменится на `disturbance_monitoring`. Новых вызовов нет, только наблюдение.

**Ожидаемо:** к этому моменту `min_branch_flow_ratio ≥ 0.95`,
`flow_imbalance_ratio ≤ 0.05`, `t11_max_temp_c ≤ 140`, `k1_feed_flow_ratio ≥ 0.95`,
`k2_stability_index ≥ 0.85` держатся непрерывно 20 секунд.

**Ключевое поведение:** возмущение вводится **только после подтверждения
устойчивого режима** плюс задержка 0–120 секунд, которую выбирает seed. Если не
подать воду (5.3) или не запустить Н-20 (5.4), режим не подтвердится и
**возмущения не будет вовсе**. Это правильное поведение, а не поломка.

---

## 7. Развитие возмущения и тревоги

**Parameters везде:** `session_id` → `<SID>` из 2.1. Ничего не делайте 5–8
минут симуляции.

### 7.1 `GET /sessions/{session_id}/alarms` (тег **sessions**)

**Response body** (пример):
```json
[
  {
    "id": "a7c9...-alarm",
    "alarm_code": "flow_deviation_branch",
    "level": "L1",
    "equipment_code": "FRC-405",
    "message": "Расход ветви 2 ниже нормы",
    "state": "active",
    "started_sim_time_ms": 1523000,
    "acknowledged_sim_time_ms": null,
    "cleared_sim_time_ms": null,
    "is_nuisance": false
  }
]
```

| Условие | Ожидаемая тревога |
|---|---|
| расход одной ветви ползёт вниз | остальные две чуть подрастают, примерно +1.5 % |
| `min_branch_flow_ratio` < 0.92 непрерывно 5 с | **L1** `flow_deviation_branch` |
| `flow_imbalance_ratio` > 0.12 | **L2** `feed_flow_imbalance` |
| `t11_max_temp_c` > 140 | **L3** `t11_temperature_deviation` |
| `elou_load_imbalance_ratio` > 0.18 | **L4** `elou_load_imbalance` |
| уровень ЭЛОУ < 3500 мм | **L5** `elou_low_level_interlock`, `elou_hv_trip_count ≥ 1` |
| `k1_feed_flow_ratio` < 0.91 | **L5** `k1_feed_deviation` |
| `furnace_heat_to_feed_ratio` > 1.25 | **L5** `unsafe_furnace_heat_to_feed` |
| `k2_stability_index` < 0.55 | **L5** `k2_critical_instability` |

Тревоги приходят **в этом порядке с нарастающим запаздыванием** — это и есть
распространение возмущения по цепочке. Фоном появляются
`nuisance_auxiliary_N` уровня **L0** на `AUX-SYSTEM` — методический шум. На
уровне 1 редко, на уровне 3 часто. Гаснут сами через 120 секунд.

**Забираем:** `[0].id` → `<AL>`, используется на шаге 7.2 (путь).

### 7.2 `POST /sessions/{session_id}/alarms/{alarm_id}/acknowledge`

**Parameters:** `session_id` = `<SID>`, `alarm_id` = `<AL>` из 7.1. **Request
body:**
```json
{ "request_id": "ack1" }
```

**Ожидаемо:** `state: "active_acknowledged"`. Повтор с тем же `request_id`
возвращает тот же момент подтверждения и не создаёт второго события.

---

## 8. Диагностика — главная проверка бизнес-логики

**Parameters везде:** `session_id` → `<SID>` из 2.1. **Сначала определите
причину сами по приборам (снимок из БД, раздел 5), не подглядывая.** Причин
ровно две, и они различимы:

| Признак | Вывод |
|---|---|
| `feed_pump_discharge_pressure_bar` упало ниже 5.2, а `branch_N_valve_actual_pct` **равно** `branch_N_valve_command_pct` | `pump_capacity_loss` |
| давление на выкиде **не упало**, даже выросло выше 6.0, а `valve_actual_pct` заметно **меньше** `valve_command_pct` | `valve_stiction` |

Проблемная ветвь — с минимальным расходом; её номер есть в
`lowest_flow_branch_code`: 1 → `FRC-404`, 2 → `FRC-405`, 3 → `FRC-406`.

Подсмотреть разгадку можно в роли инструктора — **после** собственного вывода
(это прямой запрос к БД, не через API — у скрытой причины намеренно нет ручки):

```bash
uv run python -c "
import asyncio,json
from sqlalchemy import select
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import TrainingSession
from app.settings import Settings
async def m():
    db=Database(Settings())
    async with db.session_factory() as s:
        t=await s.scalar(select(TrainingSession))
        print(json.dumps(t.hidden_runtime_config_json['disturbance'],ensure_ascii=False,indent=2))
    await db.dispose()
asyncio.run(m())"
```

### 8.1 Ветка А — правильный путь

#### 8.1.1 `POST /sessions/{session_id}/observations` ×4 — сбор улик

Отправьте по очереди:
```json
{ "request_id": "d1", "observation_type": "declare_deviation", "target_code": "FEED-SYSTEM" }
```
```json
{ "request_id": "d2", "observation_type": "compare_flows", "target_code": "FEED-SYSTEM" }
```
```json
{ "request_id": "d3", "observation_type": "inspect_pressure", "target_code": "FEED-SYSTEM" }
```
```json
{ "request_id": "d4", "observation_type": "inspect_equipment", "target_code": "N-1" }
```

**Ожидаемо:** `201` на каждое; момент первого `declare_deviation` фиксируется
как время обнаружения — используется в отчёте (12.1, `timings.detection_time_ms`).

#### 8.1.2 `POST /sessions/{session_id}/diagnoses`

**Request body** — значение `suspected_cause_code` из вашего вывода:
```json
{
  "request_id": "dg1",
  "affected_area_code": "FEED-SYSTEM",
  "deviation_code": "branch_flow_loss",
  "suspected_cause_code": "pump_capacity_loss"
}
```

**Response body:**
```json
{
  "id": "d41f...-diagnosis",
  "request_id": "dg1",
  "session_id": "<SID>",
  "sequence_no": 47,
  "sim_time_ms": 1612000,
  "affected_area_code": "FEED-SYSTEM",
  "deviation_code": "branch_flow_loss",
  "suspected_cause_code": "pump_capacity_loss"
}
```

**Ожидаемо:** `201`, и в ответе **нет** поля `is_correct` — правильность
диагноза оператору не сообщается напрямую (только в отчёте, 12.1). Значение
`suspected_cause_code`, которое вы указали, определяет, какое корректирующее
действие будет эффективным в 8.1.3.

#### 8.1.3 `POST /sessions/{session_id}/actions` — корректирующее действие

**Request body** зависит от `suspected_cause_code` из 8.1.2:

- диагноз `pump_capacity_loss` → `{"request_id":"fix1","action_type":"switch_to_standby_pump","target_code":"N-1A"}`
- диагноз `valve_stiction` → `{"request_id":"fix1","action_type":"restore_flow_control","target_code":"FRC-40X"}`,
  где `X` = 3 + номер проблемной ветви (из `lowest_flow_branch_code`)

| Проверка (снимок из БД / повтор 7.1) | Ожидаемо |
|---|---|
| через 10 с после действия | расход **почти не изменился** — восстановление занимает 180 с |
| через 200–300 с | `min_branch_flow_ratio` вернулся к значению ≥ 0.95 |
| тревоги (7.1 повторно) | L1, L2, L3 гаснут **сами** по своим порогам снятия: 0.95, 0.08 и 138 °C |
| класс действия (виден в отчёте, 12.1 `actions`) | сразу после применения пуст; через 240 с окна становится `correct` |
| правильный тип действия, но по чужому адресу | причина не устраняется, класс `ineffective` |
| корректирующее действие **до** диагноза (8.1.2 пропущен) | класс `out_of_sequence` |

#### 8.1.4 `POST /sessions/{session_id}/observations` — downstream-проверки

Отправьте по очереди семь тел, `target_code` по списку из 3.1:
```json
{ "request_id": "v-FEED-SYSTEM", "observation_type": "verify_result", "target_code": "FEED-SYSTEM" }
```
...и так же для `T-1_T-11`, `ELOU`, `V-15`, `K-1`, `FURNACES`, `K-2`, `PRODUCTS`.

**Ожидаемо:** `201` на каждое; все семь входят в `downstream_checks` отчёта
(12.1) как закрытые — от этого зависит, будет ли `outcome: "stabilized"`.

### 8.2 Ветка Б — опасная компенсация

Запускать на **отдельной сессии** — повторите 2.1–2.4 с новым `request_id`,
получите новый `<SID>`. Вместо восстановления расхода добавьте тепла:

**Request body** (`POST /sessions/{session_id}/actions`):
```json
{ "request_id": "bad", "action_type": "set_furnace_heat_load", "target_code": "FURNACES", "value": {"heat_load_pct": 125} }
```

| Проверка | Ожидаемо |
|---|---|
| класс действия (виден в отчёте 12.1 `actions`) | `dangerous` **сразу**, без ожидания окна наблюдения |
| `furnace_heat_to_feed_ratio` (снимок из БД) | превышает 1.25 → тревога L5 `unsafe_furnace_heat_to_feed` |
| `furnace_outlet_temp_c` | выше 360 °C, низ К-2 уходит выше 350 °C |
| `k2_stability_index` | падает **сильнее**, чем при бездействии — компенсация ухудшает процесс |
| отчёт (12.1) | вывод «Компенсирует симптом тепловой нагрузкой вместо восстановления расхода», снижение `safety` |

Контрольная проверка: снижение нагрузки вслед за расходом, например
`heat_load_pct: 88`, **не** считается опасным и возвращает соотношение в норму.

---

## 9. SAGAT

**Parameters везде:** `session_id` → `<SID>` из 2.1.

### 9.1 `GET /sessions/{session_id}/sagat/current` (тег **sessions**)

**Response body** (пример):
```json
{
  "id": "9e21...-checkpoint",
  "checkpoint_code": "after_stable_mode",
  "status": "open",
  "triggered_sim_time_ms": 1440000,
  "answers_deadline_sim_time_ms": 1560000,
  "questions": [
    { "code": "lowest_flow_branch", "kind": "what_changed", "prompt": "Какая ветвь сейчас даёт наименьший расход?", "options": ["1", "2", "3"] },
    { "code": "t11_over_limit", "kind": "what_it_means", "prompt": "Превышена ли температура после Т-1…Т-11?", "options": ["yes", "no"] },
    { "code": "k1_feed_trend", "kind": "what_happens_next", "prompt": "Как изменится подача в К-1, если не вмешаться?", "options": ["rising", "falling", "steady"] }
  ]
}
```

**Ожидаемо:** появляется после успешного завершения `stable_mode`, три вопроса
трёх видов. В ответе **нет** эталонных ответов, метрик и порогов — только
формулировки и варианты. До этого этапа возвращается `null`.

**Забираем:** `.id` → `<CP>`, используется на шаге 9.2 (путь).

### 9.2 `POST /sessions/{session_id}/sagat/{checkpoint_id}/answers`

**Parameters:** `session_id` = `<SID>`, `checkpoint_id` = `<CP>` из 9.1.
Значения ответов сверяйте со снимком показаний (раздел 5) на момент
`triggered_sim_time_ms` из ответа 9.1.

**Request body:**
```json
{
  "request_id": "sg1",
  "answers": { "lowest_flow_branch": "2", "t11_over_limit": "no", "k1_feed_trend": "steady" }
}
```

| Ответ | Ожидаемая оценка |
|---|---|
| совпал с фактическим состоянием | 1.0 |
| «steady» вместо реального роста или падения | 0.5 — частичное понимание |
| противоположный тренд или неверная ветвь | 0.0 |
| вопрос не отвечен | 0.0 |

Повторный `GET /sagat/current` (9.1) после ответа возвращает `null`. Вторая
контрольная точка `after_correction` появляется после успешного завершения
этапа `recovery` — повторите 9.1→9.2 ещё раз с новым `<CP>`.

---

## 10. NASA-TLX

**Parameters:** `session_id` → `<SID>` из 2.1.

### 10.1 `POST /sessions/{session_id}/nasa-tlx` (тег **sessions**)

**Request body:**
```json
{
  "mental_demand": 7,
  "physical_demand": 2,
  "temporal_demand": 6,
  "performance": 3,
  "effort": 5,
  "frustration": 4
}
```

**Response body:**
```json
{
  "session_id": "<SID>",
  "raw_tlx_score": 5.17,
  "values": { "mental_demand": 7, "physical_demand": 2, "temporal_demand": 6, "performance": 3, "effort": 5, "frustration": 4 }
}
```

**Ожидаемо:** `201`, `raw_tlx_score` равен **5.17**. Арифметика проверяема:
шкала успешности инвертируется, 3 → 7; сумма 7+2+6+7+5+4 = 31, среднее
31/6 ≈ 5.17.

| Вход | Ожидаемо |
|---|---|
| повторная отправка на тот же `<SID>` | `409`, `NASA_TLX_ALREADY_SUBMITTED` |
| `"effort": 42` | `422`, `VALIDATION_ERROR` |
| влияние на баллы (см. 12.1) | `resultiveness` в отчёте **не меняется** — показатель хранится отдельно |

---

## 11. WebSocket

Swagger `/docs` не умеет вызывать WebSocket-ручки — для этого шага нужен
отдельный скрипт. **Вход:** `<SID>` из 2.1.

```bash
uv run python -c "
import asyncio, json, websockets
async def m():
    async with websockets.connect('ws://localhost:8000/ws/v1/sessions/<SID>?last_sequence_no=0') as ws:
        for _ in range(15):
            m=json.loads(await ws.recv())
            print(m['sequence_no'], m['type'], m['sim_time_ms'])
asyncio.run(m())"
```

| Проверка | Ожидаемо |
|---|---|
| формат конверта | у каждого сообщения есть `schema_version`, `type`, `session_id`, `sequence_no`, `sim_time_ms`, `payload` |
| нумерация | `sequence_no` идут подряд без пропусков, начиная с 1 |
| догон (`?last_sequence_no=5`) | подключение начинается с шестого сообщения, ничего не теряется |
| снимки | `process_snapshot` приходит ровно раз в 5 секунд симуляции |
| утечка | в `payload` снимка **нет** `severity`, `internal_state` и других скрытых полей |
| события | команда оператора (раздел 4/5) даёт `action_status_changed`, тревога (7.1) — `alarm_raised` |

---

## 12. Отчёт и сравнение уровней

**Parameters:** `session_id` → `<SID>` из 2.1.

### 12.1 `GET /sessions/{session_id}/report` (тег **reports**)

**Response body** (пример, сокращено — реальный документ длиннее):
```json
{
  "report_version": 1,
  "session": { "id": "<SID>", "operator_id": "op-1", "instructor_id": null, "status": "completed", "sim_time_ms": 2400000 },
  "outcome": "stabilized",
  "timings": { "total_sim_time_ms": 2400000, "detection_time_ms": 42000, "reaction_time_ms": 55000, "recovery_time_ms": 182000 },
  "scores": { "safety": 92.0, "action_correctness": 88.5, "process_stability": 90.0, "reaction_speed": 76.0, "resultiveness": 87.0, "situation_awareness": 0.83, "raw_nasa_tlx": 5.17 },
  "score_events": [ { "dimension": "safety", "delta": -3.0, "rule_code": "unacknowledged_alarm", "reason": "Тревога L1 не подтверждена за отведённое время" } ],
  "actions": { "total": 6, "by_classification": { "correct": 1, "rejected": 4 }, "rejected": [], "unverified": [] },
  "alarms": { "total": 3, "timeline": [], "unacknowledged": [] },
  "downstream_checks": { "completed": ["verify_t11", "verify_elou"], "missing": ["verify_products"] },
  "stages": [ { "stage_code": "precheck", "entered_sim_time_ms": 0, "exited_sim_time_ms": 118000, "outcome": "success" } ],
  "worst_parameters": [ { "metric": "min_branch_flow_ratio", "out_of_range_ms": 240000 } ],
  "conclusions": [ "Быстро обнаруживает отклонение.", "Правильно определяет первопричину и устраняет её." ]
}
```

| Раздел | Ожидаемо |
|---|---|
| `outcome` | `stabilized` только если параметры в норме **и** выполнены все семь downstream-проверок (8.1.4); иначе `not_stabilized` |
| `timings` | `detection_time_ms` (момент `declare_deviation` из 8.1.1), `reaction_time_ms`, `recovery_time_ms` заполнены, если отклонение фиксировалось и было корректное действие; иначе `null` |
| `scores` | пять составляющих в диапазоне 0–100 плюс `situation_awareness` (9.2) и `raw_nasa_tlx` (10.1) |
| `score_events` | у каждого есть `rule_code` и человеческое `reason` — ни одного необъяснённого штрафа |
| `actions.by_classification` | ваши команды из разделов 4/5/8: `correct`, `dangerous`, `repeated`, `cancelled`, `out_of_sequence` |
| `alarms.unacknowledged` | тревоги из 7.1, которые вы не подтвердили в 7.2 |
| `downstream_checks` | что закрыто (8.1.4) и что пропущено |
| `worst_parameters` | параметры с наибольшим временем вне допустимой области |
| `conclusions` | словесные выводы, соответствующие вашим действиям |
| утечка | во всём документе **нет** `random_seed`, `hidden`, `severity`, `onset_delay_ms` |

Повторный запрос отчёта должен дать **идентичный** документ.

### 12.2 `GET /operators/{operator_id}/level-comparison` (тег **reports**)

**Parameters:** `operator_id` — не из ответа, а из вашего собственного выбора
при создании сессий (2.1): `op-1`.

**Response body** (пример, после прохождения уровней 1 и 3):
```json
{
  "operator_id": "op-1",
  "levels": [
    { "level_no": 1, "session_id": "<SID уровня 1>", "resultiveness": 87.0, "safety": 92.0, "action_correctness": 88.5, "process_stability": 90.0, "reaction_speed": 76.0, "situation_awareness": 0.83, "raw_nasa_tlx": 5.17 },
    { "level_no": 3, "session_id": "<SID уровня 3>", "resultiveness": 61.0, "safety": 70.0, "action_correctness": 60.0, "process_stability": 65.0, "reaction_speed": 40.0, "situation_awareness": 0.5, "raw_nasa_tlx": 7.0 }
  ],
  "efficiency_retention": 70.11,
  "absolute_drop": 26.0
}
```

**Ожидаемо:** пусто (`levels: []`, оба показателя `null`), пока не пройдены
уровни 1 и 3 этим же `operator_id`. После двух завершённых сессий появятся
`efficiency_retention` (отношение результативности третьего уровня к первому в
процентах) и `absolute_drop`.

---

## 13. Воспроизводимость

Повторите 2.1–2.4 (и любые последующие действия) **дважды**, с **одинаковым**
`random_seed` в теле обеих `POST /sessions`, и подавайте одни и те же команды в
те же моменты симуляционного времени. Получите два разных `<SID>` — сохраните
оба, например `<SID_A>` и `<SID_B>`.

**Ожидаемо:** отчёты (12.1) по обеим сессиям совпадают, кроме идентификаторов, а
`state_hash` снимков идентичны — сверить можно только напрямую в БД, ручки для
этого нет:

```bash
uv run python -c "
import asyncio
from sqlalchemy import select
from app.infrastructure.db.engine import Database
from app.infrastructure.db.models import ProcessSnapshot
from app.settings import Settings
async def m():
    db=Database(Settings())
    async with db.session_factory() as s:
        rows=(await s.scalars(select(ProcessSnapshot).order_by(ProcessSnapshot.session_id, ProcessSnapshot.sim_time_ms))).all()
        for r in rows[:10]: print(r.session_id[:8], r.sim_time_ms//1000, r.state_hash[:16])
    await db.dispose()
asyncio.run(m())"
```

Разный seed даёт другую причину, ветвь и задержку — а значит другие хеши.

---

## На что смотреть особенно

Места, где логика легче всего могла бы оказаться нарисованной:

1. **Ничего не происходит мгновенно.** Пуск насоса — расход нарастает минуты.
   Корректирующее действие — восстановление 180 секунд.
2. **Запаздывание нарастает вниз по цепочке.** ЭЛОУ реагирует раньше К-1, К-1
   раньше К-2.
3. **Без Н-20 колонна К-1 пустая**, сколько бы ни шёл поток.
4. **Тревоги гаснут сами** после устранения причины, их не удаляют вручную.
5. **Ложных тревог на пуске нет** — низкий расход и низкий уровень при
   наполнении аппаратов законны.
6. **Возмущение ждёт устойчивого режима** — не выведете установку, не получите
   возмущения.
7. **Две причины различимы приборами**, а не только в скрытой конфигурации.
8. **Правильный тип действия по чужому адресу не помогает** — класс станет
   `ineffective`.

Если что-то из перечисленного ведёт себя иначе — это дефект.

---

## Автоматические проверки

Тот же сценарий покрыт тестами; они пригодятся как эталон поведения:

```bash
cd backend
uv run pytest -q                                    # весь набор
uv run pytest -q tests/e2e/test_demo_runs.py        # два демонстрационных прохождения
uv run pytest -q tests/e2e/test_replay.py           # воспроизводимость
uv run pytest -q -s tests/e2e/test_concurrent_sessions.py   # 20 одновременных сессий
```
