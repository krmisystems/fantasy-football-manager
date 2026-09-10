import { useEffect, useRef, useState } from "react";
import { post } from "../api.js";
import { canReview, humanize, lineupChanges, timestamp } from "../format.js";
import { Avatar, Badge, Empty, Icon, Notice } from "./Primitives.jsx";

export function ReviewQueue({ proposals, onSelect, teams }) {
  return (
    <section className="panel review-queue">
      <div className="rail-heading">
        <h2>Review queue</h2>
        <span className="pending-count">
          <span />
          {proposals.length} pending
        </span>
      </div>
      {proposals.length ? (
        proposals.slice(0, 3).map((proposal) => (
          <button
            key={`${proposal.team_key}:${proposal.id}`}
            className="queue-row"
            onClick={() => onSelect(proposal)}
          >
            <Avatar
              name={proposal.team_name}
              index={Math.max(
                0,
                teams.findIndex((team) => team.team_key === proposal.team_key),
              )}
            />
            <span>
              <strong>
                {proposal.action === "set_lineup"
                  ? "Lineup change"
                  : humanize(proposal.action)}
              </strong>
              <span>{proposal.team_name}</span>
              <small>
                {humanize(proposal.status)} · {humanize(proposal.mode)} mode
              </small>
            </span>
            <Icon name="chevron" size={18} />
          </button>
        ))
      ) : (
        <Empty title="No proposals await review">
          Pending review proposals will appear here.
        </Empty>
      )}
    </section>
  );
}

export function ProposalRows({ proposals, onReview, session }) {
  if (!proposals.length)
    return (
      <Empty title="No saved proposals">
        Calculated recommendations appear in Analysis.
      </Empty>
    );
  return (
    <div className="proposal-list">
      {proposals.map((proposal) => (
        <article
          key={`${proposal.team_key}:${proposal.id}`}
          className="proposal-row"
        >
          <div className="proposal-main">
            <div className="proposal-title">
              <strong>{proposal.summary || humanize(proposal.action)}</strong>
              <Badge value={proposal.status} />
              {proposal.synthetic ? (
                <span className="micro-label">Synthetic</span>
              ) : null}
            </div>
            <p>
              {proposal.team_name} · {humanize(proposal.mode)} mode ·{" "}
              {humanize(proposal.source)}
            </p>
            <small>
              {timestamp(proposal.created_at)}
              {proposal.is_current ? "" : " · Earlier state revision"}
            </small>
          </div>
          <button
            className={`button button-small ${canReview(proposal, session) ? "button-primary" : ""}`}
            onClick={() => onReview(proposal)}
          >
            {canReview(proposal, session)
              ? "Review proposal"
              : "Inspect proposal"}
            <Icon name="arrow" size={16} />
          </button>
        </article>
      ))}
    </div>
  );
}

