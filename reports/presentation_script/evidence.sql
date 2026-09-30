-- Reviewed timing rows for the 3:58 presentation script.
-- The six blocks are non-overlapping and sum to 238 seconds.
WITH duration_allocation(block_order, segment, duration_seconds, purpose) AS (
  VALUES
    (1, 'Титул и проблема', 32, 'Представить команду, проблему и решение'),
    (2, 'Пуск установки', 53, 'Показать сквозное прохождение и динамику'),
    (3, 'Возмущение и диагностика', 70, 'Показать главный учебный конфликт'),
    (4, 'Проверка последствий', 25, 'Доказать downstream-контроль'),
    (5, 'Отчёт и эксперт', 50, 'Показать объяснимую оценку и следующий цикл'),
    (6, 'Финал', 8, 'Закрепить ценность одной фразой')
)
SELECT
  block_order AS "order",
  segment,
  duration_seconds,
  ROUND(duration_seconds * 100.0 / 238.0, 1) AS share_pct,
  purpose
FROM duration_allocation
ORDER BY block_order;
