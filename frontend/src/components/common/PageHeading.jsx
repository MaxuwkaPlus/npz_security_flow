export function PageHeading({ section, title, description, children }) {
  return (
    <header className="page-heading">
      <div>
        <span className="eyebrow">{section}</span>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children}
    </header>
  );
}
