export function points(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(1)
    : "—";
}

export function humanize(value) {
  if (value == null || value === "") return "Unknown";
  return String(value)
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}

export function initials(name = "") {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "?"
  );
}

export function age(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds))
    return "No saved snapshot";
  if (seconds < 60) return "Less than a minute ago";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return `${Math.floor(seconds / 86400)} days ago`;
}

export function timestamp(value) {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime())
    ? date.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Not recorded";
}

export function isPending(proposal) {
  return ["prepared", "pending", "authorized", "review_required"].includes(
    proposal.status,
  );
}

export function canReview(proposal, session) {
  return (
    session?.actions_enabled === true &&
    proposal.is_current === true &&
    proposal.mode === "review" &&
    ((proposal.source === "http" && proposal.status === "pending") ||
      (session.demo === true &&
        proposal.source === "synthetic" &&
        proposal.status === "prepared"))
  );
}

export function queryString(values) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== "" && value != null) query.set(key, String(value));
  }
  return query.toString();
}

export function lineupChanges(lineup = {}, current = {}, names = {}) {
  const before = new Map(
    Object.entries(current)
      .filter(([, id]) => id != null)
      .map(([slot, id]) => [id, slot]),
  );
  const after = new Map(
    Object.entries(lineup)
      .filter(([, id]) => id != null)
      .map(([slot, id]) => [id, slot]),
  );
  return [...new Set([...before.keys(), ...after.keys()])]
    .filter((id) => before.get(id) !== after.get(id))
    .map((id) => ({
      id,
      name: names[id] || `Player ${id}`,
      before: before.get(id) || "BENCH",
      after: after.get(id) || "BENCH",
    }));
}
