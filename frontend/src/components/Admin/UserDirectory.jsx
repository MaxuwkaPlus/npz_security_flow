import { useState } from "react";

const ASSIGNABLE_HINT =
  "Роли следующего цикла — автор сценариев, администратор, техподдержка — описаны в матрице, но пока не назначаются.";

export function UserDirectory({ users, roles, busy, onCreate, onGrant, onRevoke, onToggleActive }) {
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "trainee" });
  const assignable = roles.filter((role) => role.assignable);

  const submit = (event) => {
    event.preventDefault();
    onCreate({
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password,
      roles: [form.role],
    });
    setForm({ ...form, username: "", display_name: "", password: "" });
  };

  return (
    <section className="report-card wide">
      <h2>Учётные записи</h2>
      <p className="hint">{ASSIGNABLE_HINT}</p>

      <form className="user-form" onSubmit={submit}>
        <input
          placeholder="логин"
          value={form.username}
          maxLength="64"
          onChange={(event) => setForm({ ...form, username: event.target.value })}
          required
        />
        <input
          placeholder="фамилия и должность"
          value={form.display_name}
          maxLength="200"
          onChange={(event) => setForm({ ...form, display_name: event.target.value })}
          required
        />
        <input
          type="password"
          placeholder="пароль, минимум 12 символов"
          value={form.password}
          onChange={(event) => setForm({ ...form, password: event.target.value })}
          required
        />
        <select
          value={form.role}
          onChange={(event) => setForm({ ...form, role: event.target.value })}
        >
          {assignable.map((role) => (
            <option key={role.role} value={role.role}>
              {role.role}
            </option>
          ))}
        </select>
        <button className="primary" disabled={busy === "create"}>
          Завести
        </button>
      </form>

      <table className="user-table">
        <thead>
          <tr>
            <th>Учётная запись</th>
            <th>Роли</th>
            <th>Состояние</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id} className={user.is_active ? "" : "inactive"}>
              <td>
                <b>{user.username}</b>
                <small>{user.display_name}</small>
              </td>
              <td>
                {user.roles.map((role) => (
                  <button
                    key={role}
                    className="role-chip"
                    title="Отозвать роль — выданные токены будут обесценены немедленно"
                    disabled={busy === user.id}
                    onClick={() => onRevoke(user.id, role)}
                  >
                    {role} ×
                  </button>
                ))}
              </td>
              <td>{user.is_active ? "активна" : "отключена"}</td>
              <td>
                {/* Раскладка живёт во вложенном контейнере, а не на самой ячейке:
                    `display: flex` на `td` выводит его из табличной раскладки, и
                    ячейка перестаёт тянуться на высоту строки — разделители
                    соседних столбцов расходятся ступенькой. */}
                <div className="user-actions">
                  <select
                    defaultValue=""
                    disabled={busy === user.id}
                    onChange={(event) => {
                      if (event.target.value) onGrant(user.id, event.target.value);
                      event.target.value = "";
                    }}
                  >
                    <option value="">выдать роль…</option>
                    {assignable
                      .filter((role) => !user.roles.includes(role.role))
                      .map((role) => (
                        <option key={role.role} value={role.role}>
                          {role.role}
                        </option>
                      ))}
                  </select>
                  <button
                    disabled={busy === user.id}
                    onClick={() => onToggleActive(user.id, !user.is_active)}
                  >
                    {user.is_active ? "Отключить" : "Включить"}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