export function ProposalModal({
  proposal,
  session,
  onClose,
  onSubmitted,
  avatarIndex = 0,
}) {
  const dialog = useRef(null);
  const submitStarted = useRef(false);
  const [review, setReview] = useState(null);
  const [reviewError, setReviewError] = useState(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [remaining, setRemaining] = useState(0);
  const actionable = canReview(proposal, session);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  useEffect(() => {
    if (!review) return undefined;
    const end = Date.now() + review.expires_in_seconds * 1000;
    const tick = () =>
      setRemaining(Math.max(0, Math.ceil((end - Date.now()) / 1000)));
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [review]);

  async function prepareReview() {
    if (reviewLoading || submitStarted.current) return;
    setReviewLoading(true);
    setReviewError(null);
    setConfirmed(false);
    try {
      const result = await post(
        "api/review",
        { team_key: proposal.team_key, proposal_id: proposal.id },
        session.csrf_token,
      );
      if (
        result.status !== "review_required" ||
        !result.review_nonce ||
        !Number.isFinite(result.expires_in_seconds)
      )
        throw new Error("The proposal could not be verified for submission.");
      setReview(result);
    } catch (error) {
      setReviewError(error.message);
    } finally {
      setReviewLoading(false);
    }
  }

  async function submit() {
    if (!review || !confirmed || remaining <= 0 || submitStarted.current)
      return;
    submitStarted.current = true;
    setSubmitting(true);
    try {
      const result = await post(
        "api/submit",
        {
          team_key: proposal.team_key,
          proposal_id: proposal.id,
          review_nonce: review.review_nonce,
          confirmation: true,
        },
        session.csrf_token,
      );
      setOutcome(result);
    } catch {
      setOutcome({
        status: "unknown",
        message:
          "The submission result could not be verified. Inspect the saved proposal before any further action.",
        retry_allowed: false,
      });
    } finally {
      setSubmitting(false);
      onSubmitted();
    }
  }

  const exact = review?.proposal || proposal;
  return (
    <dialog
      ref={dialog}
      className="proposal-modal"
      aria-labelledby="proposal-modal-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting) onClose();
      }}
    >
      <div className="modal-header">
        <h2 id="proposal-modal-title">
          {outcome ? "Submission result" : "Review proposal"}
        </h2>
        {session?.demo ? (
          <Badge value="prepared" label="Demo · No live action" />
        ) : null}
        <button
          className="icon-button"
          onClick={onClose}
          disabled={submitting}
          aria-label="Close proposal"
        >
          <Icon name="close" />
        </button>
      </div>
      <div className="modal-body">
        {outcome ? (
          <>
            <Notice
              kind={outcome.status === "confirmed" ? "success" : "warning"}
            >
              <strong>{humanize(outcome.status)}</strong>
              <p>
                {outcome.message ||
                  "Inspect the saved proposal for its current status."}
              </p>
            </Notice>
            {session?.demo || outcome.demo ? (
              <Notice>This was a fictional demo. No live team changed.</Notice>
            ) : null}
            <p className="muted">This control will not retry a submission.</p>
          </>
        ) : (
          <>
            <div className="modal-team">
              <Avatar name={proposal.team_name} index={avatarIndex} large />
              <div>
                <h3>{proposal.team_name}</h3>
                <p>
                  {humanize(exact.mode)} mode · {humanize(exact.status)}
                </p>
              </div>
            </div>
            <div className="exact-heading">
              <div>
                <h3>{exact.summary || humanize(exact.action)}</h3>
                <p>
                  Review the exact changes in this proposal before approval.
                </p>
              </div>
            </div>
            <dl className="proposal-facts">
              <div>
                <dt>Action</dt>
                <dd>{humanize(exact.action)}</dd>
              </div>
              <div>
                <dt>Mode</dt>
                <dd>{humanize(exact.mode)}</dd>
              </div>
              <div>
                <dt>State revision</dt>
                <dd>{exact.revision ?? "—"}</dd>
              </div>
              <div>
                <dt>Policy revision</dt>
                <dd>{exact.config_revision ?? "—"}</dd>
              </div>
            </dl>
            <Payload
              payload={exact.payload}
              names={{
                ...proposal.player_names,
                ...exact.player_names,
                ...Object.fromEntries(
                  (review?.players || []).map((player) => [
                    player.id,
                    player.name,
                  ]),
                ),
              }}
              current={review?.current_lineup}
            />
            {review?.policy ? (
              <>
                <div className="saved-controls">
                  <h3>Saved controls</h3>
                  <p>
                    <span className="check-circle">
                      <Icon name="check" size={14} />
                    </span>
                    {humanize(review.policy.mode)} mode
                    {review.policy.paused ? " · Paused" : ""}
                  </p>
                  <p>
                    <span className="check-circle">
                      <Icon name="check" size={14} />
                    </span>
                    Source and policy checked again before submission
                  </p>
                </div>
                <details className="exact-payload">
                  <summary>Current policy and limits</summary>
                  <pre>{JSON.stringify(review.policy, null, 2)}</pre>
                </details>
              </>
            ) : null}
            {reviewError ? <Notice kind="error">{reviewError}</Notice> : null}
            {!actionable ? (
              <Notice kind="warning">
                {!session?.actions_enabled
                  ? "Submission controls are disabled for this workspace."
                  : proposal.is_current !== true
                    ? "This proposal belongs to an earlier state revision."
                    : proposal.mode !== "review"
                      ? "This proposal does not use review mode."
                      : proposal.source === "http" &&
                          proposal.status !== "pending"
                        ? "Only a pending HTTP proposal can be submitted."
                        : proposal.source === "synthetic" &&
                            proposal.status !== "prepared"
                          ? "Only a prepared demo proposal can be submitted."
                          : "This proposal source does not support dashboard submission."}
              </Notice>
            ) : null}
            {session?.demo ? (
              <Notice>
                This proposal uses fictional team data. Demo submission does not
                contact ESPN.
              </Notice>
            ) : null}
            {review ? (
              <>
                <Notice kind="warning">
                  This approval applies only to the changes shown. Changed team
                  data requires a new review.
                </Notice>
                <div className="review-expiry">
                  {remaining > 0
                    ? `Review expires in ${remaining} seconds.`
                    : "This review has expired. Verify the proposal again."}
                </div>
                <label className="confirmation">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                    disabled={submitting || remaining <= 0}
                  />
                  <span>I approve this exact proposal.</span>
                </label>
              </>
            ) : null}
          </>
        )}
      </div>
      <div className="modal-footer">
        <button className="button" onClick={onClose} disabled={submitting}>
          {outcome ? "Close" : "Cancel"}
        </button>
        {!outcome && actionable ? (
          review && remaining > 0 ? (
            <button
              className="button button-primary"
              disabled={!confirmed || submitting}
              onClick={submit}
            >
              {submitting
                ? "Submitting…"
                : session?.demo
                  ? "Approve and submit demo"
                  : "Approve and submit"}
              <Icon name="arrow" size={17} />
            </button>
          ) : (
            <button
              className="button button-primary"
              onClick={prepareReview}
              disabled={reviewLoading}
            >
              {reviewLoading
                ? "Verifying…"
                : review
                  ? "Verify again"
                  : "Verify exact proposal"}
              <Icon name="arrow" size={17} />
            </button>
          )
        ) : null}
      </div>
      {submitting ? (
        <div className="submission-progress" role="status">
          Submission is in progress. Wait for the result.
        </div>
      ) : null}
    </dialog>
  );
}

