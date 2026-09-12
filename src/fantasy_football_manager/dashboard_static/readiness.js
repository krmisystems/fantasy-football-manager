const labels = {
  operational_health: "Managed-team operational health", live_set_lineup: "Live lineup change",
  live_free_agent_add: "Live free-agent acquisition", live_waiver_claim: "Delayed waiver processing",
  live_move_to_ir: "Live IR placement", live_activate_from_ir: "Live IR activation", live_rollover: "All-team week rollover",
  weekly_cycle: "Complete weekly observation cycle", waiver_window: "League waiver windows",
  backup_integrity: "Backup integrity", backup_restore: "Isolated backup restore", installation_provenance: "Installed version evidence",
  candidate_checks: "Candidate tests and upgrade", distribution_build: "Publication and hosted build", publication_approval: "Stable release decision",
};
let loading = false;
async function refresh() {
  if (loading) return;
  loading = true;
  const button = document.getElementById("refresh");
  button.disabled = true;
  try {
    const response = await fetch("api/readiness", { cache: "no-store" });
    if (!response.ok) throw new Error("unavailable");
    const data = await response.json();
    const fresh = data.status === "pending";
    document.getElementById("status").textContent = fresh ? "Stable release pending" : data.status === "stale" ? "Evidence is stale" : "Evidence unavailable";
    document.getElementById("detail").textContent = fresh ? `${data.team_count} teams · ${data.healthy ? "Operational checks pass" : "Operational attention required"} · Checked ${new Date(data.checked_at).toLocaleString()}` : "A current collector report is required. Missing evidence cannot pass an acceptance check.";
    const target = document.getElementById("gates");
    target.replaceChildren();
    for (const [key, label] of Object.entries(labels)) {
      const state = fresh && ["passed", "failed", "pending"].includes(data.gates?.[key]) ? data.gates[key] : "unknown";
      const card = document.createElement("article");
      const title = document.createElement("h3");
      title.textContent = label;
      const badge = document.createElement("span");
      badge.className = `badge ${state}`;
      badge.textContent = state[0].toUpperCase() + state.slice(1);
      card.append(title, badge); target.append(card);
    }
  } catch {
    document.getElementById("status").textContent = "Evidence unavailable";
    document.getElementById("detail").textContent = "The report request failed. Use Refresh evidence to retry.";
    document.getElementById("gates").replaceChildren();
  } finally { loading = false; button.disabled = false; }
}
document.getElementById("refresh").addEventListener("click", refresh);
setInterval(() => { if (!document.hidden) refresh(); }, 30000);
refresh();
