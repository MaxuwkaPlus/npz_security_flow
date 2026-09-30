-- Reproducible, aggregate-only source rows for the report artifact.
-- Snapshot: 2026-08-24, Europe/Moscow. No credentials or session-level records.

-- headline_metrics
SELECT
  332 AS backend_tests,
  56 AS measured_ticks_per_s,
  '3–5 МБ' AS storage_per_session,
  '30–45 чел.-мес.' AS pilot_person_months;

-- capacity_scenarios
WITH capacity_scenarios(scenario, ticks_per_s, concurrent_sessions, speed_factor, kind, interpretation) AS (
  VALUES
    ('20 сессий ×1', 20, 20, 1, 'demand', 'Проектная цель real-time; ниже рабочего бюджета'),
    ('Рабочий бюджет', 30, NULL, NULL, 'planning', 'Около 55% локального измеренного пика'),
    ('3 сессии ×10', 30, 3, 10, 'demand', 'Практический предел рабочего бюджета'),
    ('5 сессий ×10', 50, 5, 10, 'demand', 'Почти весь локально измеренный пик'),
    ('Измеренный максимум', 56, 20, 300, 'measured', '600 тиков за 10,7 с на Apple M4; не SLA')
)
SELECT * FROM capacity_scenarios;

-- technology_stack
WITH technology_stack(layer, software, role, readiness) AS (
  VALUES
    ('1. Backend API', 'Python 3.12+; FastAPI; Uvicorn; Pydantic', 'REST, WebSocket, use-cases', 'Реализовано и типизировано'),
    ('2. Домен', 'Чистый Python; детерминированный digital twin', 'Тики, тревоги, стадии, scoring, RBAC', 'Не зависит от FastAPI/ORM'),
    ('3. Хранение', 'SQLAlchemy async; aiosqlite; Alembic; SQLite WAL', '31 таблица, события, snapshots, аудит', 'Один инстанс; без HA'),
    ('4. Frontend', 'React 19; Vite 8; JavaScript/JSX/CSS', 'Пульт, отчёт, кабинеты эксперта и ИБ', 'Сборка есть; автотестов нет'),
    ('5. Рекомендации', 'Python; FastAPI; pandas; httpx; sqlite3', 'Правила навыков, mining, очередь', 'Rule-based; не обученная ML-модель'),
    ('6. LLM, опция', 'llama.cpp; Qwen3-4B Q4_K_M', 'Только текст для эксперта', 'Есть шаблонный fallback'),
    ('7. Качество', 'pytest; Ruff; mypy strict; npm build', '332 backend и 37 ML тестов', 'Frontend coverage отсутствует'),
    ('8. Эксплуатация', 'Локальные uv/npm команды; JSON-логи; health/ready', 'Запуск и диагностика', 'Нет CI, TLS-proxy, метрик, backup runbook')
)
SELECT * FROM technology_stack;

-- server_profiles
WITH server_profiles(profile, load, vcpu, ram, disk, accelerator, comment) AS (
  VALUES
    ('Демо: ядро', '1–3 сессии; ×1–×10', 2, '2 ГБ', '20 ГБ SSD', 'Нет', 'Backend + static frontend; без LLM'),
    ('Пилот: ядро + правила', 'До 20 сессий ×1', 4, '4–8 ГБ', '40 ГБ NVMe', 'Нет', 'Повторить нагрузку на целевой VM'),
    ('Пилот: локальная LLM', 'До 20 core-сессий ×1; 1–2 генерации', 8, '16 ГБ', '50 ГБ SSD', 'Опционально ≥8 ГБ VRAM', 'Отделить llama-server при росте конкуренции'),
    ('Массовое ускорение / HA', '>3 сессий ×10 или несколько backend-инстансов', 8, '16+ ГБ', 'По retention', 'По LLM', 'Требует изменения архитектуры')
)
SELECT * FROM server_profiles;

-- storage_scenarios
WITH storage_scenarios(sessions_per_year, primary_storage, budget_storage, operational_note) AS (
  VALUES
    (100, '0,3–0,5 ГБ/год', '1,2–2 ГБ/год', 'Вмещается с большим запасом в демо-контур'),
    (1000, '3–5 ГБ/год', '12–20 ГБ/год', '40 ГБ SSD достаточно для первого года пилота'),
    (10000, '30–50 ГБ/год', '120–200 ГБ/год', 'Нужны retention, архивирование и решение о смене SQLite')
)
SELECT * FROM storage_scenarios;

