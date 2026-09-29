import { RoleMatrix } from "../components/Admin/RoleMatrix.jsx";
import { SecurityJournal } from "../components/Admin/SecurityJournal.jsx";
import { UserDirectory } from "../components/Admin/UserDirectory.jsx";
import { useAccessAdmin } from "../hooks/useAccessAdmin.js";
import { PlatformHeader } from "../components/common/PlatformHeader.jsx";
import { PlatformFooter } from "../components/common/PlatformFooter.jsx";
import { PageHeading } from "../components/common/PageHeading.jsx";

export function AdminPage({ auth, onBack }) {
  const canManageAccounts = auth.can("account.manage");
  const canReadAudit = auth.can("audit.read");
  const admin = useAccessAdmin({ canManageAccounts, canReadAudit });

  return (
    <div className="platform-shell report-page expert-page">
      <PlatformHeader section="Администрирование">
        <button onClick={onBack}>← Назад</button>
      </PlatformHeader>
      <main className="report-content">
        <PageHeading
          section="Доступ и аудит"
          title="Управление доступом"
          description="Учётные записи, назначенные роли и журнал событий безопасности. Права доступа проверяются сервером."
        />

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
      <PlatformFooter />
    </div>
  );
}
