import { Icon } from "./Primitives.jsx";

const navigation = ["Overview", "Teams", "Players", "Proposals"];

export default function Shell({ view, setView, session, children }) {
  const access = session?.actions_enabled
    ? session.demo
      ? "Demo controls enabled"
      : "Submission controls enabled"
    : "Read-only access";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#overview"
          onClick={(event) => {
            event.preventDefault();
            setView("Overview");
          }}
          aria-label="Fieldroom overview"
        >
          <Icon name="field" size={70} />
          <strong>FIELDROOM</strong>
          <span>Fantasy portfolio</span>
        </a>
        <nav aria-label="Workspace">
          {navigation.map((item) => (
            <button
              key={item}
              className={`nav-item${item === view ? " active" : ""}`}
              aria-current={item === view ? "page" : undefined}
              onClick={() => setView(item)}
            >
              <Icon name={item.toLowerCase()} size={24} />
              <span>{item}</span>
            </button>
          ))}
        </nav>
        <div className="workspace-status">
          <span className="status-dot" />
          <div>
            <strong>Local workspace</strong>
            <span>{access}</span>
          </div>
        </div>
      </aside>
      <main id="main-content">{children}</main>
    </div>
  );
}
