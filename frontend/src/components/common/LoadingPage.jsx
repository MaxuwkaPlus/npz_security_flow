import { PlatformHeader } from "./PlatformHeader.jsx";
import { PlatformFooter } from "./PlatformFooter.jsx";
import { PageHeading } from "./PageHeading.jsx";

export function LoadingPage() {
  return (
    <div className="platform-shell">
      <PlatformHeader section="Учебный комплекс" />
      <main className="page-content loading-page" aria-busy="true">
        <PageHeading
          section="Подготовка к тренировке"
          title="Рабочее место оператора"
          description="Подключаемся к учебному комплексу…"
        />
      </main>
      <PlatformFooter />
    </div>
  );
}
