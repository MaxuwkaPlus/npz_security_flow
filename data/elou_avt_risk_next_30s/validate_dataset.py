#!/usr/bin/env python3
"""Validate the generated ELOU-AVT risk_next_30s corpus."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


BASE = Path(__file__).resolve().parent
SAMPLE = BASE / "sample"
HORIZON_S = 30
SESSION_END_S = 3900
STEP_S = 5


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def number(value: str) -> float | None:
    return None if value == "" else float(value)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    snapshot_header, snapshots = read_csv(SAMPLE / "snapshots.csv")
    _, sessions = read_csv(SAMPLE / "sessions.csv")
    _, actions = read_csv(SAMPLE / "actions.csv")
    _, alarms = read_csv(SAMPLE / "alarms.csv")
    _, events = read_csv(SAMPLE / "critical_events.csv")
    _, schema_rows = read_csv(BASE / "schema.csv")
    model_columns = json.loads((BASE / "model_columns.json").read_text(encoding="utf-8"))

    schema_names = [row["field_name"] for row in schema_rows]
    require(snapshot_header == schema_names, "snapshots.csv header does not match schema.csv order")
    require(len(schema_names) == len(set(schema_names)), "duplicate schema field names")
    require(len({row["snapshot_id"] for row in snapshots}) == len(snapshots), "snapshot_id is not unique")

    session_split = {row["session_id"]: row["split"] for row in sessions}
    require(set(session_split.values()) == {"train", "validation", "test"}, "all three splits are required")
    require(all(session_split[row["session_id"]] == row["split"] for row in snapshots), "session split leakage")

    rows_by_session: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in snapshots:
        rows_by_session[row["session_id"]].append(row)
    require(set(rows_by_session) == set(session_split), "session lists disagree")
    for session_id, rows in rows_by_session.items():
        times = [int(row["sim_time_s"]) for row in rows]
        require(times == list(range(0, SESSION_END_S + 1, STEP_S)), f"bad time grid in {session_id}")

    events_by_session: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for event in events:
        events_by_session[event["session_id"]].append((int(event["sim_time_s"]), event["event_type"]))
    for session_id in events_by_session:
        events_by_session[session_id].sort()

    label_counts = Counter()
    positive_by_split = Counter()
    invalid_rows = 0
    for row in snapshots:
        t = int(row["sim_time_s"])
        valid_expected = int(t + HORIZON_S <= SESSION_END_S)
        require(int(row["label_valid"]) == valid_expected, f"label_valid mismatch at {row['snapshot_id']}")
        future = [(event_t, event_type) for event_t, event_type in events_by_session[row["session_id"]] if t < event_t <= t + HORIZON_S]
        if not valid_expected:
            invalid_rows += 1
            require(row["risk_next_30s"] == "", f"right-censored row has target at {row['snapshot_id']}")
            require(row["time_to_critical_event_s"] == "" and row["target_event_type"] == "", "right-censored label metadata must be blank")
            continue
        expected_target = int(bool(future))
        require(int(row["risk_next_30s"]) == expected_target, f"target mismatch at {row['snapshot_id']}")
        label_counts[str(expected_target)] += 1
        if expected_target:
            positive_by_split[row["split"]] += 1
            nearest_t, nearest_type = min(future)
            require(float(row["time_to_critical_event_s"]) == nearest_t - t, f"time-to-event mismatch at {row['snapshot_id']}")
            require(row["target_event_type"] == nearest_type, f"event type mismatch at {row['snapshot_id']}")
        else:
            require(row["time_to_critical_event_s"] == "" and row["target_event_type"] == "", "negative row has label metadata")

        flows = [float(row[f"branch_{branch}_flow_tph"]) for branch in (1, 2, 3)]
        ratios = [float(row[f"branch_{branch}_flow_ratio"]) for branch in (1, 2, 3)]
        require(all(abs(flow / 100.0 - ratio) < 0.0002 for flow, ratio in zip(flows, ratios)), f"flow ratio formula mismatch at {row['snapshot_id']}")
        require(abs(sum(flows) - float(row["total_feed_flow_tph"])) < 0.001, f"total flow mismatch at {row['snapshot_id']}")
        expected_margin = (140.0 - max(float(row[f"branch_{branch}_t11_outlet_temp_c"]) for branch in (1, 2, 3))) / 15.0
        require(abs(expected_margin - float(row["t11_temperature_margin_norm"])) < 0.001, f"temperature margin mismatch at {row['snapshot_id']}")

    require(set(positive_by_split) == {"train", "validation", "test"}, "positive target must occur in every split")
    require(label_counts["1"] > 0 and label_counts["0"] > label_counts["1"], "target distribution is invalid")

    all_model_fields = set(model_columns["continuous"] + model_columns["count"] + model_columns["binary"] + model_columns["categorical"])
    require(all_model_fields <= set(schema_names), "model_columns.json contains unknown columns")
    forbidden = {
        "operator_profile", "disturbance_cause", "disturbance_target_branch", "disturbance_onset_s",
        "disturbance_active_true", "disturbance_severity_true", "time_to_critical_event_s", "target_event_type",
    }
    require(not (all_model_fields & forbidden), "future/latent leakage column included in X")
    require(forbidden <= set(model_columns["excluded"]), "leakage fields are not explicitly excluded")

    variability_fields = [
        "reaction_overdue_s", "unack_alarms_count", "repeated_actions_30s", "cancelled_actions_30s",
        "sequence_violations_30s", "verification_missing", "result_checks_30s", "deviating_parameters_count",
        "flow_imbalance_ratio", "elou_load_imbalance_ratio", "k1_feed_flow_ratio", "k2_stability_index",
    ]
    variability: dict[str, dict[str, float | int]] = {}
    for field_name in variability_fields:
        values = [float(row[field_name]) for row in snapshots if row[field_name] != ""]
        require(len(set(values)) > 1, f"important feature is constant: {field_name}")
        require(any(value > 0 for value in values), f"important feature has no positive values: {field_name}")
        variability[field_name] = {"min": min(values), "max": max(values), "nonzero": sum(value != 0 for value in values), "unique": len(set(values))}

    action_class_counts = Counter(row["classification"] for row in actions)
    for required_class in ("correct", "incorrect", "dangerous", "repeated", "cancelled", "out_of_sequence"):
        require(action_class_counts[required_class] > 0, f"missing action class: {required_class}")

    event_counts = Counter(row["event_type"] for row in events)
    for required_event in (
        "severe_flow_imbalance", "t11_branch_overtemperature", "elou_critical_load_imbalance",
        "k1_critical_feed_deviation", "k2_critical_instability", "dangerous_heat_compensation",
    ):
        require(event_counts[required_event] > 0, f"missing critical event type: {required_event}")

    for row in snapshots:
        for column in model_columns["continuous"] + model_columns["count"]:
            if row[column] == "":
                continue
            require(math.isfinite(float(row[column])), f"non-finite value in {column} at {row['snapshot_id']}")

    valid_total = label_counts["0"] + label_counts["1"]
    report = {
        "status": "ok", "session_count": len(sessions), "snapshot_count": len(snapshots), "valid_snapshot_count": valid_total,
        "invalid_right_censored_rows": invalid_rows, "target_counts": dict(label_counts),
        "positive_rate": round(label_counts["1"] / valid_total, 6), "positive_rows_by_split": dict(positive_by_split),
        "action_class_counts": dict(action_class_counts), "critical_event_counts": dict(event_counts),
        "alarm_record_count": len(alarms), "important_feature_variability": variability,
        "session_split_isolation": True, "normalization_formula_checks": "passed", "target_horizon_checks": "passed",
        "leakage_column_checks": "passed", "time_grid_checks": "passed",
    }
    (SAMPLE / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
