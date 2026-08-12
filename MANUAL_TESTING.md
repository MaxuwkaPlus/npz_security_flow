# План ручного тестирования backend

Проверка бизнес-логики тренажёра ЭЛОУ-АВТ вручную: что подаём на вход и что должно
получиться. Ожидания выведены из опубликованной конфигурации сценария — порогов,
allowlist и правил, — а не из подогнанного прогона.

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

Во втором терминале:

```bash
cd backend
export API=http://localhost:8000/api/v1
```

О скорости: `10` — чтобы успевать читать показания и вводить команды; `60`–`300` —
чтобы быстро увидеть весь цикл. Всё симуляционное время ниже указано в секундах
сценария, а не реальных.

---

## 1. Смоук: сервис и каталог

| Запрос | Ожидаемо |
|---|---|
| `curl $API/health` | `{"status":"ok"}` |
| `curl $API/ready` | `{"status":"ready"}` — проверяется соединение с БД |
| `curl $API/scenarios` | массив из одного элемента, `scenario_code: ELOU-AVT-FULL-RUN`, `duration_ms: 3900000` |
| `curl $API/nope` | 404, тело `{"error":{"code":"HTTP_ERROR",...,"request_id":"..."}}` |

```bash
export SC=$(curl -s $API/scenarios | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
curl -s $API/scenarios/$SC | python3 -m json.tool | head -40
```

**Ожидаемо:** три уровня сложности (1/2/3), двадцать этапов от `precheck` до
`final_stabilization`.

**Проверка утечки:** в ответе **нет** слов `disturbance`, `hidden`,
`pump_capacity_loss`, `valve_stiction`, `target_selector`.

```bash
export INST=$(curl -s $API/scenarios/$SC | python3 -c 'import json,sys;print(json.load(sys.stdin)["installation_version_id"])')
curl -s $API/installations/$INST/topology | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d["equipment"]),"аппаратов,",len(d["edges"]),"связей")'
```

**Ожидаемо:** около 52 аппаратов и 50 связей. Среди кодов есть `FRC-404/405/406`,
`T-1_T-11`, `ELOU`, `V-15`, `K-1`, `FURNACES`, `K-2`, `PRODUCTS`. У `FRC-405` есть тег
`branch_2_flow_tph` с `critical_min: 88.0`.

---

## 2. Жизненный цикл сессии

```bash
export SID=$(curl -s -X POST $API/sessions -H 'content-type: application/json' \
  -d "{\"request_id\":\"c1\",\"operator_id\":\"op-1\",\"scenario_version_id\":\"$SC\",\"level_no\":1,\"random_seed\":7}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo $SID
```

| Вход | Ожидаемо |
|---|---|
| `POST /sessions` | 201, `status: "ready"` — конфигурация фиксируется при создании; `sim_time_ms: 0`, этап `precheck` |
| ответ на создание | **нет** полей `random_seed`, `hidden`, `target_branch` |
| повтор с тем же `request_id: c1` | тот же `id` сессии, вторая сессия не создаётся |
| `POST /sessions/$SID/pause` до старта | **409**, код `SESSION_TRANSITION_NOT_ALLOWED`, `details.status: "ready"` |
| `level_no: 0` или `4` | **422**, код `VALIDATION_ERROR` |

```bash
curl -s -X POST $API/sessions/$SID/start -H 'content-type: application/json' -d '{"request_id":"s1"}'
```

**Ожидаемо:** `status: "running"`. С этого момента идёт симуляционное время.

### Пауза останавливает время

```bash
curl -s -X POST $API/sessions/$SID/pause -H 'content-type: application/json' -d '{"request_id":"p1"}'
sleep 10
curl -s $API/sessions/$SID/state          # sim_time_ms не изменился
curl -s -X POST $API/sessions/$SID/resume -H 'content-type: application/json' -d '{"request_id":"p2"}'
```

**Ожидаемо:** между `pause` и `resume` `sim_time_ms` **стоит на месте**. Повтор `pause`
с `request_id: p1` возвращает прежний ответ и не создаёт второй переход.

### Проверка версии

Отправьте `{"request_id":"x1","expected_version":1}` на `/pause` после нескольких
тиков.

**Ожидаемо:** **409**, код `SESSION_VERSION_MISMATCH`.

---

## 3. Осмотр установки — этап `precheck`

Этап ждёт четыре явные проверки. Без них он закроется таймаутом на 240-й секунде
симуляции.

