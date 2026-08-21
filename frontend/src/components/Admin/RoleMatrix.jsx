/**
 * Матрица ролей и прав в том виде, в котором её применяет сервер.
 *
 * Нужна на разборе доступа: показывает не только выданное, но и намеренно
 * не выданное — например, что автор сценариев не может менять правила безопасности.
 */
export function RoleMatrix({ roles }) {
  const permissions = [...new Set(roles.flatMap((role) => role.permissions))].sort();

  return (
    <section className="report-card wide">
      <h2>Матрица прав</h2>
      <p className="hint">
        Роль — упаковка прав. Решение по каждому запросу принимается по конкретному
        праву, поэтому разделение полномочий сохраняется при любом наборе ролей.
      </p>
      <div className="matrix-scroll">
        <table className="user-table matrix">
          <thead>
            <tr>
              <th>Право</th>
              {roles.map((role) => (
                <th key={role.role} className={role.assignable ? "" : "inactive"}>
                  {role.role}
                  {!role.assignable && <small>следующий цикл</small>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {permissions.map((permission) => (
              <tr key={permission}>
                <td>{permission}</td>
                {roles.map((role) => (
                  <td key={role.role} className="matrix-cell">
                    {role.permissions.includes(permission) ? "●" : "·"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
