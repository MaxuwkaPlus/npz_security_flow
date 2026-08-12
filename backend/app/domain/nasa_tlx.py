"""Raw NASA-TLX (§16.8 технического задания).

Шесть шкал 0…10 приводятся к одному направлению и усредняются. Показатель хранится
отдельно и никогда не снижает квалификационную оценку оператора.
"""

from collections.abc import Mapping
from dataclasses import dataclass

SCALE_MIN = 0.0
SCALE_MAX = 10.0

# По шкале успешности «0» означает лучший результат, поэтому она инвертируется.
INVERTED_SCALES = frozenset({"performance"})
SCALES = ("mental_demand", "physical_demand", "temporal_demand", "performance", "effort", "frustration")


@dataclass(frozen=True, slots=True)
class TlxResponse:
    values: Mapping[str, float]

    def raw_score(self) -> float:
        aligned = [
            SCALE_MAX - self.values[scale] if scale in INVERTED_SCALES else self.values[scale]
            for scale in SCALES
        ]
        return round(sum(aligned) / len(SCALES), 2)


def validate(values: Mapping[str, float]) -> str | None:
    """Сообщение об ошибке или None, если анкета заполнена корректно."""

    missing = [scale for scale in SCALES if scale not in values]
    if missing:
        return f"Не заполнены шкалы: {', '.join(missing)}"
    out_of_range = [scale for scale in SCALES if not SCALE_MIN <= values[scale] <= SCALE_MAX]
    if out_of_range:
        return f"Значения вне диапазона 0…10: {', '.join(out_of_range)}"
    return None