```bash
for T in FEED-SYSTEM T-1_T-11 ELOU K-2; do
  curl -s -X POST $API/sessions/$SID/observations -H 'content-type: application/json' \
    -d "{\"request_id\":\"o-$T\",\"observation_type\":\"inspect_equipment\",\"target_code\":\"$T\"}"; echo; done
curl -s $API/sessions/$SID/state
```

| Вход | Ожидаемо |
|---|---|
| четыре наблюдения `inspect_equipment` | 201 на каждое; этап меняется на `feed_preparation` **до** 240 с симуляции |
| `observation_type: "peek"` | 422, `UNKNOWN_OBSERVATION_TYPE` |
| `verify_result` на `N-1` | 422, `OBSERVATION_TARGET_NOT_ALLOWED` |
| повтор с тем же `request_id` | прежний ответ, дубля нет |

Допустимые адреса `verify_result`: `FEED-SYSTEM`, `T-1_T-11`, `ELOU`, `V-15`, `K-1`,
`FURNACES`, `K-2`, `PRODUCTS`.

---

## 4. Валидация команд

| Вход | Ожидаемо |
|---|---|
| `{"action_type":"open_secret_bypass","target_code":"N-1"}` | 202, `status: "rejected"`, `rejection_reason: "unknown_action_type"` |
| `{"action_type":"set_control_valve","target_code":"K-2"}` | 202, `rejected`, `target_not_allowed` |
| `{"action_type":"set_control_valve","target_code":"FRC-404","value":{"opening_pct":140}}` | 202, `rejected`, `value_out_of_range` |
| `{"action_type":"set_control_valve","target_code":"FRC-404"}` без `value` | 202, `rejected`, `missing_value` |
| любая команда на приостановленной сессии | **409**, `SESSION_NOT_RUNNING` |

Отклонённая команда **записывается в журнал** — она входит в оценку, — но на установку
не влияет: расходы не должны измениться.

### Отмена команды

```bash
AID=$(curl -s -X POST $API/sessions/$SID/actions -H 'content-type: application/json' \
  -d '{"request_id":"cancel-me","action_type":"set_control_valve","target_code":"FRC-404","value":{"opening_pct":50}}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
curl -s -X POST $API/sessions/$SID/actions/$AID/cancel -d '{}' -H 'content-type: application/json'
```

| Вход | Ожидаемо |
|---|---|
| отмена принятой команды | `status: "cancelled"`, клапан **не** уходит на 50 % |
| повторная отмена | прежний ответ |
| отмена уже применённой команды | 409, `ACTION_ALREADY_RESOLVED` |

---

## 5. Пуск установки и причинно-следственная цепочка

Подавайте команды **по одной** и смотрите состояние между ними. Это основная проверка
того, что модель причинна, а не рисует числа.

```bash
act()  { curl -s -X POST $API/sessions/$SID/actions -H 'content-type: application/json' -d "$1"; echo; }
obs()  { curl -s -X POST $API/sessions/$SID/observations -H 'content-type: application/json' -d "$1"; echo; }
state(){ curl -s $API/sessions/$SID/state; echo; }
```

Показания приборов удобно смотреть из последнего снимка:

```bash
values() {
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
}
```

### 5.1. Сырьевой насос

```bash
act '{"request_id":"a1","action_type":"start_feed_pump","target_code":"N-1"}'
```

| Момент | Ожидаемо |
|---|---|
| сразу после команды | `status: "accepted"`, а не «applied» — применит ближайший шаг симуляции |
| +5 с | `feed_pump_state: RUNNING`, давление на выкиде растёт к 6.0 бар, расходы ветвей **малы** — единицы т/ч |
| +60 с | каждая ветвь примерно 50–90 т/ч: расход нарастает постепенно, а не скачком |
| +180 с | около 95–100 т/ч на ветвь, `total_feed_flow_tph` ≈ 300 |

### 5.2. Температура после Т-1…Т-11

Наблюдайте `branch_N_t11_outlet_temp_c` по мере прогрева.

**Ожидаемо:** от 25 °C растёт примерно до **130 °C** и там остаётся. Предел регламента —
140 °C, при штатном расходе он не превышается. Прогрев занимает около 15 минут
симуляции.

### 5.3. Промывочная вода на ЭЛОУ

```bash
act '{"request_id":"a2","action_type":"set_wash_water","target_code":"ELOU","value":{"ratio":0.075}}'
```

