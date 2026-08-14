import { useCallback, useEffect, useState } from "react";
import { api } from "../services/api.js";
import { apiErrorMessage, rejectionMessage, stageTitle } from "../utils/helpers.js";
import { useSessionSocket } from "./useSessionSocket.js";

const EMPTY_SNAPSHOT = { values: {}, derived: {} };

export function useTrainingSession() {
  const [screen, setScreen] = useState("start");
  const [scenarios, setScenarios] = useState([]);
  const [scenario, setScenario] = useState(null);
  const [session, setSession] = useState(null);
  const [topology, setTopology] = useState(null);
  const [snapshot, setSnapshot] = useState(EMPTY_SNAPSHOT);
  const [alarms, setAlarms] = useState([]);
  const [actionLog, setActionLog] = useState([]);
  const [wsStatus, setWsStatus] = useState("offline");
  const [notification, setNotification] = useState(null);
  const [sagatCheckpoint, setSagatCheckpoint] = useState(null);
  const [isDiagnosisOpen, setDiagnosisOpen] = useState(false);
  const [isTlxOpen, setTlxOpen] = useState(false);

  const notify = useCallback((text, kind = "info") => {
    setNotification({ text, kind });
    setTimeout(() => setNotification(null), 4200);
  }, []);

  useEffect(() => {
    api.scenarios().then(setScenarios).catch((error) => {
      notify(apiErrorMessage(error), "error");
    });
  }, [notify]);

  const refreshSessionState = useCallback(async () => {
    if (!session?.id) return;

    try {
      const [nextSession, activeAlarms] = await Promise.all([
        api.state(session.id),
        api.alarms(session.id),
      ]);
      setSession(nextSession);
      setAlarms(activeAlarms);
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  }, [notify, session?.id]);

  const receiveRealtimeMessage = useCallback(
    (message) => {
      const payload = message.payload || {};

      if (message.type === "process_snapshot") {
        setSnapshot({
          values: payload.values || {},
          derived: payload.derived || {},
          stage_code: payload.stage_code,
        });
      }

      if (message.type === "session_state") {
        setSession((current) =>
          current
            ? { ...current, ...payload, sim_time_ms: message.sim_time_ms }
            : current,
        );
      }

      if (message.type === "stage_changed") {
        const stageCode = payload.stage_code || payload.to_stage_code;
        setSession((current) =>
          current
            ? { ...current, current_stage_code: stageCode || current.current_stage_code }
            : current,
        );
        notify(`Этап: ${stageTitle(stageCode)}`);
      }

      if (["alarm_raised", "alarm_updated"].includes(message.type)) {
        refreshSessionState();
      }

      if (message.type === "action_status_changed") {
        const actionId = payload.action_id || payload.id;
        setActionLog((current) =>
          [
            {
              ...payload,
              id: actionId,
              status: payload.status,
              sequence_no: message.sequence_no,
            },
            ...current.filter((action) => action.id !== actionId),
          ].slice(0, 12),
        );
      }

      if (
        message.type === "session_event" &&
        payload.event_type === "sagat_requested"
      ) {
        api.currentSagat(message.session_id).then(setSagatCheckpoint).catch(() => {});
      }

      if (message.type === "session_completed") {
        setSession((current) =>
          current
            ? { ...current, status: "completed", sim_time_ms: message.sim_time_ms }
            : current,
        );
        setTlxOpen(true);
      }
    },
    [notify, refreshSessionState],
  );

  useSessionSocket(session?.id, receiveRealtimeMessage, setWsStatus);

  const startSession = async ({ operatorId, scenarioId, levelNo }) => {
    try {
      const selectedScenario = await api.scenario(scenarioId);
      const createdSession = await api.createSession({
        operator_id: operatorId,
        scenario_version_id: scenarioId,
        level_no: levelNo,
      });

      setScenario(selectedScenario);
      setSession(createdSession);
      setTopology(await api.topology(selectedScenario.installation_version_id));
      setScreen("console");
      notify("Сессия создана. Запустите симуляцию.");
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  const changeLifecycle = async (command) => {
    try {
      setSession(await api.lifecycle(session.id, command));
    } catch (error) {
      notify(apiErrorMessage(error), "error");
      refreshSessionState();
    }
  };

  const submitAction = async (actionType, targetCode, value = {}) => {
    try {
      const receipt = await api.action(session.id, {
        action_type: actionType,
        target_code: targetCode,
        value,
        client_sim_time_ms: session.sim_time_ms,
      });
      setActionLog((current) => [receipt, ...current].slice(0, 12));

      if (receipt.status === "rejected") {
        notify(rejectionMessage(receipt.rejection_reason), "warning");
      }
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  const recordObservation = async (observationType, targetCode) => {
    try {
      await api.observe(session.id, {
        observation_type: observationType,
        target_code: targetCode,
      });
      if (observationType === "declare_deviation") setDiagnosisOpen(true);
      notify("Наблюдение внесено в журнал.");
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  const submitDiagnosis = async (diagnosis) => {
    try {
      await api.diagnose(session.id, diagnosis);
      setDiagnosisOpen(false);
      notify("Диагноз зафиксирован. Оценка будет в итоговом отчёте.");
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  const submitSagat = async (answers) => {
    try {
      await api.submitSagat(session.id, sagatCheckpoint.id, answers);
      setSagatCheckpoint(null);
      notify("Ответы SAGAT приняты.");
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  const acknowledgeAlarm = async (alarmId) => {
    try {
      await api.acknowledge(session.id, alarmId);
      refreshSessionState();
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  const cancelAction = async (action) => {
    try {
      await api.cancelAction(session.id, action.id);
      notify("Команда отозвана.");
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  const openReport = () => {
    setScreen("report");
  };

  const submitNasaTlx = async (values) => {
    try {
      await api.nasaTlx(session.id, values);
      setTlxOpen(false);
      setScreen("report");
    } catch (error) {
      notify(apiErrorMessage(error), "error");
    }
  };

  return {
    actionLog,
    alarms,
    acknowledgeAlarm,
    cancelAction,
    changeLifecycle,
    isControlEnabled: session?.status === "running",
    isDiagnosisOpen,
    isTlxOpen,
    notification,
    openReport,
    recordObservation,
    refreshSessionState,
    sagatCheckpoint,
    scenario,
    screen,
    session,
    setDiagnosisOpen,
    setScreen,
    snapshot,
    startSession,
    submitAction,
    submitDiagnosis,
    submitNasaTlx,
    submitSagat,
    topology,
    wsStatus,
    scenarios,
  };
}
