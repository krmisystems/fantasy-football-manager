import { useEffect, useState } from "react";
import { useResource } from "../api.js";
import { queryString, humanize } from "../format.js";
import { Loading, Notice, Pager, Icon } from "./Primitives.jsx";
import { RosterTable } from "./Teams.jsx";
import { ProposalRows } from "./Proposals.jsx";

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

export function ProposalExplorer({ teams, revision, session, onReview }) {
  const [team, setTeam] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const state = useResource(
    `api/proposals?${queryString({ team_key: team, status, limit: 25, offset })}`,
    revision,
  );
  return (
    <section className="panel explorer">
      <div className="panel-heading">
        <div>
          <h2>Proposal history</h2>
          <p>Inspect saved decisions and review exact changes.</p>
        </div>
      </div>
      <div className="explorer-filters">
        <label className="filter-label">
          <span className="sr-only">Managed team</span>
          <select
            value={team}
            onChange={(event) => {
              setTeam(event.target.value);
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
              setStatus(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All statuses</option>
            {[
              "pending",
              "prepared",
              "authorized",
              "confirmed",
              "pending_waiver",
              "unknown",
              "rejected",
              "cancelled",
              "not_submitted",
            ].map((item) => (
              <option key={item} value={item}>
                {humanize(item)}
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