| Вход | Ожидаемо |
|---|---|
| `ratio: 0.075` | `elou_wash_water_ratio: 0.075` — регламент 5–10 %; этап `elou_feed_and_water` закрывается успехом |
| `ratio: 0.5` | значение обрезается до 0.20 — максимум конфигурации |

**Уровни ЭЛОУ:** `elou_stage1_min_level_mm` растёт от 0 примерно до **3820 мм**. Пока
аппарат наполняется, уровень законно ниже 3500 мм — **тревоги блокировки быть не
должно**. Защита взводится только после вывода ступени в работу, то есть от 3700 мм.

### 5.4. Насосы Н-20 и колонна К-1

```bash
act '{"request_id":"a3","action_type":"start_transfer_pump","target_code":"N-20"}'
```

**Ожидаемо:** до этой команды `k1_feed_flow_ratio` равен 0 и `k1_bottom_temp_c` равен 0,
сколько бы ни шёл поток — без откачки из Е-15 сырьё до колонны не доходит. После
команды К-1 наполняется: давление около 1.6 бар, низ около 268 °C, уровень около 50 %.

### 5.5. Печи

```bash
act '{"request_id":"a4","action_type":"set_furnace_heat_load","target_code":"FURNACES","value":{"heat_load_pct":100}}'
```

| Момент | Ожидаемо |
|---|---|
| до розжига | `furnace_heat_load_pct: 0`, `furnace_heat_to_feed_ratio: 0`, температура на выходе равна низу К-1 |
| после розжига | выход около 340 °C, `furnace_heat_to_feed_ratio` ≈ **1.0**, низ К-2 около 338 °C, `k2_stability_index` стремится к 1.0 |

Этап `furnaces` требует соотношение в диапазоне 0.95–1.05 — при погашенных печах он
**не** закроется успехом.

---

## 6. Выход на режим и запуск возмущения

Дождитесь, пока `current_stage_code` дойдёт до `stable_mode`, а затем сменится на
`disturbance_monitoring`.

**Ожидаемо:** к этому моменту `min_branch_flow_ratio ≥ 0.95`,
`flow_imbalance_ratio ≤ 0.05`, `t11_max_temp_c ≤ 140`, `k1_feed_flow_ratio ≥ 0.95`,
`k2_stability_index ≥ 0.85` держатся непрерывно 20 секунд.

**Ключевое поведение:** возмущение вводится **только после подтверждения устойчивого
режима** плюс задержка 0–120 секунд, которую выбирает seed. Если не подать воду или не
запустить Н-20, режим не подтвердится и **возмущения не будет вовсе**. Это правильное
поведение, а не поломка.

---

## 7. Развитие возмущения и тревоги

Ничего не делайте 5–8 минут симуляции и следите за `curl $API/sessions/$SID/alarms`.

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
распространение возмущения по цепочке.

Фоном появляются `nuisance_auxiliary_N` уровня **L0** на `AUX-SYSTEM` — методический
шум. На уровне 1 редко, на уровне 3 часто. Гаснут сами через 120 секунд.

### Подтверждение тревоги

```bash
AL=$(curl -s $API/sessions/$SID/alarms | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
curl -s -X POST $API/sessions/$SID/alarms/$AL/acknowledge -H 'content-type: application/json' -d '{"request_id":"ack1"}'
```

**Ожидаемо:** `state: "active_acknowledged"`. Повтор возвращает тот же момент
подтверждения и не создаёт второго события.

---

## 8. Диагностика — главная проверка бизнес-логики

**Сначала определите причину сами по приборам, не подглядывая.** Причин ровно две, и
они различимы:

| Признак | Вывод |
|---|---|
| `feed_pump_discharge_pressure_bar` упало ниже 5.2, а `branch_N_valve_actual_pct` **равно** `branch_N_valve_command_pct` | `pump_capacity_loss` |
| давление на выкиде **не упало**, даже выросло выше 6.0, а `valve_actual_pct` заметно **меньше** `valve_command_pct` | `valve_stiction` |

Проблемная ветвь — с минимальным расходом; её номер есть в `lowest_flow_branch_code`:
1 → `FRC-404`, 2 → `FRC-405`, 3 → `FRC-406`.

Подсмотреть разгадку можно в роли инструктора — **после** собственного вывода:

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

### Ветка А — правильный путь

