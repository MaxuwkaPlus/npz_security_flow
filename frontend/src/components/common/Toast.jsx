export function Toast({ notification }) {
  if (!notification) return null;

  return (
    <div className={`toast ${notification.kind}`}>{notification.text}</div>
  );
}
