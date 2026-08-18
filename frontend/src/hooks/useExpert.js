import { useCallback, useEffect, useState } from "react";
import { mlApi } from "../services/mlApi.js";

/**
 * Состояние кабинета эксперта.
 *
 * Владеет всем обменом с сервисом рекомендаций: списком прохождений, разбором
 * выбранного, очередью предложений и поиском системных проблем. Страница и её
 * компоненты остаются отображением, как и на пульте оператора.
 */
export function useExpert(expertId) {
  const [health, setHealth] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [advice, setAdvice] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [findings, setFindings] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const guard = useCallback(async (task, marker) => {
    setBusy(marker);
    setError(null);
    try {
      return await task();
    } catch (failure) {
      setError(failure.message);
      return null;
    } finally {
      setBusy(null);
    }
  }, []);

  const loadProposals = useCallback(
    () => guard(() => mlApi.proposals().then((data) => setProposals(data.items)), "proposals"),
    [guard],
  );

  useEffect(() => {
    mlApi.health().then(setHealth).catch(() => setHealth(null));
    guard(() => mlApi.sessions().then((data) => setSessions(data.items)), "sessions");
    loadProposals();
  }, [guard, loadProposals]);

  const review = async (proposalId, decision, comment) => {
    await guard(() => mlApi.review(proposalId, decision, expertId, comment), proposalId);
    await loadProposals();
  };

  return {
    advice,
    error,
    findings,
    health,
    busy,
    proposals,
    selectedId,
    sessions,
    review,
    // Разбор прохождения кладёт черновик в очередь, поэтому её сразу перечитываем.
    selectSession: async (sessionId) => {
      setSelectedId(sessionId);
      setAdvice(null);
      await guard(() => mlApi.advice(sessionId).then(setAdvice), "advice");
      await loadProposals();
    },
    mine: async (source) => {
      await guard(() => mlApi.mine(source).then(setFindings), "mine");
      await loadProposals();
    },
  };
}