function Payload({ payload, names, current }) {
  if (!payload || !Object.keys(payload).length)
    return <Notice>No exact changes are available in this record.</Notice>;
  const changes =
    current && payload.lineup
      ? lineupChanges(payload.lineup, current, names)
      : null;
  return (
    <section className="payload-section">
      <h3>Exact changes</h3>
      {changes ? (
        changes.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Current slot</th>
                  <th>Proposed slot</th>
                </tr>
              </thead>
              <tbody>
                {changes.map((change) => (
                  <tr key={change.id}>
                    <td>{change.name}</td>
                    <td>{change.before}</td>
                    <td>{change.after}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Notice>This lineup matches the current saved lineup.</Notice>
        )
      ) : payload.lineup && typeof payload.lineup === "object" ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Slot</th>
                <th>Player</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(payload.lineup).map(([slot, value]) => (
                <tr key={slot}>
                  <td>{slot}</td>
                  <td>
                    {names[value] ||
                      (value != null ? `Player ${value}` : "Empty")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <dl className="payload-fields">
        {Object.entries(payload)
          .filter(([key]) => key !== "lineup")
          .map(([key, value]) => (
            <div key={key}>
              <dt>{humanize(key)}</dt>
              <dd>
                {value == null ? (
                  "None"
                ) : typeof value === "object" ? (
                  <pre>{JSON.stringify(value, null, 2)}</pre>
                ) : names[value] ? (
                  `${names[value]} (${value})`
                ) : (
                  String(value)
                )}
              </dd>
            </div>
          ))}
      </dl>
      <details className="exact-payload">
        <summary>Exact stored payload</summary>
        <pre>{JSON.stringify(payload, null, 2)}</pre>
      </details>
    </section>
  );
}
