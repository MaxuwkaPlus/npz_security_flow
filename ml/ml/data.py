"""Единый вход в данные: корпус и живая база тренажёра приводятся к одним фактам.

Источника два и они разные по формату:

* `data/elou_avt_risk_next_30s/sample/*.csv` — синтетический корпус из 36 прохождений
  с шестью профилями поведения. На нём калибруются пороги и проверяются правила.
* `backend/var/npz_security_flow.db` — боевая база тренажёра. Открывается строго
  read-only: ML читает журнал, но никогда не пишет в базу тренажёра.

Оба источника превращаются в один `SessionFacts`, поэтому остальные модули не знают,
откуда пришли данные, и одинаково работают и на корпусе, и на живой сессии.

Важное ограничение: сюда не попадают скрытые поля сценария (`hidden_runtime_config_json`,
`internal_state_json`) и разметка будущего из корпуса. Первопричина не берётся из
скрытого состояния — она выводится из журнала диагнозов оператора (см. `_infer_cause`).
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ml import config

# Действия, которыми устраняется первопричина (backend: CONTROL_ACTIONS + STAGE_CHECKS).
CORRECTIVE_ACTION_TYPES = ("switch_to_standby_pump", "restore_flow_control")

# Все прохождения корпуса длятся один и тот же сеанс (manifest.json).
CORPUS_SESSION_DURATION_MS = 3_900_000

# Оператор называет причину коротким кодом, сценарий хранит полный код возмущения.
CAUSE_BY_DIAGNOSIS = {
    "pump_capacity_loss": "feed_pump_capacity_loss",
    "valve_stiction": "flow_control_valve_stiction",
}

# Какой участок закрывает какую downstream-проверку (backend: STAGE_CHECKS).
DOWNSTREAM_TARGETS = {
    "T-1_T-11": "verify_t11",
    "ELOU": "verify_elou",
    "V-15": "verify_e15",
    "K-1": "verify_k1",
    "FURNACES": "verify_furnaces",
    "K-2": "verify_k2",
    "PRODUCTS": "verify_products",
}


@dataclass(frozen=True, slots=True)
class SessionFacts:
    """Факты одного прохождения. Только то, что видит инструктор в журнале."""

    session_id: str
    operator_id: str
    source: str  # corpus | backend
    level_no: int
    status: str
    outcome: str | None
    sim_time_ms: int
    reaction_deadline_ms: int

    # Ход разбора отклонения: тревога → фиксация → диагноз → действие → проверка.
    first_alarm_ms: int | None = None
    declared_deviation_ms: int | None = None
    diagnosis_ms: int | None = None
    diagnosis_submitted: bool = False
    diagnosis_correct: bool = False
    correct_action_ms: int | None = None
    verify_flow_done: bool = False
    downstream_checks_done: int = 0

    # Тревоги: значимые и второстепенный шум считаются отдельно.
    alarms_total: int = 0
    alarms_unacknowledged: int = 0
    alarm_ack_delay_avg_ms: int | None = None
    nuisance_alarms_total: int = 0

    # Команды оператора.
    actions_total: int = 0
    dangerous_actions: int = 0
    repeated_actions: int = 0
    out_of_sequence_actions: int = 0
    critical_events: int = 0

    # Первопричина прошлого прохождения: нужна, чтобы дать другую в следующем.
    # Выведена из диагноза оператора, а не из скрытого состояния сценария.
    known_cause: str | None = None

    # Справочные поля для эксперта при разборе. В расчёт навыков не входят.
    audit: dict[str, Any] = field(default_factory=dict)

    @property
    def detection_time_ms(self) -> int | None:
        """Сколько прошло от первой видимой тревоги до фиксации отклонения."""

        if self.first_alarm_ms is None or self.declared_deviation_ms is None:
            return None
        return max(0, self.declared_deviation_ms - self.first_alarm_ms)

    @property
    def reaction_time_ms(self) -> int | None:
        """Сколько прошло от первой видимой тревоги до корректирующего действия."""

        if self.first_alarm_ms is None or self.correct_action_ms is None:
            return None
        return max(0, self.correct_action_ms - self.first_alarm_ms)

    @property
    def disturbance_happened(self) -> bool:
        """Возмущение дошло до оператора: без него навыки разбора не оцениваются."""

        return self.first_alarm_ms is not None


# --- Корпус ---------------------------------------------------------------


def load_corpus(corpus_dir: Path | None = None) -> list[SessionFacts]:
    """Читает корпус целиком. Одна строка `sessions.csv` — одно прохождение."""

    directory = corpus_dir or config.CORPUS_DIR
    sessions = pd.read_csv(directory / "sessions.csv")
    actions = pd.read_csv(directory / "actions.csv")
    alarms = pd.read_csv(directory / "alarms.csv")

    facts: list[SessionFacts] = []
    for row in sessions.to_dict("records"):
        session_id = str(row["session_id"])
        facts.append(
            _corpus_session(
                row,
                actions[actions["session_id"] == session_id],
                alarms[alarms["session_id"] == session_id],
            )
        )
    return facts


def _corpus_session(row: dict[str, Any], actions: pd.DataFrame, alarms: pd.DataFrame) -> SessionFacts:
    level_no = int(row["difficulty_level"])
    diagnosis_correct = bool(row["diagnosis_correct"])
    real_alarms = alarms[alarms["is_nuisance"] == 0]
    acknowledged = real_alarms.dropna(subset=["acknowledged_at_s"])

    return SessionFacts(
        session_id=str(row["session_id"]),
        # В корпусе один синтетический оператор на профиль поведения: так видно
        # динамику «профиль → его слабое место» по нескольким прохождениям.
        operator_id=str(row["operator_profile"]),
        source="corpus",
        level_no=level_no,
        status="completed",
        outcome=str(row["session_outcome"]),
        sim_time_ms=CORPUS_SESSION_DURATION_MS,
        reaction_deadline_ms=config.BASE_LEVELS[level_no].reaction_deadline_ms,
        first_alarm_ms=_seconds_to_ms(row.get("primary_alarm_at_s")),
        declared_deviation_ms=_seconds_to_ms(row.get("detection_at_s")),
        diagnosis_ms=_seconds_to_ms(row.get("diagnosis_at_s")),
        diagnosis_submitted=_seconds_to_ms(row.get("diagnosis_at_s")) is not None,
        diagnosis_correct=diagnosis_correct,
        correct_action_ms=_seconds_to_ms(row.get("correct_action_at_s")),
        verify_flow_done=bool((actions["action_type"] == "verify_flow").any()),
        downstream_checks_done=actions[actions["action_type"].isin(config.DOWNSTREAM_CHECKS)][
            "action_type"
        ].nunique(),
        alarms_total=len(real_alarms),
        alarms_unacknowledged=int(real_alarms["acknowledged_at_s"].isna().sum()),
        alarm_ack_delay_avg_ms=_mean_ms(acknowledged["acknowledged_at_s"] - acknowledged["started_at_s"]),
        nuisance_alarms_total=int((alarms["is_nuisance"] == 1).sum()),
        actions_total=len(actions),
        dangerous_actions=int((actions["classification"] == "dangerous").sum()),
        repeated_actions=int((actions["classification"] == "repeated").sum()),
        out_of_sequence_actions=int((actions["classification"] == "out_of_sequence").sum()),
        critical_events=int(row.get("critical_event_count") or 0),
        known_cause=_infer_cause(_corpus_diagnosis_code(actions), diagnosis_correct),
        audit={
            "operator_profile": row["operator_profile"],
            "disturbance_cause": row["disturbance_cause"],
            "disturbance_target_branch": int(row["disturbance_target_branch"]),
        },
    )


def _corpus_diagnosis_code(actions: pd.DataFrame) -> str | None:
    """В корпусе диагноз записан как `submit_diagnosis:<код причины>`."""

    submitted = actions[actions["action_type"].str.startswith("submit_diagnosis:")]
    if submitted.empty:
        return None
    return str(submitted.iloc[0]["action_type"]).split(":", 1)[1]


# --- Живая база тренажёра -------------------------------------------------


def load_backend_sessions(db_path: Path | None = None) -> list[SessionFacts]:
    """Все прохождения из базы тренажёра."""

    with closing(_read_only(db_path or config.BACKEND_DB)) as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM training_sessions ORDER BY created_at")]
        return [facts for facts in (_backend_session(conn, session_id) for session_id in ids) if facts]


def load_backend_session(session_id: str, db_path: Path | None = None) -> SessionFacts | None:
    """Одно прохождение: работает и на незавершённой сессии (рекомендация по ходу)."""

    with closing(_read_only(db_path or config.BACKEND_DB)) as conn:
        return _backend_session(conn, session_id)


def _read_only(db_path: Path) -> sqlite3.Connection:
    """База тренажёра открывается только на чтение: ML не может её испортить."""

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _backend_session(conn: sqlite3.Connection, session_id: str) -> SessionFacts | None:
    session = conn.execute(
        """
        SELECT s.id, s.operator_id, s.status, s.sim_time_ms, s.final_outcome,
               l.level_no, l.reaction_deadline_ms
        FROM training_sessions s
        JOIN scenario_levels l ON l.id = s.scenario_level_id
        WHERE s.id = ?
        """,
        (session_id,),
    ).fetchone()
    if session is None:
        return None

    actions = _rows(
        conn,
        """
        SELECT action_type, status, classification, sim_time_ms
        FROM operator_actions WHERE session_id = ? ORDER BY sim_time_ms
        """,
        session_id,
    )
    observations = _rows(
        conn,
        """
        SELECT observation_type, target_code, sim_time_ms
        FROM operator_observations WHERE session_id = ? ORDER BY sim_time_ms
        """,
        session_id,
    )
    alarms = _rows(
        conn,
        """
        SELECT alarm_code, level, is_nuisance, ack_required,
               started_sim_time_ms, acknowledged_sim_time_ms
        FROM session_alarms WHERE session_id = ? ORDER BY started_sim_time_ms
        """,
        session_id,
    )
    diagnoses = _rows(
        conn,
        """
        SELECT suspected_cause_code, is_correct, sim_time_ms
        FROM operator_diagnoses WHERE session_id = ? ORDER BY sim_time_ms
        """,
        session_id,
    )

    real_alarms = [alarm for alarm in alarms if not alarm["is_nuisance"]]
    ack_delays = [
        alarm["acknowledged_sim_time_ms"] - alarm["started_sim_time_ms"]
        for alarm in real_alarms
        if alarm["acknowledged_sim_time_ms"] is not None
    ]
    diagnosis = diagnoses[0] if diagnoses else None
    declared = _first_observation(observations, "declare_deviation")
    verified_targets = {
        obs["target_code"] for obs in observations if obs["observation_type"] == "verify_result"
    }

    return SessionFacts(
        session_id=session["id"],
        operator_id=session["operator_id"],
        source="backend",
        level_no=session["level_no"],
        status=session["status"],
        outcome=session["final_outcome"],
        sim_time_ms=session["sim_time_ms"],
        reaction_deadline_ms=session["reaction_deadline_ms"],
        first_alarm_ms=real_alarms[0]["started_sim_time_ms"] if real_alarms else None,
        declared_deviation_ms=declared,
        diagnosis_ms=diagnosis["sim_time_ms"] if diagnosis else None,
        diagnosis_submitted=diagnosis is not None,
        diagnosis_correct=bool(diagnosis["is_correct"]) if diagnosis else False,
        correct_action_ms=_correct_action_ms(actions),
        verify_flow_done="FEED-SYSTEM" in verified_targets,
        downstream_checks_done=len(verified_targets & set(DOWNSTREAM_TARGETS)),
        alarms_total=len(real_alarms),
        alarms_unacknowledged=sum(
            1 for alarm in real_alarms if alarm["ack_required"] and alarm["acknowledged_sim_time_ms"] is None
        ),
        alarm_ack_delay_avg_ms=int(sum(ack_delays) / len(ack_delays)) if ack_delays else None,
        nuisance_alarms_total=sum(1 for alarm in alarms if alarm["is_nuisance"]),
        actions_total=len(actions),
        dangerous_actions=_count_classification(actions, "dangerous"),
        repeated_actions=_count_classification(actions, "repeated"),
        out_of_sequence_actions=_count_classification(actions, "out_of_sequence"),
        # В журнале тренажёра критические события отдельно не хранятся: их роль
        # играют тревоги высшего уровня L5.
        critical_events=sum(1 for alarm in real_alarms if alarm["level"] == "L5"),
        known_cause=_infer_cause(
            diagnosis["suspected_cause_code"] if diagnosis else None,
            bool(diagnosis["is_correct"]) if diagnosis else False,
        ),
        audit={"status": session["status"]},
    )


def _rows(conn: sqlite3.Connection, sql: str, session_id: str) -> list[sqlite3.Row]:
    _assert_no_forbidden(sql)
    return conn.execute(sql, (session_id,)).fetchall()


def _assert_no_forbidden(sql: str) -> None:
    """Страховка инварианта: ML не читает скрытое состояние сценария.

    Проверка стоит на границе с базой, поэтому нарушение видно сразу при запросе,
    а не в виде подсказки, случайно попавшей оператору.
    """

    for forbidden in config.FORBIDDEN_FIELDS:
        if forbidden in sql:
            raise ValueError(f"Запрос обращается к скрытому полю сценария: {forbidden}")


def _first_observation(observations: list[sqlite3.Row], observation_type: str) -> int | None:
    for observation in observations:
        if observation["observation_type"] == observation_type:
            return int(observation["sim_time_ms"])
    return None


def _correct_action_ms(actions: list[sqlite3.Row]) -> int | None:
    """Первое принятое корректирующее действие.

    Классификацию бэкенд проставляет после окна наблюдения, поэтому у свежей
    команды она ещё пустая. Для рекомендации по ходу сессии этого ждать нельзя:
    считаем действие корректным, пока оценка не сказала обратного.
    """

    for action in actions:
        if action["action_type"] not in CORRECTIVE_ACTION_TYPES:
            continue
        if action["status"] not in ("accepted", "applied"):
            continue
        if action["classification"] in (None, "correct"):
            return int(action["sim_time_ms"])
    return None


def _count_classification(actions: list[sqlite3.Row], classification: str) -> int:
    return sum(1 for action in actions if action["classification"] == classification)


# --- Общее ----------------------------------------------------------------


def _infer_cause(suspected_cause_code: str | None, diagnosis_correct: bool) -> str | None:
    """Восстанавливает первопричину прошлого прохождения из диагноза оператора.

    Скрытое состояние сценария читать нельзя, но вывод возможен: причин ровно две.
    Верный диагноз называет её прямо, неверный — исключает названную. Если оператор
    назвал что-то за пределами двух причин, вывод не делаем.
    """

    code = CAUSE_BY_DIAGNOSIS.get(suspected_cause_code or "")
    if code is None:
        return None
    if diagnosis_correct:
        return code
    return next(cause for cause in config.DISTURBANCE_CAUSES if cause != code)


def _seconds_to_ms(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(float(value) * 1000)


def _mean_ms(seconds: "pd.Series[float]") -> int | None:
    if seconds.empty:
        return None
    return int(seconds.mean() * 1000)
