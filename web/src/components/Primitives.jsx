import { humanize, initials } from "../format.js";

export function Icon({ name, size = 20, ...props }) {
  const paths = {
    overview: (
      <>
        <path d="m3 10 9-7 9 7v11h-7v-7h-4v7H3Z" />
      </>
    ),
    teams: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3 21v-3a6 6 0 0 1 12 0v3ZM16 4a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5v2" />
      </>
    ),
    players: (
      <>
        <circle cx="12" cy="7" r="4" />
        <path d="M4 21v-2a8 8 0 0 1 16 0v2Z" />
      </>
    ),
    proposals: (
      <>
        <path d="M5 3h10l4 4v14H5ZM14 3v5h5M8 12h8M8 16h6" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 4v6h-6M4 20v-6h6" />
        <path d="M5.4 8a8 8 0 0 1 13-3L20 7M4 17l1.6 2A8 8 0 0 0 19 16" />
      </>
    ),
    chevron: <path d="m9 5 7 7-7 7" />,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    check: <path d="m5 12 4 4L19 6" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    lock: (
      <>
        <rect x="5" y="10" width="14" height="11" rx="2" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      </>
    ),
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 6 6" />
      </>
    ),
    alert: (
      <>
        <path d="m12 3 10 18H2Z" />
        <path d="M12 9v5M12 17h.01" />
      </>
    ),
    field: (
      <>
        <rect x="2" y="5" width="28" height="18" rx=".5" />
        <path d="M16 5v18M2 10h4v8H2M30 10h-4v8h4" />
        <circle cx="16" cy="14" r="3" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox={name === "field" ? "0 0 32 28" : "0 0 24 24"}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}

export function Avatar({ name, index = 0, large = false }) {
  return (
    <span
      className={`avatar avatar-${index % 5}${large ? " avatar-large" : ""}`}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  );
}

export function Badge({ value, label }) {
  const positive = ["ready", "confirmed", "executed"].includes(value);
  const warning = [
    "stale",
    "prepared",
    "pending",
    "pending_waiver",
    "review_required",
    "incomplete",
    "unknown",
  ].includes(value);
  const negative = [
    "invalid",
    "missing",
    "rejected",
    "conflict",
    "not_submitted",
  ].includes(value);
  return (
    <span
      className={`badge ${positive ? "badge-green" : warning ? "badge-amber" : negative ? "badge-red" : "badge-neutral"}`}
    >
      {label || humanize(value)}
    </span>
  );
}

export function Notice({ children, kind = "info" }) {
  return (
    <div
      className={`notice notice-${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      <Icon
        name={kind === "error" || kind === "warning" ? "alert" : "check"}
        size={17}
      />
      <div>{children}</div>
    </div>
  );
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

export function Loading({ children = "Loading saved data…" }) {
  return (
    <div className="loading" role="status">
      <span className="loading-dot" />
      {children}
    </div>
  );
}

export function Pager({ total, offset, limit, onChange }) {
  return (
    <div className="pager">
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`
          : "0 results"}
      </span>
      <div>
        <button
          className="button button-small"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Previous
        </button>
        <button
          className="button button-small"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
