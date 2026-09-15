import test from "node:test";
import assert from "node:assert/strict";
import { readRoute, routeHash } from "../src/navigation.js";

test("team and analysis links survive serialization", () => {
  const route = { view: "Teams", team: "team-example", tab: "Analysis", status: "review" };
  assert.deepEqual(readRoute(routeHash(route)), route);
});
test("proposal filters survive serialization", () => {
  const route = { view: "Proposals", team: "team-example", tab: "Roster", status: "confirmed" };
  assert.deepEqual(readRoute(routeHash(route)), route);
});
test("unknown routes and unsafe identifiers use safe defaults", () => {
  assert.deepEqual(readRoute("#missing?team=%3Cscript%3E&tab=invalid&status=invalid"), {
    view: "Overview", team: "", tab: "Roster", status: "review",
  });
});