-- pilot_team
WITH pilot_team(role, fte, responsibility, mandatory) AS (
  VALUES
    ('Backend-инженеры', 2.0, 'Recovery, ML auth, API/WS, persistence, observability', 'Обязательно'),
    ('Инженер-технолог ЭЛОУ-АВТ', 1.0, 'Пороги, причинность, безопасные действия, приёмка', 'Критически обязательно'),
    ('Frontend-инженер', 1.0, 'Пульт, accessibility, error states, тесты', 'Обязательно'),
    ('QA automation', 1.0, 'Frontend/API/E2E, нагрузка, recovery, регрессия', 'Обязательно'),
    ('Product/Project manager', 0.5, 'Scope, пилот, KPI, решения заказчика и экономика', 'Обязательно'),
    ('Методист / human factors', 0.5, 'SAGAT, NASA-TLX, scoring, учебная валидность', 'Обязательно'),
    ('DevOps/SRE', 0.5, 'Deploy, TLS, backup, monitoring, runbook', 'Обязательно'),
    ('AppSec / ИБ', 0.5, 'Threat model, secrets, RBAC, audit, hardening', 'Обязательно'),
    ('UX/UI', 0.3, 'Мнемосхема, тревоги, нагрузка, usability', 'Желательно'),
    ('ML/LLM-инженер', 0.8, 'Оценка рекомендаций, inference, guardrails, latency/cost', 'Опция: 0,5–1,0 FTE')
)
SELECT * FROM pilot_team;

-- economic_inputs
WITH economic_inputs(step_order, input, owner, use_case) AS (
  VALUES
    (1, 'Площадки, обучаемые, сессии/месяц, пик', 'Product owner + учебный центр', 'Инфраструктура, стоимость сессии, масштаб эффекта'),
    (2, 'Fully-loaded ставки и доступность экспертов', 'Finance + HR + подрядчики', 'CAPEX разработки и ежегодная поддержка'),
    (3, 'On-prem/cloud, закупка, амортизация', 'IT + закупки + Finance', 'Инфраструктурный CAPEX/OPEX'),
    (4, 'SLA, backup, retention, RTO/RPO', 'IT/SRE + ИБ + владелец процесса', 'Штат сопровождения и резервирование'),
    (5, 'Число сценариев и экспертная приёмка', 'Технолог + методист', 'Контентный CAPEX и ежегодное обновление'),
    (6, 'Local LLM, GPU или внешний inference', 'Архитектор + ИБ + Finance', 'Опциональный compute/OPEX и риски данных'),
    (7, 'Часы инструктора, время подготовки, safety KPI', 'Учебный центр + производство + HSE', 'Benefit, ROI, payback')
)
SELECT step_order AS "order", input, owner, use_case AS use FROM economic_inputs;

-- risk_register
WITH risk_register(priority, gap, impact, required_action) AS (
  VALUES
    ('P0', 'Пароли записаны в пользовательском изменении Start.md', 'Компрометация стенда и аварийная смена данных', 'Сменить, удалить, включить secret scanning'),
    ('P0', 'ML API без аутентификации; expert_id задаёт клиент', 'Просмотр профилей и подмена решений эксперта', 'Backend principal/RBAC и server-side identity'),
    ('P1', 'Running-сессии не восстанавливаются после рестарта', 'Потеря учебного времени и зависшие статусы', 'Startup recovery, lease, recovery-тест'),
    ('P1', 'Нет CI/deploy/TLS/metrics/backup-restore', 'Высокая стоимость релиза и неизвестные RTO/RPO', 'Deploy, reverse proxy, monitoring, restore drill'),
    ('P1', 'Технологические значения provisional', 'Нельзя обосновать безопасность и аттестацию', 'Формальная предметная приёмка'),
    ('P1', 'Frontend без автотестов/type-check; latest в manifest', 'Регрессии UI и нестабильные обновления', 'Зафиксировать версии; lint, component/E2E tests'),
    ('P2', 'SQLite + in-memory hub ограничивают HA', 'Вертикальный потолок', 'Менять после подтверждённого масштаба'),
    ('P2', 'ML-каталог — правила на синтетике', 'Нельзя обещать predictive ML', 'Позиционировать как explainable baseline')
)
SELECT * FROM risk_register;

