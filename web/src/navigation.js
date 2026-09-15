const views = { overview: "Overview", teams: "Teams", players: "Players", proposals: "Proposals" };
const tabs = ["Roster", "Analysis", "Proposals"];
export const proposalStatuses = ["review", "all", "pending", "prepared", "authorized", "confirmed", "pending_waiver", "awaiting_verification", "unknown", "rejected", "cancelled", "not_submitted", "expired"];

export function readRoute(hash = "") {
  const [path, search = ""] = hash.replace(/^#/, "").split("?");
  const query = new URLSearchParams(search);
  const team = query.get("team") || "";
  return {
    view: views[path] || "Overview",
    team: /^[A-Za-z0-9_.:-]{1,120}$/.test(team) ? team : "",
    tab: tabs.find((tab) => tab.toLowerCase() === query.get("tab")) || "Roster",
    status: proposalStatuses.includes(query.get("status")) ? query.get("status") : "review",
  };
}

export function routeHash({ view = "Overview", team = "", tab = "Roster", status = "review" }) {
  const query = new URLSearchParams();
  if (team) query.set("team", team);
  if (view === "Teams" && tab !== "Roster") query.set("tab", tab.toLowerCase());
  if (view === "Proposals" && status !== "review") query.set("status", status);
  return `#${view.toLowerCase()}${query.size ? `?${query}` : ""}`;
}
