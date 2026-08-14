export const QUICK_ACTIONS = [
  ["start_feed_pump", "N-1", "Пустить Н-1"],
  ["start_feed_pump", "N-1A", "Пустить Н-1А"],
  ["switch_to_standby_pump", "N-1A", "Резервный Н-1А"],
  ["restore_flow_control", "FRC-404", "Восст. FRC-404"],
  ["restore_flow_control", "FRC-405", "Восст. FRC-405"],
  ["restore_flow_control", "FRC-406", "Восст. FRC-406"],
  ["start_transfer_pump", "N-20", "Пустить Н-20"],
];

export const OBSERVATIONS = [
  ["inspect_equipment", "FEED-SYSTEM", "Осмотреть подачу"],
  ["inspect_equipment", "T-1_T-11", "Осмотреть Т-1…Т-11"],
  ["inspect_equipment", "ELOU", "Осмотреть ЭЛОУ"],
  ["inspect_equipment", "K-2", "Осмотреть К-2"],
  ["declare_deviation", "FEED-SYSTEM", "Зафиксировать отклонение"],
  ["compare_flows", "FEED-SYSTEM", "Сравнить расходы"],
  ["inspect_pressure", "FEED-SYSTEM", "Проверить давление"],
  ["inspect_equipment", "N-1", "Осмотреть насос"],
  ["verify_result", "FEED-SYSTEM", "Подтвердить расход"],
  ["verify_result", "T-1_T-11", "Проверить Т-1…Т-11"],
  ["verify_result", "ELOU", "Проверить ЭЛОУ"],
  ["verify_result", "V-15", "Проверить Е-15"],
  ["verify_result", "K-1", "Проверить К-1"],
  ["verify_result", "FURNACES", "Проверить печи"],
  ["verify_result", "K-2", "Проверить К-2"],
  ["verify_result", "PRODUCTS", "Проверить продукты"],
];

export const TLX_SCALES = [
  ["mental_demand", "Ментальная нагрузка"],
  ["physical_demand", "Физическая нагрузка"],
  ["temporal_demand", "Дефицит времени"],
  ["performance", "Удовлетворённость работой"],
  ["effort", "Усилия"],
  ["frustration", "Фрустрация"],
];

export const STAGE_LABELS = {
  precheck: "Предпусковой осмотр",
  feed_preparation: "Подготовка подачи",
  feed_startup: "Пуск сырья",
  t1_t3: "Т-1…Т-3",
  t4_t7: "Т-4…Т-7",
  t7_t11: "Т-7…Т-11",
  elou_feed_and_water: "ЭЛОУ и вода",
  elou_stage_1: "ЭЛОУ, ступень 1",
  elou_stage_2: "ЭЛОУ, ступень 2",
  e15: "Е-15",
  post_elou_heating: "Т-17…Т-27",
  k1: "Колонна К-1",
  furnaces: "Печи",
  k2: "Колонна К-2",
  side_draws_and_products: "Продукты",
  stable_mode: "Устойчивый режим",
  disturbance_monitoring: "Контроль отклонения",
  diagnosis_and_correction: "Диагностика и коррекция",
  recovery: "Восстановление",
  final_stabilization: "Финальная стабилизация",
};

export const SESSION_STATUS_LABELS = {
  ready: "готова",
  running: "идёт",
  paused: "пауза",
  completed: "завершена",
  failed: "завершена",
  aborted: "прервана",
};

export const PROCESS_GROUPS = [
  ["Подача", "N-1 · FRC-404/405/406"],
  ["Теплообмен", "Т-1…Т-11"],
  ["ЭЛОУ", "А-19 · Э-1…Э-6"],
  ["Подготовка", "Е-15 · Н-20"],
  ["Ректификация", "К-1 · печи · К-2"],
  ["Продукты", "Боковые отборы"],
];

export const TERMINAL_SESSION_STATUSES = ["completed", "failed", "aborted"];
