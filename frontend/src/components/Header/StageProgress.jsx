import { stageTitle } from "../../utils/helpers.js";

export function StageProgress({ scenario, currentStageCode, snapshotStageCode }) {
  const stageIndex = scenario?.stages.findIndex(
    (stage) => stage.code === currentStageCode,
  );
  const stageCount = scenario?.stages.length || 1;
  const progress = Math.max(4, ((stageIndex + 1) / stageCount) * 100);

  return (
    <section className="stagebar">
      <span>
        Этап {stageIndex + 1} / {scenario?.stages.length}
      </span>
      <b>{stageTitle(snapshotStageCode || currentStageCode)}</b>
      <div className="progress">
        <i style={{ width: `${progress}%` }} />
      </div>
    </section>
  );
}
