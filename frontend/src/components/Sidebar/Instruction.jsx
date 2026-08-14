import { stageTitle } from "../../utils/helpers.js";

const instructions = {
  disturbance_monitoring:
    "Контролируйте тенденции расхода. Зафиксируйте отклонение и выполните осмотры.",
  final_stabilization:
    "Подтвердите последствия по всем downstream-участкам.",
};

export function Instruction({ stage }) {
  return (
    <section className="instruction">
      <span>ТЕКУЩАЯ ЗАДАЧА</span>
      <b>{stageTitle(stage)}</b>
      <p>
        {instructions[stage] ||
          "Выполняйте этап последовательно и фиксируйте обязательные осмотры."}
      </p>
    </section>
  );
}
