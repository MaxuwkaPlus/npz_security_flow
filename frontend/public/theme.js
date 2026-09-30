// Синхронно перед CSS/React, чтобы сохранённая тема не мигала при загрузке.
(() => {
  let theme = "dark";
  try {
    if (localStorage.getItem("npz.theme") === "light") theme = "light";
  } catch {
    // Запрет хранилища не должен мешать загрузке приложения.
  }
  document.documentElement.dataset.theme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#101b26" : "#f4f6f8");
})();
