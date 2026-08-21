import { useEffect } from "react";
import { useAuth } from "./hooks/useAuth.js";
import { ADMIN_PATH, CONSOLE_PATH, navigate, useRoute } from "./hooks/useRoute.js";
import { useTrainingSession } from "./hooks/useTrainingSession.js";
import { AdminPage } from "./pages/AdminPage.jsx";
import { ExpertPage } from "./pages/ExpertPage.jsx";
import { HomePage } from "./pages/HomePage.jsx";
import { LoginPage } from "./pages/LoginPage.jsx";
import { ReportPage } from "./pages/ReportPage.jsx";
import { StartPage } from "./pages/StartPage.jsx";

/**
 * Два рабочих места на разных адресах.
 *
 * Пульт открыт сразу: обучаемый садится за него без входа и получает гостевой токен
 * ровно на своё прохождение. Кабинет эксперта и журнал доступа закрыты — там нужна
 * учётная запись, потому что решения эксперта подписываются именем, а журнал ИБ
 * вообще не рассчитан на анонимного читателя.
 *
 * Скрытый раздел — удобство, а не защита: обращение к чужому ресурсу отклонит сервер,
 * даже если открыть адрес напрямую.
 */
function App() {
  const path = useRoute();
  const auth = useAuth();

  if (path.startsWith(ADMIN_PATH)) {
    return <SecurityWorkplace auth={auth} />;
  }
  return <TrainingWorkplace auth={auth} />;
}

/** Рабочее место администратора ИБ: отдельный адрес и обязательный вход. */
function SecurityWorkplace({ auth }) {
  const authorized = auth.can("audit.read") || auth.can("account.manage");

  if (!authorized) {
    return (
      <LoginPage
        onLogin={auth.login}
        busy={auth.busy}
        // Гость сюда попал по адресу, а не по нехватке прав: сообщать ему об отказе
        // не за что. А вот вошедшему под чужой ролью сказать надо прямо.
        error={
          auth.isAuthenticated && !auth.isGuest
            ? "У этой учётной записи нет доступа к журналу и учётным записям"
            : auth.error
        }
        eyebrow="ДОСТУП И АУДИТ"
        title="Вход администратора ИБ"
        lead="Учётные записи, роли и журнал доступа. Раздел закрыт: войдите учётной записью с правом на аудит или управление доступом."
        onBack={() => navigate(CONSOLE_PATH)}
      />
    );
  }

  return <AdminPage auth={auth} onBack={() => navigate(CONSOLE_PATH)} />;
}

/** Пульт, разбор и отчёт. Вход не требуется — требуется он только у кабинета эксперта. */
function TrainingWorkplace({ auth }) {
  const training = useTrainingSession(auth);
  const canReview = auth.can("proposal.review") || auth.can("report.read_any");

  // Нет токена — берём гостевой. Экрана входа обучаемый не видит вовсе.
  useEffect(() => {
    if (!auth.isAuthenticated) auth.startGuest();
  }, [auth.isAuthenticated, auth.startGuest]);

  // Эксперт за пульт не садится — ему сразу разбор. Администратора ИБ сюда не
  // отправляем: его рабочее место на /admin, а на экран входа эксперта он попал бы
  // ни за чем.
  useEffect(() => {
    if (!auth.isAuthenticated) return;
    if (auth.can("session.operate") || auth.can("session.create")) return;
    if (canReview) training.setScreen("expert");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated, auth.user?.user_id]);

  if (!auth.isAuthenticated) {
    // Самостоятельное прохождение может быть отключено настройкой контура: тогда
    // остаётся вход по учётной записи.
    if (auth.error) {
      return (
        <LoginPage
          onLogin={auth.login}
          busy={auth.busy}
          error={auth.error}
          lead="Самостоятельное прохождение в этом контуре отключено: войдите учётной записью обучаемого или инструктора."
        />
      );
    }
    return (
      <main className="start-page">
        <div className="hero">
          <span className="eyebrow">УЧЕБНЫЙ КОМПЛЕКС</span>
          <h1>
            Пульт оператора
            <br />
            <em>ЭЛОУ-АВТ</em>
          </h1>
          <p>Готовим рабочее место…</p>
          <div className="hero-line" />
        </div>
      </main>
    );
  }

  // Гость может войти под своей учётной записью, не теряя пульт: отказ от входа
  // возвращает его туда же, откуда он пришёл.
  if (training.screen === "login") {
    return (
      <LoginPage
        onLogin={async (username, password) => {
          if (await auth.login(username, password)) training.setScreen("start");
        }}
        busy={auth.busy}
        error={auth.error}
        lead="Обучаемому вход нужен, чтобы прохождения остались за ним; инструктору — чтобы вести чужое обучение; эксперту — чтобы подписывать решения."
        onBack={() => training.setScreen("start")}
      />
    );
  }

  if (training.screen === "expert") {
    const leave = () => training.setScreen(training.session ? "console" : "start");
    if (!canReview) {
      return (
        <LoginPage
          onLogin={auth.login}
          busy={auth.busy}
          error={
            auth.isGuest
              ? auth.error
              : auth.error || "У этой учётной записи нет доступа к разбору прохождений"
          }
          eyebrow="КАБИНЕТ ЭКСПЕРТА"
          title="Вход эксперта"
          lead="Разбор прохождений и решения по сценариям. Раздел закрыт: утверждение рекомендации подписывается учётной записью, поэтому анонимно сюда не войти."
          onBack={leave}
        />
      );
    }
    return <ExpertPage auth={auth} onBack={leave} />;
  }

  if (training.screen === "report") {
    return (
      <ReportPage session={training.session} onBack={() => training.setScreen("console")} />
    );
  }

  if (training.screen === "start" || !training.session) {
    return (
      <StartPage
        auth={auth}
        scenarios={training.scenarios}
        sessions={training.sessions}
        onStart={training.startSession}
        onOpen={training.openSession}
        onRefresh={training.loadSessions}
        onNavigate={training.setScreen}
      />
    );
  }

  return <HomePage auth={auth} training={training} />;
}

export default App;
