import { useResource } from "../api.js";
import { age, humanize, points, timestamp } from "../format.js";
import { Avatar, Badge, Empty, Icon, Loading, Notice } from "./Primitives.jsx";
import { ProposalRows } from "./Proposals.jsx";

export function TeamTable({
  teams,
  selected,
  onSelect,
  filters,
  avatarTeams = teams,
}) {
  const leagueCount = new Set(teams.map((team) => team.league_key).filter(Boolean)).size;
  const unknownLeagues = teams.some((team) => !team.league_key);
  return (
    <section className="panel team-panel" aria-labelledby="managed-heading">
      <div className="panel-heading">
        <div>
          <h2 id="managed-heading">Managed teams</h2>
          <p>
            {teams.length} teams{leagueCount ? ` across ${leagueCount} ${unknownLeagues ? "known " : ""}${leagueCount === 1 ? "league" : "leagues"}` : " · League data unavailable"}
          </p>
        </div>
        {filters}
      </div>
      {teams.length ? (
        <div className="table-scroll">
          <table className="team-table">
            <thead>
              <tr>
                <th>Team</th>
                <th>League</th>
                <th>Week</th>
                <th>Status</th>
                <th>
                  <span className="sr-only">Open team</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {teams.map((team) => (
                <tr
                  className={selected === team.team_key ? "selected" : ""}
                  key={team.team_key}
                >
                  <td>
                    <button
                      className="team-select"
                      onClick={() => onSelect(team.team_key)}
                      aria-pressed={selected === team.team_key}
                    >
                      <Avatar
                        name={team.name}
                        index={Math.max(
                          0,
                          avatarTeams.findIndex(
                            (item) => item.team_key === team.team_key,
                          ),
                        )}
                      />
                      <strong>{team.name}</strong>
                    </button>
                  </td>
                  <td>{team.league_name}</td>
                  <td>{team.week ?? "—"}</td>
                  <td>
                    <Badge value={team.data_status} />
                    {team.paused ? (
                      <span className="cell-note">Paused</span>
                    ) : null}
                  </td>
                  <td>
                    <button
                      className="icon-button"
                      aria-label={`View ${team.name}`}
                      onClick={() => onSelect(team.team_key)}
                    >
                      <Icon name="chevron" size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No teams in this view">
          Select another filter, or configure a portfolio manifest.
        </Empty>
      )}
    </section>
  );
}

export function RosterTable({ players, global = false }) {
  const slotOrder = ["QB", "RB", "WR", "TE", "FLEX", "DST", "K", "BENCH", "IR"];
  const displayed = global
    ? players
    : [...players].sort((left, right) => {
        const order = (player) => {
          const index = slotOrder.indexOf(
            (player.slot || "").replace(/\d+$/, ""),
          );
          return index < 0 ? slotOrder.length : index;
        };
        return (
          order(left) - order(right) ||
          (left.slot || "").localeCompare(right.slot || "", undefined, {
            numeric: true,
          })
        );
      });
  return players.length ? (
    <div className="table-scroll">
      <table className="roster-table">
        <thead>
          <tr>
            {global ? <th>Managed team</th> : <th>Slot</th>}
            <th>Player</th>
            <th>Team</th>
            <th>Projected</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {displayed.map((player) => (
            <tr key={`${player.team_key}:${player.id}`}>
              <td>{global ? player.team_name : humanize(player.slot)}</td>
              <td>
                <span className="player-name">{player.name}</span>
                <span className="cell-note">
                  {player.position}
                  {player.protected ? " · Protected" : ""}
                </span>
              </td>
              <td>{player.nfl_team || "—"}</td>
              <td className="number">{points(player.weekly_projection)}</td>
              <td>
                <span className="player-state">
                  {player.locked ? (
                    <>
                      <Icon name="lock" size={13} />
                      Locked
                    </>
                  ) : player.availability ? (
                    humanize(player.availability)
                  ) : (
                    "Unknown"
                  )}
                  {!player.owned && global ? (
                    <span className="cell-note">
                      {player.roster_status === "opponent"
                        ? "Opponent roster"
                        : "Unrostered in snapshot"}
                    </span>
                  ) : null}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty title="No players to display">
      A valid saved roster is required.
    </Empty>
  );
}

export function TeamDetail({
  teamKey,
  teams,
  revision,
  tab,
  setTab,
  onReview,
  session,
  onExpand,
}) {
  const teamState = useResource(
    teamKey ? `api/teams/${encodeURIComponent(teamKey)}` : null,
    revision,
  );
  const analysisState = useResource(
    teamKey && tab === "Analysis"
      ? `api/teams/${encodeURIComponent(teamKey)}/analysis`
      : null,
    revision,
  );
  const proposalState = useResource(
    teamKey && tab === "Proposals"
      ? `api/proposals?team_key=${encodeURIComponent(teamKey)}&limit=50`
      : null,
    revision,
  );
  if (!teamKey) return null;
  const team = teamState.data?.team;
  return (
    <section className="panel detail-panel" aria-label="Selected team details">
      {teamState.error ? (
        <Notice kind="error">{teamState.error}</Notice>
      ) : !team ? (
        <Loading />
      ) : (
        <>
          <div className="detail-heading">
            <Avatar
              name={team.name}
              index={Math.max(
                0,
                teams.findIndex((item) => item.team_key === teamKey),
              )}
              large
            />
            <div>
              <h2>{team.name}</h2>
              <p>
                {team.league_name}
                <span className="dot-divider">·</span>Week {team.week ?? "—"}
              </p>
            </div>
            {onExpand ? (
              <button className="text-button view-team" onClick={onExpand}>
                View team <Icon name="arrow" size={19} />
              </button>
            ) : (
              <Badge value={team.data_status} />
            )}
          </div>
          {team.data_status !== "ready" ? (
            <Notice kind="warning">
              {humanize(team.data_status)} data.{" "}
              {team.data_status === "unsupported"
                ? "Analysis for this sport or provider is not implemented."
                : "Review the source status before you act."}
            </Notice>
          ) : null}
          <div
            className="tabs"
            role="tablist"
            aria-label={`${team.name} details`}
          >
            {["Roster", "Analysis", "Proposals"].map((name) => (
              <button
                key={name}
                id={`tab-${name}`}
                role="tab"
                aria-selected={tab === name}
                aria-controls="team-tab-panel"
                className={tab === name ? "active" : ""}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </div>
          <div
            id="team-tab-panel"
            role="tabpanel"
            aria-labelledby={`tab-${tab}`}
          >
            {tab === "Roster" ? (
              <>
                <RosterTable players={teamState.data.roster} />
                <div className="detail-meta">
                  <span>Saved {age(team.age_seconds)}</span>
                  <span>
                    {team.roster_count} players ·{" "}
                    {humanize(team.automation_mode)} mode
                  </span>
                </div>
              </>
            ) : null}
            {tab === "Analysis" ? (
              analysisState.error ? (
                <Notice kind="error">{analysisState.error}</Notice>
              ) : !analysisState.data ? (
                <Loading />
              ) : (
                <Analysis data={analysisState.data} teamData={teamState.data} />
              )
            ) : null}
            {tab === "Proposals" ? (
              proposalState.error ? (
                <Notice kind="error">{proposalState.error}</Notice>
              ) : !proposalState.data ? (
                <Loading />
              ) : (
                <ProposalRows
                  proposals={proposalState.data.proposals}
                  onReview={onReview}
                  session={session}
                />
              )
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

function Analysis({ data, teamData }) {
  const players = new Map(teamData.roster.map((player) => [player.id, player]));
  const current = new Map(
    teamData.roster
      .filter((player) => player.slot !== "BENCH" && player.slot !== "IR")
      .map((player) => [player.slot, player.id]),
  );
  const changes = Object.entries(data.lineup || {}).filter(
    ([slot, id]) => current.get(slot) !== id,
  );
  const messages = [...(data.errors || []), ...(data.warnings || [])];
  return (
    <div className="analysis-content">
      <div className="analysis-caption">
        <div>
          <h3>Lineup analysis</h3>
          <p>
            A calculation from saved player data. This is not a submitted
            proposal.
          </p>
        </div>
        <Badge
          value={
            data.status ||
            (data.comparison_complete === false ? "incomplete" : "ready")
          }
        />
      </div>
      <div className="analysis-metrics">
        <div>
          <span>Current projection</span>
          <strong>{points(data.current_points)}</strong>
        </div>
        <div>
          <span>Suggested projection</span>
          <strong>{points(data.projected_points)}</strong>
        </div>
        <div>
          <span>Potential change</span>
          <strong className="positive">
            {typeof data.improvement === "number" && data.improvement > 0
              ? "+"
              : ""}
            {points(data.improvement)}
          </strong>
        </div>
      </div>
      {messages.map((message, index) => (
        <Notice key={index} kind="warning">
          {message}
        </Notice>
      ))}
      {changes.length ? (
        <>
          <h3 className="subheading">Suggested slot changes</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Current player</th>
                  <th>Suggested player</th>
                </tr>
              </thead>
              <tbody>
                {changes.map(([slot, id]) => (
                  <tr key={slot}>
                    <td>{slot}</td>
                    <td>{players.get(current.get(slot))?.name || "Empty"}</td>
                    <td>
                      {players.get(id)?.name || (id ? `Player ${id}` : "Empty")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <Empty
          title={
            data.status === "unavailable"
              ? "Analysis unavailable"
              : data.comparison_complete === false
                ? "A complete comparison is unavailable"
                : "No slot changes suggested"
          }
        >
          Missing projections remain unknown.
        </Empty>
      )}
      <div className="policy-strip">
        <div>
          <span>Season strategy</span>
          <strong>{humanize(teamData.policy?.strategy?.season)}</strong>
        </div>
        <div>
          <span>Lineup policy</span>
          <strong>
            {humanize(teamData.policy?.effective_modes?.set_lineup)}
          </strong>
        </div>
        <div>
          <span>FAAB balance</span>
          <strong>{teamData.budget?.balance ?? "—"}</strong>
        </div>
        <div>
          <span>Analysis time</span>
          <strong>{timestamp(data.generated_at)}</strong>
        </div>
      </div>
    </div>
  );
}
