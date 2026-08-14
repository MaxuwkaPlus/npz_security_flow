import { useTrainingSession } from "./hooks/useTrainingSession.js";
import { HomePage } from "./pages/HomePage.jsx";
import { ReportPage } from "./pages/ReportPage.jsx";
import { StartPage } from "./pages/StartPage.jsx";

function App() {
  const training = useTrainingSession();

  if (training.screen === "start") {
    return (
      <StartPage scenarios={training.scenarios} onStart={training.startSession} />
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
