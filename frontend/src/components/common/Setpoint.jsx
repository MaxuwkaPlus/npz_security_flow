export function Setpoint({
  label,
  value,
  setValue,
  min,
  max,
  step,
  unit,
  onApply,
  enabled,
}) {
  return (
    <label className="setpoint">
      <span>{label}</span>
      <div>
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step || 1}
          onChange={(event) => setValue(event.target.value)}
        />
        <em>{unit}</em>
        <button disabled={!enabled} onClick={onApply} type="button">
          Задать
        </button>
      </div>
    </label>
  );
}
