import { useEffect, useRef } from "react";
import { socketUrl } from "../services/api.js";
import { clearSession } from "../services/auth.js";

// Коды закрытия из диапазона приложения: отказ в доступе не лечится повтором,
// и переподключаться по нему нельзя — иначе клиент будет долбить сервер.
const UNAUTHENTICATED = 4401;
const FORBIDDEN = 4403;
const NOT_FOUND = 4404;
const FINAL_CODES = [UNAUTHENTICATED, FORBIDDEN, NOT_FOUND];

export function useSessionSocket(sessionId, onMessage, onStatus) {
  const sequence = useRef(0);
  const retry = useRef();
  const onMessageRef = useRef(onMessage);
  const onStatusRef = useRef(onStatus);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onStatusRef.current = onStatus;
  }, [onMessage, onStatus]);

  useEffect(() => {
    if (!sessionId) return undefined;

    let stopped = false;
    let websocket;

    const connect = () => {
      onStatusRef.current("connecting");
      websocket = new WebSocket(socketUrl(sessionId, sequence.current));
      websocket.onopen = () => onStatusRef.current("connected");
      websocket.onmessage = ({ data }) => {
        const message = JSON.parse(data);
        if (message.sequence_no > sequence.current) {
          sequence.current = message.sequence_no;
        }
        onMessageRef.current(message);
      };
      websocket.onclose = ({ code }) => {
        if (stopped) return;

        if (FINAL_CODES.includes(code)) {
          onStatusRef.current("denied");
          // Токен истёк или отозван — сеанс закончился, нужен повторный вход.
          if (code === UNAUTHENTICATED) clearSession();
          return;
        }

        onStatusRef.current("reconnecting");
        retry.current = setTimeout(connect, 1500);
      };
      websocket.onerror = () => websocket.close();
    };

    connect();

    return () => {
      stopped = true;
      clearTimeout(retry.current);
      websocket?.close();
    };
  }, [sessionId]);
}
