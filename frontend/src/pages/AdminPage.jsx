import { RoleMatrix } from "../components/Admin/RoleMatrix.jsx";
import { SecurityJournal } from "../components/Admin/SecurityJournal.jsx";
import { UserDirectory } from "../components/Admin/UserDirectory.jsx";
import { useAccessAdmin } from "../hooks/useAccessAdmin.js";

export function AdminPage({ auth, onBack }) {
  const canManageAccounts = auth.can("account.manage");
  const canReadAudit = auth.can("audit.read");
  const admin = useAccessAdmin({ canManageAccounts, canReadAudit });

  return (
    <main className="report-page expert-page">
      <header>
        <button onClick={onBack}>← Назад</button>
        <span className="eyebrow">ДОСТУП И АУДИТ</span>
        <h1>Учётные записи, роли и журнал доступа</h1>
        <p>
          Права проверяются на сервере при каждом запросе. Отзыв роли и отключение
          учётной записи действуют сразу: выданные токены обесцениваются, ждать
          истечения срока не нужно.
        </p>
      </header>

      {admin.error && <p className="banner negative">{admin.error}</p>}

      <div className="report-grid">
        {canManageAccounts && (
          <UserDirectory
            users={admin.users}
            roles={admin.roles}
            busy={admin.busy}
            onCreate={admin.createUser}
            onGrant={admin.grantRole}
            onRevoke={admin.revokeRole}
            onToggleActive={admin.toggleActive}
          />
        )}

        {canReadAudit && (
          <SecurityJournal
            events={admin.events}
            filter={admin.filter}
            onFilter={admin.changeFilter}
            onRefresh={() => admin.loadEvents()}
          />
        )}

        <RoleMatrix roles={admin.roles} />
      </div>
    </main>
  );
}
