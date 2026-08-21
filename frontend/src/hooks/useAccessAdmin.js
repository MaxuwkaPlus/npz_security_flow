import { useCallback, useEffect, useState } from "react";
import { api } from "../services/api.js";
import { apiErrorMessage } from "../utils/helpers.js";

/**
 * Состояние рабочего места администратора ИБ: учётные записи, роли и журнал доступа.
 *
 * Матрица ролей читается с сервера, а не дублируется в интерфейсе: расхождение между
 * показанным и применяемым было бы хуже отсутствия экрана.
 */
export function useAccessAdmin({ canManageAccounts, canReadAudit }) {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [events, setEvents] = useState([]);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const guard = useCallback(async (task, marker) => {
    setBusy(marker);
    setError(null);
    try {
      return await task();
    } catch (failure) {
      setError(apiErrorMessage(failure));
      return null;
    } finally {
      setBusy(null);
    }
  }, []);

  const loadUsers = useCallback(
    () => (canManageAccounts ? guard(() => api.users().then(setUsers), "users") : null),
    [canManageAccounts, guard],
  );

  const loadEvents = useCallback(
    (eventType = filter) =>
      canReadAudit
        ? guard(() => api.securityEvents({ event_type: eventType }).then(setEvents), "events")
        : null,
    [canReadAudit, filter, guard],
  );

  useEffect(() => {
    api.roles().then(setRoles).catch(() => setRoles([]));
    loadUsers();
    loadEvents("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canManageAccounts, canReadAudit]);

  const createUser = async (body) => {
    await guard(() => api.createUser(body), "create");
    await loadUsers();
    await loadEvents();
  };

  const grantRole = async (userId, role) => {
    await guard(() => api.grantRole(userId, role), userId);
    await loadUsers();
    await loadEvents();
  };

  const revokeRole = async (userId, role) => {
    await guard(() => api.revokeRole(userId, role), userId);
    await loadUsers();
    await loadEvents();
  };

  const toggleActive = async (userId, isActive) => {
    await guard(() => api.setUserActive(userId, isActive), userId);
    await loadUsers();
    await loadEvents();
  };

  const changeFilter = async (value) => {
    setFilter(value);
    await loadEvents(value);
  };

  return {
    busy,
    changeFilter,
    createUser,
    error,
    events,
    filter,
    grantRole,
    loadEvents,
    loadUsers,
    revokeRole,
    roles,
    toggleActive,
    users,
  };
}
