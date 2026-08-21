import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api.js";
import { clearSession, onSessionChange, readSession, saveSession } from "../services/auth.js";
import { apiErrorMessage } from "../utils/helpers.js";

/**
 * Текущий субъект: кто вошёл, какие у него роли и права.
 *
 * Права нужны интерфейсу, чтобы не показывать недоступные разделы. Это удобство,
 * а не защита: каждую ручку проверяет сервер, и спрятанная кнопка ничего не решает.
 *
 * Пульт открыт без входа: если токена нет, клиент берёт гостевой. Он тоже настоящий —
 * выдан сервером и ограничен своим прохождением, — поэтому дальше всё работает
 * одинаково, независимо от того, вошёл человек по учётной записи или нет.
 */
export function useAuth() {
  const [session, setSession] = useState(() => readSession());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // Гостевой токен запрашивается один раз за монтирование: без этого неудачный
  // запрос повторялся бы на каждом рендере.
  const guestRequested = useRef(false);

  // Просроченный токен обнуляет сеанс прямо в слое запросов — экран входа должен
  // появиться и без действия пользователя.
  useEffect(() => onSessionChange(setSession), []);

  useEffect(() => {
    if (!session) return;
    // Роли могли измениться в другой вкладке или быть отозваны администратором.
    api.me().then((user) => saveSession(session.token, user)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.token]);

  const login = useCallback(async (username, password) => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(username, password);
      saveSession(result.access_token, result.user);
      // Вход по учётной записи отменяет гостевой режим: следующий выход должен
      // снова привести к пульту, а не к бесконечному экрану входа.
      guestRequested.current = false;
      return true;
    } catch (failure) {
      setError(apiErrorMessage(failure));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const startGuest = useCallback(async () => {
    if (guestRequested.current) return false;
    guestRequested.current = true;
    setError(null);
    try {
      const result = await api.guest();
      saveSession(result.access_token, result.user);
      return true;
    } catch (failure) {
      // Самостоятельное прохождение может быть отключено настройкой контура —
      // тогда остаётся вход по учётной записи, и об этом надо сказать прямо.
      setError(apiErrorMessage(failure));
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Токен мог истечь сам — состояние на клиенте всё равно очищаем.
    } finally {
      guestRequested.current = false;
      clearSession();
    }
  }, []);

  const user = session?.user || null;
  const can = useCallback(
    (permission) => Boolean(user?.permissions?.includes(permission)),
    [user],
  );

  return {
    user,
    can,
    busy,
    error,
    login,
    logout,
    startGuest,
    isAuthenticated: Boolean(user),
    // Гость сел за пульт без проверки личности: ему не предлагают «выйти», ему
    // предлагают войти, и его именем ничего не подписывается.
    isGuest: Boolean(user?.roles?.includes("guest")),
  };
}
