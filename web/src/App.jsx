import { useEffect, useState } from "react";
import { useRefreshClock, useResource } from "./api.js";
import { humanize, isPending } from "./format.js";
import Shell from "./components/Shell.jsx";
import { Empty, Icon, Loading, Notice } from "./components/Primitives.jsx";
import { TeamDetail, TeamTable } from "./components/Teams.jsx";
import { ProposalModal, ReviewQueue } from "./components/Proposals.jsx";
import { PlayerExplorer, ProposalExplorer } from "./components/Explorer.jsx";

export default function App() {
  const [view, setView] = useState("Overview");
  const [selected, setSelected] = useState(null);
  const [tab, setTab] = useState("Roster");
  const [provider, setProvider] = useState("");
  const [sport, setSport] = useState("");
  const [proposal, setProposal] = useState(null);
  const [revision, refresh] = useRefreshClock();
  const overview = useResource("api/overview", revision);
  const session = useResource("api/session", revision);
  const queue = useResource(
    overview.data
      ? `api/proposals?status=${overview.data.source_mode === "demo" ? "prepared" : "pending"}&limit=200`
      : null,
    revision,
  );
  const allTeams = overview.data?.teams || [];
  const teams = allTeams.filter(
    (team) =>
      (!provider || team.provider === provider) &&
      (!sport || team.sport === sport),
  );
  const activeKey = teams.some((team) => team.team_key === selected)
    ? selected
    : teams[0]?.team_key;
  const pending = (queue.data?.proposals || []).filter(
    (item) =>
      isPending(item) && teams.some((team) => team.team_key === item.team_key),
  );
  useEffect(() => {
    setTab("Roster");
  }, [activeKey]);
  const demo = overview.data?.source_mode === "demo";
  const summary = overview.data?.summary;
  const providers = [...new Set(allTeams.map((team) => team.provider))];
  const sports = [
    ...new Set([
      ...(overview.data?.supported_sports || []),
      ...allTeams.map((team) => team.sport),
    ]),
  ];
  const filters = (
    <div className="table-filters">
      <label>
        <span className="sr-only">Provider</span>
        <select
          value={provider}
          onChange={(event) => setProvider(event.target.value)}
        >
          <option value="">All providers</option>
          {providers.map((item) => (
            <option key={item} value={item}>
              {item === "espn" ? "ESPN" : humanize(item)}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className="sr-only">Sport</span>
        <select
          value={sport}
          onChange={(event) => setSport(event.target.value)}
        >
          <option value="">
            {sports.length === 1 ? humanize(sports[0]) : "All sports"}
          </option>
          {sports.length > 1
            ? sports.map((item) => (
                <option key={item} value={item}>
                  {humanize(item)}
                </option>
              ))
            : null}
        </select>
      </label>
    </div>
  );
  return (
    <Shell view={view} setView={setView} session={session.data}>
      <a className="skip-link" href="#workspace-content">
        Skip to workspace
      </a>
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            Workspace <span>/</span> {view}
          </div>
          <h1>
            {view === "Overview"
              ? "Your teams. One field of view."
              : view === "Teams"
                ? "Every team, in context."
                : view === "Players"
                  ? "Know your player pool."
                  : "Review every change."}
          </h1>
          <p>
            {view === "Overview"
              ? "Track saved team data and review proposed changes."
              : view === "Teams"
                ? "Inspect rosters, analysis, and saved proposals."
                : view === "Players"
                  ? "Find players across leagues and managed rosters."
                  : "Inspect proposals before approval and submission."}
          </p>
        </div>
        <div className="header-actions">
          {demo ? <span className="demo-label">Demo data</span> : null}
          <button
            className="button button-primary refresh-button"
            onClick={refresh}
            disabled={overview.loading}
            aria-label="Refresh saved data"
          >
            <Icon name="refresh" size={20} />
            <span>Refresh</span>
          </button>
        </div>
      </header>
      <div id="workspace-content">
        {overview.error ? (
          <Notice kind="error">
            {overview.error} Use Refresh to try again.
          </Notice>
        ) : null}
        {session.error ? (
          <Notice kind="warning">
            Submission controls are unavailable. {session.error}
          </Notice>
        ) : null}
        {!overview.data && overview.loading ? (
          <Loading>Loading your portfolio…</Loading>
        ) : overview.data ? (
          <>
            {view === "Overview" ? (
              <div className="summary-band" aria-label="Portfolio totals">
                {[
                  ["Managed teams", summary.total_teams, ""],
                  ["Ready teams", summary.ready_teams, "positive"],
                  ["Needs attention", summary.attention_teams, "warning-text"],
                  ["Pending proposals", summary.pending_proposals, "muted"],
                ].map(([label, value, className]) => (
                  <div
                    key={label}
                    title={
                      label === "Ready teams"
                        ? "The saved source is complete and within its age limit. A ready team can also need attention."
                        : label === "Needs attention"
                          ? "Includes source issues, unverified locks, pending proposals, missing projections, or paused automation. This count can overlap Ready teams."
                          : undefined
                    }
                  >
                    <span>{label}</span>
                    <strong className={className}>{value}</strong>
                  </div>
                ))}
              </div>
            ) : null}
            {overview.data.configuration_required ? (
              <div className="panel">
                <Empty title="Connect your managed teams">
                  Start the dashboard with a portfolio manifest, or use demo
                  mode to explore fictional teams.
                </Empty>
              </div>
            ) : null}
            {view === "Overview" || view === "Teams" ? (
              <>
                <div className={view === "Overview" ? "overview-grid" : ""}>
                  <TeamTable
                    teams={teams}
                    avatarTeams={allTeams}
                    selected={activeKey}
                    onSelect={setSelected}
                    filters={filters}
                  />
                  {view === "Overview" ? (
                    <aside className="right-rail">
                      {queue.error ? (
                        <Notice kind="error">{queue.error}</Notice>
                      ) : (
                        <ReviewQueue
                          proposals={pending}
                          onSelect={setProposal}
                          teams={allTeams}
                        />
                      )}
                      <section className="panel source-health">
                        <div className="rail-heading">
                          <h2>Source health</h2>
                        </div>
                        <ul>
                          <li>
                            <span className="check-circle">
                              <Icon name="check" size={14} />
                            </span>
                            Saved snapshots only
                          </li>
                          <li>
                            <span className="check-circle">
                              <Icon name="check" size={14} />
                            </span>
                            {session.data?.actions_enabled
                              ? demo
                                ? "Demo submission enabled"
                                : "Exact approval required"
                              : "No live transactions"}
                          </li>
                          <li>
                            <span className="check-circle">
                              <Icon name="check" size={14} />
                            </span>
                            Football supported
                          </li>
                        </ul>
                      </section>
                    </aside>
                  ) : null}
                </div>
                <TeamDetail
                  teamKey={activeKey}
                  teams={allTeams}
                  revision={revision}
                  tab={tab}
                  setTab={setTab}
                  onReview={setProposal}
                  session={session.data}
                  onExpand={view === "Overview" ? () => setView("Teams") : null}
                />
              </>
            ) : null}
            {view === "Players" ? (
              <PlayerExplorer teams={allTeams} revision={revision} />
            ) : null}
            {view === "Proposals" ? (
              <ProposalExplorer
                teams={allTeams}
                revision={revision}
                session={session.data}
                onReview={setProposal}
              />
            ) : null}
          </>
        ) : null}
      </div>
      <footer className="page-footer">
        {demo
          ? "Demo workspace. Team data and proposals are synthetic."
          : "Local workspace. Data comes from configured team stores."}
        <span>Refreshes every 30 seconds while visible.</span>
      </footer>
      {proposal ? (
        <ProposalModal
          key={`${proposal.team_key}:${proposal.id}`}
          proposal={proposal}
          session={session.data}
          avatarIndex={Math.max(
            0,
            allTeams.findIndex((team) => team.team_key === proposal.team_key),
          )}
          onClose={() => setProposal(null)}
          onSubmitted={refresh}
        />
      ) : null}
    </Shell>
  );
}
