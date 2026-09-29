export function Toast({ notification }) {
  if (!notification) return null;

  return (
    <div
      className={`toast ${notification.kind}`}
      role={notification.kind === "error" ? "alert" : "status"}
    >
      {notification.text}
    </div>
  );
}
