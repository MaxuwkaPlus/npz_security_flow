-- Воспроизводимые агрегаты для отчёта об экономике пилота.
-- Срез: 2026-08-24, Europe/Moscow. Валюта: российский рубль.
-- Страховые взносы: 30%; организационные накладные: 10%; горизонт: 5 месяцев.

-- role_costs и контрольный итог ФОТ.
WITH roles(role, role_short, fte, salary_low, salary_base, salary_high, responsibility) AS (
  VALUES
    ('Backend lead / архитектор', 'Backend lead', 1.0, 420000, 497000, 550000, 'Архитектура, recovery, code review, производительность'),
    ('Backend Python инженер', 'Backend', 1.0, 220000, 278000, 350000, 'API/WebSocket, persistence, auth и наблюдаемость'),
    ('Frontend React инженер', 'Frontend', 1.0, 210000, 260000, 320000, 'Пульт, accessibility, error states и тесты'),
    ('QA automation', 'QA', 1.0, 180000, 230000, 300000, 'E2E, нагрузка, backup/recovery и регрессия'),
    ('Инженер-технолог ЭЛОУ-АВТ', 'Технолог', 1.0, 200000, 250000, 320000, 'Причинность, пороги, безопасные действия и приёмка'),
    ('Product / Project manager', 'PM / PO', 0.5, 200000, 260000, 330000, 'Scope, бюджет, KPI и решения заказчика'),
    ('Методист / human factors', 'Методист', 0.5, 160000, 180000, 220000, 'SAGAT, NASA-TLX, scoring и учебная валидность'),
    ('DevOps / SRE', 'DevOps', 0.5, 220000, 280000, 350000, 'CI/CD, TLS, мониторинг, backup и capacity'),
    ('AppSec / ИБ', 'AppSec', 0.5, 200000, 250000, 330000, 'Threat model, secrets, RBAC, audit и hardening'),
    ('UX / UI', 'UX / UI', 0.3, 160000, 210000, 280000, 'Мнемосхема, тревоги, когнитивная нагрузка и usability')
),
calculated AS (
  SELECT
    *,
    fte * 5.0 AS person_months,
    ROUND(fte * salary_low * 5.0 * 1.30 * 1.10) AS loaded_cost_low_rub,
    ROUND(fte * salary_base * 5.0 * 1.30 * 1.10) AS loaded_cost_base_rub,
    ROUND(fte * salary_high * 5.0 * 1.30 * 1.10) AS loaded_cost_high_rub
  FROM roles
)
SELECT * FROM calculated ORDER BY loaded_cost_base_rub DESC;

WITH roles(fte, salary_low, salary_base, salary_high) AS (
  VALUES
    (1.0, 420000, 497000, 550000), (1.0, 220000, 278000, 350000),
    (1.0, 210000, 260000, 320000), (1.0, 180000, 230000, 300000),
    (1.0, 200000, 250000, 320000), (0.5, 200000, 260000, 330000),
    (0.5, 160000, 180000, 220000), (0.5, 220000, 280000, 350000),
    (0.5, 200000, 250000, 330000), (0.3, 160000, 210000, 280000)
)
SELECT
  SUM(fte) AS pilot_fte,
  SUM(fte) * 5.0 AS pilot_person_months,
  ROUND(SUM(fte * salary_low * 5.0 * 1.30 * 1.10)) AS low_fot_rub,
  ROUND(SUM(fte * salary_base * 5.0 * 1.30 * 1.10)) AS base_fot_rub,
  ROUND(SUM(fte * salary_high * 5.0 * 1.30 * 1.10)) AS high_fot_rub,
  ROUND(SUM(fte * salary_base * 5.0 * 1.30 * 1.10) * 1.15 + 55075) AS funding_request_rub
FROM roles;

-- infrastructure_scenarios.
WITH infrastructure(profile, monthly_rub, annual_rub) AS (
  VALUES
    ('Демо: ядро', 2460, 29520),
    ('Пилот: production + staging', 5155, 61860),
    ('Пилот: ядро + мониторинг', 7615, 91380),
    ('Пилот + CPU LLM', 8725, 104700),
    ('GPU L4, 100 часов в месяц', 6952, 83424),
    ('GPU L4, 730 часов в месяц', 50750, 609000)
)
SELECT * FROM infrastructure ORDER BY monthly_rub;

