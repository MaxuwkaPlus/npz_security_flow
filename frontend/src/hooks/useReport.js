import { useEffect, useState } from "react";
import { api } from "../services/api.js";

export function useReport(sessionId, operatorId) {
  const [report, setReport] = useState(null);
  const [comparison, setComparison] = useState(null);

  useEffect(() => {
    if (!sessionId) return;

    api.report(sessionId).then(setReport).catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    if (!operatorId) return;

    api.comparison(operatorId).then(setComparison).catch(() => {});
  }, [operatorId]);

  return { comparison, report };
}
