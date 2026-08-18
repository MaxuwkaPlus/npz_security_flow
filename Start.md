# Как запустить проект

Проект состоит из четырёх частей. Каждая запускается в своём терминале.

| Часть | Порт | Зачем |
|---|---|---|
| Backend | 8000 | считает установку, тревоги и оценку |
| Frontend | 5173 | пульт оператора и кабинет эксперта |
| LLM | 8080 | пишет текст рекомендаций |
| ML-сервис | 8100 | находит слабые места и предлагает сценарии |

Обязателен только backend и frontend. Без ML тренажёр работает полностью, без LLM
ML-сервис работает на шаблонных текстах.

## Подготовка (один раз)

```bash
cd backend && uv sync && uv run alembic upgrade head && uv run python -m app.cli seed
cd ../frontend && npm install
cd ../ml && uv sync
```

Скачать модель (2.3 ГБ, тоже один раз):

```bash
cd ml && mkdir -p models
curl -L -o models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf \
  https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
```

## Запуск (четыре терминала)

```bash
# 1 — backend
cd backend && SIMULATION_SPEED_FACTOR=10 uv run uvicorn app.main:app --port 8000
```

```bash
# 2 — frontend
cd frontend && npm run dev
```

```bash
# 3 — LLM
cd ml && llama-server -m models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf --port 8080 --ctx-size 8192 --jinja
```

```bash
# 4 — ML-сервис
cd ml && uv run uvicorn ml.service:app --port 8100
```

Откройте **http://localhost:5173**

`SIMULATION_SPEED_FACTOR` — во сколько раз симуляция быстрее реального времени.
Сценарий длится 65 минут, поэтому: `10` — пройти минут за 7, `1` — в реальном времени,
`300` — пролетит за 13 секунд, только для быстрой проверки.

## Как проверить, что всё поднялось

```bash
curl localhost:8000/api/v1/health   # {"status":"ok"}
curl localhost:8080/health          # {"status":"ok"}
curl localhost:8100/health          # llm_available: true
curl localhost:5173                 # страница отдаётся
```

## Что посмотреть

**Пульт оператора** — `http://localhost:5173`. Создайте сессию, запустите, ведите
установку: пуск насоса, вода на ЭЛОУ, насос Н-20, нагрузка печей. Дальше пойдут тревоги:
зафиксируйте отклонение, поставьте диагноз, выполните корректирующее действие и проверьте
последствия. В конце — отчёт.

**Кабинет эксперта** — ссылка на стартовом экране и в шапке пульта. Там видно:

- разбор прохождения по шести навыкам с обоснованием;
- предлагаемый сценарий на следующий раз;
- очередь предложений — утвердить или отклонить;
- системные проблемы по всем операторам.

Ни одна рекомендация не попадает в тренажёр сама: её утверждает эксперт.

## Остановить всё

```bash
pkill -f "uvicorn app.main"; pkill -f "uvicorn ml.service"; pkill -f llama-server; pkill -f "npm run dev"
```

## Если что-то не так

- **`couldn't bind HTTP server socket`** — порт уже занят, старый процесс не был
  остановлен. Проверить: `lsof -nP -iTCP:8080 -sTCP:LISTEN`.
- **В кабинете эксперта «Сервис рекомендаций недоступен»** — не запущен терминал 4.
- **В тексте рекомендаций написано «шаблон»** — не запущен терминал 3 с моделью.
- **`llama-server -hf ...:Q4_K_M` не работает** — в сборке из Homebrew так нельзя,
  качайте файл модели напрямую, как в подготовке.
- **Пустые оценки навыков** — это не ошибка: если возмущение ещё не дошло до оператора,
  оценивать нечего.

Подробности по частям: [backend/README.md](backend/README.md),
[frontend/README.md](frontend/README.md), [ml/README.md](ml/README.md).
