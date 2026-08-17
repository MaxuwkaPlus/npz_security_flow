"""Все настраиваемые величины ML-части в одном месте.

Правило проекта: пороги, веса и временные окна не разбросаны по коду, а лежат в
конфигурации. Здесь то же самое — если методист меняет порог «слабого навыка»,
он правит один файл, а не ищет числа по модулям.

Значения ниже — методическое допущение уровня MVP (`provisional` в терминах
технического задания). Их подтверждает эксперт, а не код.
"""

import os
from dataclasses import dataclass
from pathlib import Path

# --- Пути -----------------------------------------------------------------

# ml/ml/config.py -> ml/ml -> ml -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[2]

# Синтетический корпус: 36 прохождений, 6 профилей поведения. Только чтение.
CORPUS_DIR = REPO_ROOT / "data" / "elou_avt_risk_next_30s" / "sample"

# Боевая база тренажёра. ML открывает её строго в режиме read-only.
BACKEND_DB = REPO_ROOT / "backend" / "var" / "npz_security_flow.db"

# Собственная база ML: только очередь предложений эксперту.
ML_DB = Path(os.getenv("ML_DB_PATH", REPO_ROOT / "ml" / "var" / "ml.db"))

# --- LLM ------------------------------------------------------------------

# llama.cpp поднимается отдельно и говорит по OpenAI-совместимому протоколу:
#   llama-server -hf unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M \
#       --port 8080 --ctx-size 8192 --jinja
LLM_BASE_URL = os.getenv("ML_LLM_BASE_URL", "http://127.0.0.1:8080")
LLM_MODEL = os.getenv("ML_LLM_MODEL", "qwen3-4b-instruct-2507")
# Низкая температура: нужен предсказуемый методический текст, а не разнообразие.
LLM_TEMPERATURE = float(os.getenv("ML_LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_S = float(os.getenv("ML_LLM_TIMEOUT_S", "60"))
LLM_MAX_TOKENS = int(os.getenv("ML_LLM_MAX_TOKENS", "700"))

# --- Навыки ---------------------------------------------------------------

# Порядок важен: при равных баллах слабым считается навык, стоящий выше.
# Сначала то, что угрожает установке, потом то, что относится к качеству работы.
SKILL_ORDER: tuple[str, ...] = (
    "safety",
    "correction",
    "diagnosis",
    "detection",
    "verification",
    "alarm_handling",
)

SKILL_NAMES: dict[str, str] = {
    "safety": "Безопасность действий",
    "correction": "Корректирующее действие",
    "diagnosis": "Диагностика первопричины",
    "detection": "Обнаружение отклонения",
    "verification": "Проверка результата и последствий",
    "alarm_handling": "Работа с тревогами",
}

# Ниже этого балла навык считается слабым и попадает в рекомендацию.
WEAK_SKILL_THRESHOLD = float(os.getenv("ML_WEAK_SKILL_THRESHOLD", "70"))

# Границы «хорошо / плохо» для навыков со временем. Время сравнивается не с абсолютной
# секундой, а с дедлайном реакции своего уровня: на третьем уровне он вдвое строже.
DETECTION_GOOD_RATIO = 0.5  # уложился в половину дедлайна — 100 баллов
DETECTION_BAD_RATIO = 1.5  # втрое дольше хорошего — 0 баллов
CORRECTION_GOOD_RATIO = 1.0
CORRECTION_BAD_RATIO = 3.0
ALARM_ACK_GOOD_MS = 30_000
ALARM_ACK_BAD_MS = 120_000

# Диагноз: попытка разобраться ценнее бездействия, но неверный вывод — не навык.
DIAGNOSIS_WRONG_SCORE = 25.0

# Проверка результата: сначала свой контур, потом семь участков ниже по цепочке.
VERIFY_FLOW_WEIGHT = 30.0
DOWNSTREAM_WEIGHT = 70.0

# Штрафы безопасности — копия политики оценки бэкенда (seed/scoring.py).
# Одинаковые числа означают, что тренажёр и ML одинаково понимают «опасно».
SAFETY_PENALTIES: dict[str, float] = {
    "dangerous_action": 25.0,
    "missed_alarm": 10.0,
    "out_of_sequence_action": 5.0,
    "repeated_action": 2.0,
}

# --- Допустимые значения ручек сценария -----------------------------------
# Копия allowlist из backend/app/infrastructure/seed/scenario.py.
# Рекомендация — это выбор значений из этих списков, ничего нового ML не выдумывает.

LEVELS: tuple[int, ...] = (1, 2, 3)
DISTURBANCE_CAUSES: tuple[str, ...] = ("feed_pump_capacity_loss", "flow_control_valve_stiction")
TARGET_BRANCHES: tuple[int, ...] = (1, 2, 3)

# Семь обязательных проверок последствий после корректирующего действия.
DOWNSTREAM_CHECKS: tuple[str, ...] = (
    "verify_t11",
    "verify_elou",
    "verify_e15",
    "verify_k1",
    "verify_furnaces",
    "verify_k2",
    "verify_products",
)

# Эталонная последовательность оператора (§10.1 ТЗ). Фокус рекомендации — подмножество.
EXPECTED_STEPS: tuple[str, ...] = (
    "declare_deviation",
    "compare_flows",
    "inspect_pressure",
    "inspect_pump",
    "submit_diagnosis",
    "corrective_action",
    "verify_flow",
    *DOWNSTREAM_CHECKS,
)


@dataclass(frozen=True, slots=True)
class LevelKnobs:
    """Ручки уровня сложности. Имена совпадают с `LevelSpec` бэкенда."""

    sensor_delay_ms: int
    nuisance_alarm_rate: float
    reaction_deadline_ms: int
    development_speed_factor: float
    hints_enabled: bool
    standby_pump_start_delay_ms: int


# Базовые уровни бэкенда (seed/scenario.py, LEVELS). Профильный сценарий строится
# как «базовый уровень + точечные правки под слабый навык».
BASE_LEVELS: dict[int, LevelKnobs] = {
    1: LevelKnobs(0, 0.4, 120_000, 0.80, True, 0),
    2: LevelKnobs(2_500, 2.0, 90_000, 1.00, True, 30_000),
    3: LevelKnobs(6_000, 4.5, 60_000, 1.60, False, 60_000),
}


@dataclass(frozen=True, slots=True)
class TrainingRecipe:
    """Как тренировать конкретный слабый навык.

    `level_shift` — сдвиг уровня относительно последнего пройденного.
    `cause` — `same` повторить ту же первопричину, `other` дать вторую.
    `knobs` — точечные правки ручек базового уровня.
    """

    goal: str
    level_shift: int
    cause: str
    knobs: dict[str, float | int | bool]
    focus_steps: tuple[str, ...]


# Ядро методики: слабый навык → чем именно его отрабатывать.
# Одна таблица вместо разбросанных условий, поэтому правило видно целиком.
TRAINING_RECIPES: dict[str, TrainingRecipe] = {
    # Опасное действие — единственный случай, когда сложность снижают: сначала
    # безопасная последовательность, потом скорость.
    "safety": TrainingRecipe(
        goal=(
            "Отработать безопасную последовательность: сначала восстановить расход, "
            "а не компенсировать симптом теплом"
        ),
        level_shift=-1,
        cause="same",
        knobs={"nuisance_alarm_rate": 0.4, "reaction_deadline_ms": 150_000, "hints_enabled": True},
        focus_steps=("submit_diagnosis", "corrective_action", "verify_flow"),
    ),
    # Причина найдена, но действие не доведено: повторяем ту же причину с подсказками.
    "correction": TrainingRecipe(
        goal="Довести корректирующее действие до результата на знакомой первопричине",
        level_shift=0,
        cause="same",
        knobs={"hints_enabled": True, "reaction_deadline_ms": 120_000, "standby_pump_start_delay_ms": 0},
        focus_steps=("corrective_action", "verify_flow"),
    ),
    # Диагноз путается — даём вторую первопричину: у неё другой наблюдаемый признак,
    # и оператор учится их различать, а не запоминать один ответ.
    "diagnosis": TrainingRecipe(
        goal=(
            "Научиться различать первопричины по признакам: падение давления насоса "
            "против расхождения команды и фактического положения регулятора"
        ),
        level_shift=0,
        cause="other",
        knobs={"nuisance_alarm_rate": 1.0, "hints_enabled": False},
        focus_steps=("compare_flows", "inspect_pressure", "inspect_pump", "submit_diagnosis"),
    ),
    # Отклонение замечено поздно: замедляем развитие и убираем шум, чтобы тренировать
    # именно наблюдение, а не скорость рук.
    "detection": TrainingRecipe(
        goal="Замечать раннее отклонение расхода до эскалации тревог",
        level_shift=0,
        cause="same",
        knobs={"development_speed_factor": 0.6, "nuisance_alarm_rate": 0.4, "sensor_delay_ms": 0},
        focus_steps=("declare_deviation", "compare_flows"),
    ),
    # Исправил и не посмотрел, что стало дальше по цепочке: акцент на семи проверках.
    "verification": TrainingRecipe(
        goal="Проследить последствия по всей цепочке установки после корректирующего действия",
        level_shift=0,
        cause="same",
        knobs={"nuisance_alarm_rate": 0.4, "hints_enabled": False},
        focus_steps=("verify_flow", *DOWNSTREAM_CHECKS),
    ),
    # Тонет в потоке тревог: сознательно поднимаем шум на том же уровне сложности.
    "alarm_handling": TrainingRecipe(
        goal="Сохранять последовательность действий при потоке второстепенных тревог",
        level_shift=0,
        cause="same",
        knobs={"nuisance_alarm_rate": 4.5},
        focus_steps=("declare_deviation", "submit_diagnosis", "corrective_action"),
    ),
}


@dataclass(frozen=True, slots=True)
class MiningThresholds:
    """Когда систематическая проблема считается поводом для нового сценария."""

    # Ниже какой доли успешных прохождений шаг считается проблемным.
    min_step_completion_rate: float = 0.6
    # Какая доля операторов должна иметь навык слабым.
    min_weak_share: float = 0.4
    # Меньше этого числа сессий выводы не делаем: статистики нет.
    min_sessions: int = 10


MINING = MiningThresholds()

# Поля, которые ML не имеет права читать: скрытое состояние сценария и разметка
# будущего из корпуса. Список используется как явная проверка в data.py.
FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "hidden_runtime_config_json",
        "internal_state_json",
        "disturbance_active_true",
        "disturbance_severity_true",
        "time_to_critical_event_s",
        "target_event_type",
        "risk_next_30s",
    }
)

# Служебные поля корпуса: показываются эксперту при разборе завершённой сессии,
# но в расчёт навыков не попадают (см. data.py).
AUDIT_ONLY_FIELDS: frozenset[str] = frozenset(
    {"operator_profile", "disturbance_cause", "disturbance_target_branch"}
)
