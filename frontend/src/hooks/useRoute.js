import { useEffect, useState } from "react";

/**
 * Адрес страницы как часть состояния приложения.
 *
 * Раздел администратора ИБ вынесен на отдельный адрес, а не спрятан за кнопкой:
 * на общем компьютере в операторной рабочее место оператора не должно вести к
 * журналу доступа даже видом ссылки. Разграничение при этом делает сервер —
 * адрес лишь определяет, какой экран показать.
 */

export const ADMIN_PATH = "/admin";
export const CONSOLE_PATH = "/";

export function navigate(path) {
  if (window.location.pathname === path) return;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useRoute() {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const sync = () => setPath(window.location.pathname);
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  return path;
}
