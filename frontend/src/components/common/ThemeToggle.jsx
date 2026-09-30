import { useTheme } from "../../hooks/useTheme.js";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggleTheme}
      aria-label="Тёмная тема"
      aria-pressed={isDark}
      title={`Включить ${isDark ? "светлую" : "тёмную"} тему`}
    >
      <span aria-hidden="true">{isDark ? "☀" : "☾"}</span>
      {isDark ? "Светлая тема" : "Тёмная тема"}
    </button>
  );
}
