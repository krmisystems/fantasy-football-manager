import { useEffect, useState } from "react";
import { useResource } from "../api.js";
import { queryString, humanize } from "../format.js";
import { Loading, Notice, Pager, Icon } from "./Primitives.jsx";
import { RosterTable } from "./Teams.jsx";
import { ProposalRows } from "./Proposals.jsx";
import { proposalStatuses } from "../navigation.js";

export function PlayerExplorer({ teams, revision }) {
  const [team, setTeam] = useState("");
  const [position, setPosition] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [rostered, setRostered] = useState(true);
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(query);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);
  const state = useResource(
    `api/players?${queryString({ team_key: team, position, query: search, rostered_only: rostered, limit: 25, offset })}`,
    revision,
  );
  function change(setter, value) {
    setter(value);
    setOffset(0);
  }
  return (
    <section className="panel explorer">
      <div className="panel-heading">
        <div>
          <h2>Player directory</h2>
          <p>Search saved players across your managed teams.</p>
        </div>
      </div>
      <div className="explorer-filters">
        <label className="search-field">
          <Icon name="search" size={18} />
          <input
            type="search"
            aria-label="Search players"
            placeholder="Search players or NFL teams"
            value={query}
            maxLength={160}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label className="filter-label">
          <span className="sr-only">Managed team</span>
          <select
            value={team}
            onChange={(event) => change(setTeam, event.target.value)}
          >
            <option value="">All managed teams</option>
            {teams.map((item) => (
              <option key={item.team_key} value={item.team_key}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-label">
          <span className="sr-only">Position</span>
          <select
            value={position}
            onChange={(event) => change(setPosition, event.target.value)}
          >
            <option value="">All positions</option>
            {["QB", "RB", "WR", "TE", "DST", "K"].map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={rostered}
            onChange={(event) => change(setRostered, event.target.checked)}
          />
          My rosters only
        </label>
      </div>
      {!rostered ? (
        <div className="panel-notice">
          <Notice kind="warning">
            Unrostered players come from saved snapshots. Their current
            availability is not verified.
          </Notice>
        </div>
      ) : null}
      {state.error ? (
        <Notice kind="error">{state.error}</Notice>
      ) : !state.data ? (
        <Loading />
      ) : (
        <>
          <RosterTable players={state.data.players} global />
          <Pager
            total={state.data.total}
            offset={offset}
            limit={25}
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}

export function ProposalExplorer({ teams, revision, session, onReview, team = "", status = "review", onFilter }) {
  const [offset, setOffset] = useState(0);
  const effectiveStatus = status === "review" ? "unresolved" : status === "all" ? "" : status;
  useEffect(() => setOffset(0), [team, status]);
  const state = useResource(
    `api/proposals?${queryString({ team_key: team, status: effectiveStatus, limit: 25, offset })}`,
    revision,
  );
  return (
    <section className="panel explorer">
      <div className="panel-heading">
        <div>
          <h2>{status === "review" ? "Pending proposals" : "Proposal history"}</h2>
          <p>{status === "review" ? "Review saved changes and track unresolved submissions. Find calculated lineup suggestions under Teams → Analysis." : "Inspect past decisions and their recorded status."}</p>
        </div>
      </div>
      <div className="proposal-views" aria-label="Proposal views">
        <button className="button" aria-pressed={status === "review"} onClick={() => onFilter({ team, status: "review" })}>Pending</button>
        <button className="button" aria-pressed={status !== "review"} onClick={() => onFilter({ team, status: "all" })}>History</button>
      </div>
      <div className="explorer-filters">
        <label className="filter-label">
          <span className="sr-only">Managed team</span>
          <select
            value={team}
            onChange={(event) => {
              onFilter({ team: event.target.value, status });
              setOffset(0);
            }}
          >
            <option value="">All managed teams</option>
            {teams.map((item) => (
              <option key={item.team_key} value={item.team_key}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-label">
          <span className="sr-only">Proposal status</span>
          <select
            value={status}
            onChange={(event) => {
              onFilter({ team, status: event.target.value });
              setOffset(0);
            }}
          >
            {proposalStatuses.map((item) => (
              <option key={item} value={item}>
                {item === "review" ? "All pending" : item === "all" ? "All statuses" : humanize(item)}
              </option>
            ))}
          </select>
        </label>
        <p className="filter-hint">
          Provider confirmation determines the result.
        </p>
      </div>
      {state.error ? (
        <Notice kind="error">{state.error}</Notice>
      ) : !state.data ? (
        <Loading />
      ) : (
        <>
          <ProposalRows
            proposals={state.data.proposals}
            onReview={onReview}
            session={session}
          />
          {state.data.truncated ? (
            <Notice kind="warning">
              This view includes a bounded set of recent records.
            </Notice>
          ) : null}
          <Pager
            total={state.data.total}
            offset={offset}
            limit={25}
            onChange={setOffset}
          />
        </>
      )}
    </section>
  );
}
