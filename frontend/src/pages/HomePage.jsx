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

export function HomePage({ training }) {
  const stage = training.snapshot.stage_code || training.session.current_stage_code;
  const values = { ...training.snapshot.values, ...training.snapshot.derived };

  return (
    <main className="app-shell">
      <AppHeader session={training.session} wsStatus={training.wsStatus} />
      <StageProgress
        scenario={training.scenario}
        currentStageCode={training.session.current_stage_code}
        snapshotStageCode={training.snapshot.stage_code}
      />
      <div className="console-grid">
        <aside className="left-column">
          <SessionControls
            session={training.session}
            onLifecycle={training.changeLifecycle}
            onReport={training.openReport}
          />
          <AlarmPanel
            alarms={training.alarms}
            enabled={training.isControlEnabled}
            onAcknowledge={training.acknowledgeAlarm}
          />
        </aside>
        <section className="process-area">
          <ProcessMap topology={training.topology} stage={stage} />
          <Metrics values={values} topology={training.topology} />
          <ActionPanel
            enabled={training.isControlEnabled}
            onAction={training.submitAction}
            onObserve={training.recordObservation}
          />
        </section>
        <aside className="right-column">
          <CommandLog actions={training.actionLog} onCancel={training.cancelAction} />
          <Instruction stage={stage} />
        </aside>
      </div>
      <DiagnosisModal
        isOpen={training.isDiagnosisOpen}
        onClose={() => training.setDiagnosisOpen(false)}
        onSubmit={training.submitDiagnosis}
      />
      <SagatModal
        checkpoint={training.sagatCheckpoint}
        onSubmit={training.submitSagat}
      />
      <TlxModal isOpen={training.isTlxOpen} onSubmit={training.submitNasaTlx} />
      <Toast notification={training.notification} />
    </main>
  );
}
