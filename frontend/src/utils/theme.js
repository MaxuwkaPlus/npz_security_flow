export const THEME_STORAGE_KEY = "npz.theme";

export function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function applyTheme(theme) {
  const value = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = value;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", value === "dark" ? "#101b26" : "#f4f6f8");
  try {
    localStorage.setItem(THEME_STORAGE_KEY, value);
  } catch {
    // В закрытом хранилище выбор действует до перезагрузки страницы.
  }
  return value;
}
