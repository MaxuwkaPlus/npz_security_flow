# Backend тренажёра операторов ЭЛОУ-АВТ

Источник истины по требованиям — [техническое задание](../docs/BACKEND_PROJECT_SPEC.md);
предметные подробности — [сценарий тренажёра](../docs/TRAINER_SCENARIO.md).

Backend является авторитетным источником состояния: фронтенд отправляет намерения
оператора и отображает полученное, но не считает технологическую динамику, не
классифицирует действия и не выставляет оценки.

## Запуск

```bash
cd backend
uv sync
uv run alembic upgrade head          # схема на чистой БД
uv run python -m app.cli seed        # публикация установки, сценария и политики оценки
uv run uvicorn app.main:app --reload
```

Документация API: `http://127.0.0.1:8000/docs`, схема — `/openapi.json`.

### Настройки

Все переменные окружения необязательны и имеют разумные значения по умолчанию.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./var/npz_security_flow.db` | Файловая SQLite; каталог создаётся автоматически |
| `SIMULATION_SPEED_FACTOR` | `1.0` | Во сколько раз симуляция быстрее реального времени |
| `SQLITE_BUSY_TIMEOUT_MS` | `5000` | Ограниченное ожидание блокировки записи |
| `LOG_LEVEL` | `INFO` | Уровень структурированных JSON-логов |

Сценарий длится 65 минут симуляционного времени. Для демонстрации поднимайте
`SIMULATION_SPEED_FACTOR` — например, `120` проходит сценарий примерно за полчаса
реального времени, `300` — за считанные минуты.

## Проверки

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

Отдельные группы: `tests/unit` (доменные правила), `tests/integration` (хранение и
прикладные сценарии на временной файловой SQLite), `tests/contract` (REST, WebSocket и
OpenAPI), `tests/e2e` (демонстрационные прохождения, replay и нагрузка).

## Демонстрационное прохождение

```bash
SC=$(curl -s localhost:8000/api/v1/scenarios | jq -r '.[0].id')
SID=$(curl -s -X POST localhost:8000/api/v1/sessions -H 'content-type: application/json' \
  -d "{\"request_id\":\"r1\",\"operator_id\":\"op-1\",\"scenario_version_id\":\"$SC\",\"level_no\":1,\"random_seed\":7}" | jq -r .id)

curl -s -X POST localhost:8000/api/v1/sessions/$SID/start -H 'content-type: application/json' -d '{"request_id":"r2"}'
curl -s -X POST localhost:8000/api/v1/sessions/$SID/actions -H 'content-type: application/json' \
  -d '{"request_id":"r3","action_type":"start_feed_pump","target_code":"N-1"}'
curl -s -X POST localhost:8000/api/v1/sessions/$SID/actions -H 'content-type: application/json' \
  -d '{"request_id":"r4","action_type":"set_wash_water","target_code":"ELOU","value":{"ratio":0.075}}'
curl -s -X POST localhost:8000/api/v1/sessions/$SID/actions -H 'content-type: application/json' \
  -d '{"request_id":"r5","action_type":"start_transfer_pump","target_code":"N-20"}'
curl -s -X POST localhost:8000/api/v1/sessions/$SID/actions -H 'content-type: application/json' \
  -d '{"request_id":"r6","action_type":"set_furnace_heat_load","target_code":"FURNACES","value":{"heat_load_pct":100}}'

curl -s localhost:8000/api/v1/sessions/$SID/state
curl -s localhost:8000/api/v1/sessions/$SID/alarms
curl -s localhost:8000/api/v1/sessions/$SID/report
```

Поток состояния в реальном времени: `ws://localhost:8000/ws/v1/sessions/{session_id}`.
Клиент передаёт `?last_sequence_no=N`, получает пропущенные сообщения из журнала и
продолжает слушать; по `sequence_no` он замечает пропуск и запрашивает состояние REST-ом.

## Устройство

```text
app/
├── domain/          технологические правила: двойник, тревоги, этапы, оценка
├── application/     прикладные сценарии и транзакционные границы
├── infrastructure/  ORM, репозитории, realtime, фоновая симуляция, seed
└── api/v1/          REST и WebSocket, DTO белым списком полей
```

Доменный слой не импортирует FastAPI, SQLAlchemy и транспорт. Пороги, коэффициенты,
окна и веса живут в опубликованной версии сценария и политики оценки, а не в коде.

### Что важно знать о поведении

- **Один писатель на сессию.** Тик и команда оператора идут внутри блокировки сессии
  и одной короткой транзакции, поэтому состояние не расходится.
- **Команда не меняет установку мгновенно.** Расход, температура и нагрузка участков
  описаны апериодическими звеньями, запаздывание нарастает вниз по цепочке.
- **Возмущение вводится после подтверждения устойчивого режима**, а не в фиксированный
  момент: оператор может выйти на режим быстрее или медленнее.
- **Скрытое состояние не покидает backend.** Причина, целевая ветвь, seed и
  интенсивность возмущения доступны только расчёту, аудиту и отчёту инструктора.
- **Прохождение воспроизводимо.** Одинаковые версии, seed и журнал действий дают
  совпадающие `state_hash` снимков и один и тот же отчёт.

## Измеренная производительность

На одном экземпляре с файловой SQLite: **20 одновременных сессий, 600 шагов за 9,5 с
(≈63 шага/с, 15,8 мс на шаг)** — `tests/e2e/test_concurrent_sessions.py`. Это измерение
на машине разработчика, а не подтверждённый SLA: цель по нагрузке фиксируется отдельно.

## Границы реализации

Вне текущего объёма: ML-модель и inference, пользовательский интерфейс, точная
физико-химическая модель НПЗ, интеграции с АСУ ТП, несколько установок и распределённое
выполнение. Значения порогов и штрафов, не подтверждённые исходными материалами,
помечены в конфигурации как `provisional` и требуют согласования с технологом.
