import { ActionPanel } from "../components/Dashboard/ActionPanel.jsx";
import { Metrics } from "../components/Dashboard/Metrics.jsx";
import { ProcessMap } from "../components/Dashboard/ProcessMap.jsx";
import { AppHeader } from "../components/Header/AppHeader.jsx";
import { StageProgress } from "../components/Header/StageProgress.jsx";
import { DiagnosisModal } from "../components/Modals/DiagnosisModal.jsx";
import { SagatModal } from "../components/Modals/SagatModal.jsx";
import { TlxModal } from "../components/Modals/TlxModal.jsx";
import { AlarmPanel } from "../components/Sidebar/AlarmPanel.jsx";
import { CommandLog } from "../components/Sidebar/CommandLog.jsx";
import { Instruction } from "../components/Sidebar/Instruction.jsx";
import { SessionControls } from "../components/Sidebar/SessionControls.jsx";
import { Toast } from "../components/common/Toast.jsx";

export function HomePage({ auth, training }) {
  // Инструктор наблюдает за прохождением, но не подаёт команды вместо оператора:
  // иначе журнал перестал бы отвечать, чей навык проверяется.
  const canOperate =
    auth.can("session.operate") && auth.user.username === training.session.operator_id;
  // Ход прохождения ведёт инструктор. Если инструктора нет — обучаемый ведёт своё
  // сам, и только своё: право на это отдельное и сверяется с владельцем сессии.
  const canControl =
    auth.can("session.control") || (auth.can("session.control_own") && canOperate);
  const stage = training.snapshot.stage_code || training.session.current_stage_code;
  const values = { ...training.snapshot.values, ...training.snapshot.derived };

  return (
    <main className="app-shell">
      <AppHeader
        auth={auth}
        session={training.session}
        wsStatus={training.wsStatus}
        onExpert={() => training.setScreen("expert")}
        onLeave={training.leaveSession}
      />
      <StageProgress
        scenario={training.scenario}
        currentStageCode={training.session.current_stage_code}
        snapshotStageCode={training.snapshot.stage_code}
      />
      <div className="console-grid">
        <aside className="left-column">
          <SessionControls
            session={training.session}
            canControl={canControl}
            canReadReport={
              auth.can("report.read_any") ||
              (auth.can("report.read_own") && canOperate)
            }
            onLifecycle={training.changeLifecycle}
            onReport={training.openReport}
          />
          <AlarmPanel
            alarms={training.alarms}
            enabled={training.isControlEnabled && canOperate}
            onAcknowledge={training.acknowledgeAlarm}
          />
        </aside>
        <section className="process-area">
          <ProcessMap topology={training.topology} stage={stage} />
          <Metrics values={values} topology={training.topology} />
          <ActionPanel
            enabled={training.isControlEnabled && canOperate}
            onAction={training.submitAction}
            onObserve={training.recordObservation}
          />
        </section>
        <aside className="right-column">
          <CommandLog
            actions={training.actionLog}
            onCancel={canOperate ? training.cancelAction : null}
          />
          <Instruction stage={stage} />
        </aside>
      </div>
      <DiagnosisModal
        isOpen={canOperate && training.isDiagnosisOpen}
        onClose={() => training.setDiagnosisOpen(false)}
        onSubmit={training.submitDiagnosis}
      />
      <SagatModal
        checkpoint={canOperate ? training.sagatCheckpoint : null}
        onSubmit={training.submitSagat}
      />
      <TlxModal isOpen={canOperate && training.isTlxOpen} onSubmit={training.submitNasaTlx} />
      <Toast notification={training.notification} />
    </main>
  );
}