-- software_budget: публичные цены и проектные решения.
WITH software_budget(category, software, status, public_price, planning_cost, decision) AS (
  VALUES
    ('Приложение', 'Python, FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite, React, Vite', 'Обязательно', '0 ₽ лицензий', '0 ₽', 'Оставить текущий стек; вести SBOM'),
    ('ОС и публикация', 'Linux, Nginx/Caddy, systemd или Docker Engine/Compose', 'Обязательно', '0 ₽ лицензий', '0 ₽', 'Выбрать стандарт заказчика'),
    ('Качество и безопасность', 'pytest, Ruff, mypy, Playwright, k6, Trivy, npm audit', 'Обязательно', '0 ₽ лицензий', '0 ₽', 'Включить в CI'),
    ('Мониторинг', 'Prometheus + Grafana OSS + Loki', 'Обязательно для пилота', '0 ₽ лицензий', 'VM входит в инфраструктуру', 'Self-hosted по умолчанию'),
    ('Код и CI', 'GitHub Team', 'Опция', '4 USD/польз./мес.', '≈3 400 ₽/мес. для 10 пользователей', 'Можно заменить GitLab/Gitea заказчика'),
    ('Управление задачами', 'YouTrack Cloud', 'Опция', '0 USD до 10; от 4,50 USD/польз./мес.', '0 ₽ для команды до 10', 'Не покупать при наличии трекера'),
    ('Облачный мониторинг', 'Grafana Cloud Pro', 'Опция', 'от 19 USD/мес. + usage', 'от ≈1 615 ₽/мес. + usage', 'Только если допустим внешний SaaS'),
    ('Резервные копии', 'restic + S3-compatible storage', 'Обязательно', 'Клиент 0 ₽; 100 ГБ ≈129–235 ₽/мес.', '235 ₽/мес. + операции', 'Шифрование и restore drill'),
    ('LLM', 'llama.cpp + Qwen3-4B-Instruct-2507', 'Опция', '0 ₽ лицензий', 'CPU VM или GPU отдельно', 'Не включать в обязательное ядро')
)
SELECT * FROM software_budget ORDER BY category;

-- annual_opex и опции.
WITH annual_opex(item, annual_rub, status) AS (
  VALUES
    ('Команда сопровождения, 1,6 FTE', 6978972, 'База'),
    ('Инфраструктура ядра', 91380, 'База'),
    ('GitHub Team, 10 пользователей', 40800, 'Опция в базовом ориентире'),
    ('Базовый OPEX ядра', 7111152, 'Итого'),
    ('Один новый сценарий', 702416, 'По объёму контента'),
    ('ML/LLM сопровождение, 0,3 FTE', 1801800, 'Опция'),
    ('GPU L4, постоянно', 609000, 'Опция')
)
SELECT * FROM annual_opex ORDER BY item;

-- excluded_items: статьи вне базового scope.
WITH excluded_items(item, why_not_now, trigger) AS (
  VALUES
    ('PostgreSQL / managed database', 'Основное хранилище MVP — файловая SQLite', 'Высокая конкурентная запись или несколько инстансов'),
    ('Kubernetes и микросервисы', 'Модульный монолит достаточен для пилота', 'Утверждённый HA SLA и несколько независимых контуров'),
    ('OPC/SCADA/DCS лицензии', 'Интеграция с реальным производством исключена из MVP', 'Отдельное ТЗ и стенд интеграции'),
    ('Постоянный GPU', 'LLM опциональна и имеет fallback', 'Измеренная задержка подтверждает потребность'),
    ('Windows Server и коммерческая СУБД', 'Текущий стек от них не зависит', 'Обязательный стандарт заказчика'),
    ('Промышленная сертификация', 'Продукт является учебным MVP', 'Формальная аттестация или производственные решения')
)
SELECT * FROM excluded_items ORDER BY item;
