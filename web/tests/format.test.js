import assert from "node:assert/strict";
import test from "node:test";
import {
  points,
  age,
  canReview,
  lineupChanges,
  queryString,
} from "../src/format.js";

test("missing and non-finite projections stay unknown", () => {
  for (const value of [null, undefined, NaN, Infinity, "0"])
    assert.equal(points(value), "—");
  assert.equal(points(0), "0.0");
  assert.equal(points(15.37), "15.4");
});

test("submission controls require enabled mode and current supported proposal", () => {
  const proposal = {
    status: "pending",
    is_current: true,
    source: "http",
    mode: "review",
  };
  assert.equal(
    canReview(proposal, { actions_enabled: true, demo: false }),
    true,
  );
  for (const altered of [
    { status: "unknown" },
    { status: "prepared" },
    { mode: "automatic" },
    { mode: "advisory" },
    { is_current: false },
    { source: "browser" },
    { source: "synthetic" },
  ]) {
    assert.equal(
      canReview(
        { ...proposal, ...altered },
        { actions_enabled: true, demo: false },
      ),
      false,
    );
  }
  assert.equal(canReview(proposal, { actions_enabled: false }), false);
  assert.equal(canReview(proposal, undefined), false);
  assert.equal(
    canReview(
      { ...proposal, source: "synthetic", status: "prepared" },
      { actions_enabled: true, demo: true },
    ),
    true,
  );
});

test("exact lineup changes retain both sides of a swap and omit unchanged players", () => {
  const changes = lineupChanges(
    { QB1: "a", TE1: "c" },
    { QB1: "a", TE1: "b" },
    { a: "Quarterback", b: "Current TE", c: "New TE" },
  );
  assert.deepEqual(changes, [
    { id: "b", name: "Current TE", before: "TE1", after: "BENCH" },
    { id: "c", name: "New TE", before: "BENCH", after: "TE1" },
  ]);
  assert.deepEqual(lineupChanges({ QB1: "a" }, { QB1: "a" }), []);
});

test("query encoding preserves filter boundaries and false booleans", () => {
  const params = new URLSearchParams(
    queryString({
      query: "A&B=TE",
      rostered_only: false,
      offset: 0,
      team_key: "",
      position: null,
    }),
  );
  assert.equal(params.get("query"), "A&B=TE");
  assert.equal(params.get("rostered_only"), "false");
  assert.equal(params.get("offset"), "0");
  assert.equal(params.has("team_key"), false);
});

test("unknown source time is not rendered as fresh", () => {
  assert.equal(age(null), "No saved snapshot");
  assert.equal(age(50), "Less than a minute ago");
  assert.equal(age(3600), "1 hr ago");
});