```bash
obs '{"request_id":"d1","observation_type":"declare_deviation","target_code":"FEED-SYSTEM"}'
obs '{"request_id":"d2","observation_type":"compare_flows","target_code":"FEED-SYSTEM"}'
obs '{"request_id":"d3","observation_type":"inspect_pressure","target_code":"FEED-SYSTEM"}'
obs '{"request_id":"d4","observation_type":"inspect_equipment","target_code":"N-1"}'

curl -s -X POST $API/sessions/$SID/diagnoses -H 'content-type: application/json' \
  -d '{"request_id":"dg1","affected_area_code":"FEED-SYSTEM","deviation_code":"branch_flow_loss","suspected_cause_code":"pump_capacity_loss"}'
```

**Ожидаемо:** 201, и в ответе **нет** поля `is_correct` — правильность диагноза
оператору не сообщается.

Корректирующее действие выбирается по вашему диагнозу:

- `pump_capacity_loss` → `{"action_type":"switch_to_standby_pump","target_code":"N-1A"}`
- `valve_stiction` → `{"action_type":"restore_flow_control","target_code":"FRC-40X"}`,
  где `X` = 3 + номер ветви

| Проверка | Ожидаемо |
|---|---|
| через 10 с после действия | расход **почти не изменился** — восстановление занимает 180 с |
| через 200–300 с | `min_branch_flow_ratio` вернулся к значению ≥ 0.95 |
| тревоги | L1, L2, L3 гаснут **сами** по своим порогам снятия: 0.95, 0.08 и 138 °C |
| класс действия | сразу после применения пуст; через 240 с окна становится `correct` |
| правильный тип по чужому адресу | причина не устраняется, класс `ineffective` |
| корректирующее действие **до** диагноза | класс `out_of_sequence` |

Затем downstream-проверки:

```bash
for T in FEED-SYSTEM T-1_T-11 ELOU V-15 K-1 FURNACES K-2 PRODUCTS; do
  obs "{\"request_id\":\"v-$T\",\"observation_type\":\"verify_result\",\"target_code\":\"$T\"}"; done
```

### Ветка Б — опасная компенсация

Запускать на отдельной сессии. Вместо восстановления расхода добавьте тепла:

```bash
act '{"request_id":"bad","action_type":"set_furnace_heat_load","target_code":"FURNACES","value":{"heat_load_pct":125}}'
```

| Проверка | Ожидаемо |
|---|---|
| класс действия | `dangerous` **сразу**, без ожидания окна наблюдения |
| `furnace_heat_to_feed_ratio` | превышает 1.25 → тревога L5 `unsafe_furnace_heat_to_feed` |
| `furnace_outlet_temp_c` | выше 360 °C, низ К-2 уходит выше 350 °C |
| `k2_stability_index` | падает **сильнее**, чем при бездействии — компенсация ухудшает процесс |
| отчёт | вывод «Компенсирует симптом тепловой нагрузкой вместо восстановления расхода», снижение `safety` |

Контрольная проверка: снижение нагрузки вслед за расходом, например
`heat_load_pct: 88`, **не** считается опасным и возвращает соотношение в норму.

---

## 9. SAGAT

```bash
curl -s $API/sessions/$SID/sagat/current | python3 -m json.tool
```

**Ожидаемо:** после успешного завершения `stable_mode` появляется контрольная точка
`after_stable_mode` с тремя вопросами трёх видов: `what_changed`, `what_it_means`,
`what_happens_next`. В ответе **нет** эталонных ответов, метрик и порогов — только
формулировки и варианты. До этого этапа возвращается `null`.

```bash
CP=$(curl -s $API/sessions/$SID/sagat/current | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
curl -s -X POST $API/sessions/$SID/sagat/$CP/answers -H 'content-type: application/json' \
  -d '{"request_id":"sg1","answers":{"lowest_flow_branch":"2","t11_over_limit":"no","k1_feed_trend":"steady"}}'
```

| Ответ | Ожидаемая оценка |
|---|---|
| совпал с фактическим состоянием | 1.0 |
| «steady» вместо реального роста или падения | 0.5 — частичное понимание |
| противоположный тренд или неверная ветвь | 0.0 |
| вопрос не отвечен | 0.0 |

Эталон вычисляется из состояния установки на момент вопроса — сверьте свои ответы с
показаниями снимка в ту секунду. Повторный `GET /sagat/current` после ответа возвращает
`null`. Вторая контрольная точка `after_correction` появляется после успешного
завершения этапа `recovery`.

