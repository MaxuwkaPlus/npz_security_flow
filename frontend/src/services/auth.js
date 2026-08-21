/**
 * Хранение токена доступа.
 *
 * `sessionStorage`, а не `localStorage`: вкладка закрыта — сеанс закончился, и токен
 * не остаётся на общем компьютере в операторной. Права хранятся рядом только для того,
 * чтобы не показывать заведомо недоступные разделы: решение принимает сервер на
 * каждом запросе, и подделка этого списка ничего не открывает.
 */

const TOKEN_KEY = "npz.access_token";
const USER_KEY = "npz.user";

const listeners = new Set();

export function readSession() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const raw = sessionStorage.getItem(USER_KEY);
  if (!token || !raw) return null;

  try {
    return { token, user: JSON.parse(raw) };
  } catch {
    clearSession();
    return null;
  }
}

export function saveSession(token, user) {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  listeners.forEach((listener) => listener(readSession()));
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  listeners.forEach((listener) => listener(null));
}

export function accessToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

/** Подписка на вход и выход, включая принудительный после 401. */
export function onSessionChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
