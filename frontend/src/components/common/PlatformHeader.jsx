/** Название самостоятельного проекта, без корпоративного знака и логотипов. */
export function PlatformHeader({ section, children }) {
  return (
    <header className="platform-header">
      <div className="platform-identity">
        <span className="platform-name">ЭЛОУ-АВТ</span>
        <span className="platform-description">
          Тренажёр операторов
          <br />
          технологической установки
        </span>
      </div>
      {section && <span className="platform-section">{section}</span>}
      <div className="platform-actions">{children}</div>
    </header>
  );
}
