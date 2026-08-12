"""Элементарная динамика упрощённой модели."""


def approach(current: float, target: float, dt_ms: int, time_constant_ms: int) -> float:
    """Апериодическое звено первого порядка: изменение растянуто во времени."""

    if time_constant_ms <= 0:
        return target
    return current + (target - current) * min(1.0, dt_ms / time_constant_ms)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
