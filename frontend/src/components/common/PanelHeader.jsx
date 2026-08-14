export function PanelHeader({ title, children }) {
  return (
    <div className="panel-head">
      <h3>{title}</h3>
      {children}
    </div>
  );
}