---

## 10. NASA-TLX

```bash
curl -s -X POST $API/sessions/$SID/nasa-tlx -H 'content-type: application/json' \
  -d '{"mental_demand":7,"physical_demand":2,"temporal_demand":6,"performance":3,"effort":5,"frustration":4}'
```

**Ожидаемо:** 201, `raw_tlx_score` равен **5.17**. Арифметика проверяема: шкала
успешности инвертируется, 3 → 7; сумма 7+2+6+7+5+4 = 31, среднее 31/6 ≈ 5.17.

| Вход | Ожидаемо |
|---|---|
| повторная отправка | 409, `NASA_TLX_ALREADY_SUBMITTED` |
| `"effort": 42` | 422, `VALIDATION_ERROR` |
| влияние на баллы | `resultiveness` в отчёте **не меняется** — показатель хранится отдельно |

---

## 11. WebSocket

```bash
uv run python -c "
import asyncio, json, websockets
async def m():
    async with websockets.connect('ws://localhost:8000/ws/v1/sessions/$SID?last_sequence_no=0') as ws:
        for _ in range(15):
            m=json.loads(await ws.recv())
            print(m['sequence_no'], m['type'], m['sim_time_ms'])
asyncio.run(m())"
```

| Проверка | Ожидаемо |
|---|---|
| формат конверта | у каждого сообщения есть `schema_version`, `type`, `session_id`, `sequence_no`, `sim_time_ms`, `payload` |
| нумерация | `sequence_no` идут подряд без пропусков, начиная с 1 |
| догон | подключение с `?last_sequence_no=5` начинается с шестого сообщения, ничего не теряется |
| снимки | `process_snapshot` приходит ровно раз в 5 секунд симуляции |
| утечка | в `payload` снимка **нет** `severity`, `internal_state` и других скрытых полей |
| события | команда оператора даёт `action_status_changed`, тревога — `alarm_raised` |

---

## 12. Отчёт и сравнение уровней

```bash
curl -s $API/sessions/$SID/report | python3 -m json.tool
```

| Раздел | Ожидаемо |
|---|---|
| `outcome` | `stabilized` только если параметры в норме **и** выполнены все семь downstream-проверок; иначе `not_stabilized` |
| `timings` | `detection_time_ms`, `reaction_time_ms`, `recovery_time_ms` заполнены, если отклонение фиксировалось и было корректное действие; иначе `null` |
| `scores` | пять составляющих в диапазоне 0–100 плюс `situation_awareness` и `raw_nasa_tlx` |
| `score_events` | у каждого есть `rule_code` и человеческое `reason` — ни одного необъяснённого штрафа |
| `actions.by_classification` | ваши `correct`, `dangerous`, `repeated`, `cancelled`, `out_of_sequence` |
| `alarms.unacknowledged` | те тревоги, которые вы не подтвердили |
| `downstream_checks` | что закрыто и что пропущено |
| `worst_parameters` | параметры с наибольшим временем вне допустимой области |
| `conclusions` | словесные выводы, соответствующие вашим действиям |
| утечка | во всём документе **нет** `random_seed`, `hidden`, `severity`, `onset_delay_ms` |

Повторный запрос отчёта должен дать **идентичный** документ.

```bash
curl -s $API/operators/op-1/level-comparison | python3 -m json.tool
```

**Ожидаемо:** пусто, пока не пройдены уровни 1 и 3. После двух сессий одного
`operator_id` с `level_no: 1` и `level_no: 3` появятся `efficiency_retention`, равный
отношению результативности третьего уровня к первому в процентах, и `absolute_drop`.

---

## 13. Воспроизводимость

Создайте две сессии с **одинаковым** `random_seed` и повторите одни и те же команды в
те же моменты симуляционного времени.

**Ожидаемо:** отчёты совпадают, кроме идентификаторов, а `state_hash` снимков
идентичны:

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
2. **Запаздывание нарастает вниз по цепочке.** ЭЛОУ реагирует раньше К-1, К-1 раньше
   К-2.
3. **Без Н-20 колонна К-1 пустая**, сколько бы ни шёл поток.
4. **Тревоги гаснут сами** после устранения причины, их не удаляют вручную.
5. **Ложных тревог на пуске нет** — низкий расход и низкий уровень при наполнении
   аппаратов законны.
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
