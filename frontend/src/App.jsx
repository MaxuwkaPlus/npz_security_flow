import { useTrainingSession } from "./hooks/useTrainingSession.js";
import { ExpertPage } from "./pages/ExpertPage.jsx";
import { HomePage } from "./pages/HomePage.jsx";
import { ReportPage } from "./pages/ReportPage.jsx";
import { StartPage } from "./pages/StartPage.jsx";

function App() {
  const training = useTrainingSession();

  if (training.screen === "expert") {
    return (
      <ExpertPage
        onBack={() => training.setScreen(training.session ? "console" : "start")}
      />
    );
  }

  if (training.screen === "start") {
    return (
      <StartPage
        scenarios={training.scenarios}
        onStart={training.startSession}
        onExpert={() => training.setScreen("expert")}
      />
    );
  }

  if (training.screen === "report") {
    return (
      <ReportPage
        session={training.session}
        onBack={() => training.setScreen("console")}
      />
    );
  }

  return <HomePage training={training} />;
}

export default App;
