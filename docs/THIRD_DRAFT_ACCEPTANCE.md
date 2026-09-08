# Third draft acceptance

**Status: Verified visible completion with failures and operator interventions. Final server sync is pending.**

The visible draft history contains all 160 selections.
The selected roster contains 16 players: 13 manager-confirmed selections and three operator-confirmed ESPN Autopicks.
The separate host-browser fallback submitted zero `DRAFT` clicks.
This run does not establish unattended draft completion.

## Runtime and scope

The league used a 10-team PPR snake draft with 16 rounds.
The selected team drafted from slot 10.
The executor used installed v0.3.0 with a private bootstrap and operator recovery changes.
It did not use an unchanged released wheel or the final corrected source.
The later source tests provide separate regression evidence.

## Selection results

| Execution source | Overall picks | Count |
|---|---|---|
| Manager submission with confirmed platform observation | 10, 11, 30, 31, 50, 51, 70, 71, 90, 91, 110, 111, 130 | 13 |
| ESPN Autopick, confirmed by the operator | 131, 150, 151 | 3 |
| Separate host-browser fallback `DRAFT` click | None | 0 |

Platform fallback selections are not manager-confirmed submissions.
No latency or general success-rate claim is derived from this trial.

## Failures and interventions

| Stage | Failure or limitation | Intervention and observed result |
|---|---|---|
| Startup | An API team name contained trailing whitespace. The visible roster option did not contain that whitespace. | The operator normalized the private runtime's team-name mapping. Exact team identifiers and roster checks remained in effect. |
| First turn | An initial preflight did not find a visible enabled `DRAFT` button. | The check failed before authorization. A later loop confirmed pick 10. |
| After pick 94 | The normal worker stops after its own roster is complete. It does not wait for every league selection. | The operator made a planned restart with no pending claim. A private read-only observation tail extended final-history collection. |
| Pick 131 | A D/ST autocomplete regex contained an unescaped slash. Playwright rejected the selector before the player submission. | The worker stopped with no awaiting claim. ESPN Autopick made selection 131. |
| Final two turns | The fallback handoff did not produce a host-browser submission before the turns expired. | ESPN Autopick made selections 150 and 151. The operator verified both selections. |

One controller can hold a shared browser profile lease at a time.
ESPN also disconnected the separate Chrome draft session while the server held the draft connection.
That second browser could not serve as a simultaneous live standby in this trial.
Operator recovery must account for the current controller and its pending claims.
The fallback handoff in this trial did not establish reliable recovery before the next turn.

## Source regression checks

The current source strips surrounding whitespace from the chosen API team name.
The [waiting-room unit tests](../tests/test_espn_browser.py) exercise an unselected team's trailing whitespace.
The [public draft Chrome fixture](../tests/test_espn_public_draft_integration.py) also includes that mismatch.
These checks retain exact member, team, and roster identity requirements.

The current source escapes slash delimiters in dynamic Playwright regex selectors.
The [D/ST autocomplete Chrome test](../tests/test_browser_integration.py) reproduces the failed selector with a fictional player.
Both `D/ST` and `DST` display variants failed before the fix and passed after it.
The test also verifies that wrong-team and wrong-position suggestions receive zero clicks.
The [browser implementation](../src/fantasy_football_manager/espn_browser.py) contains both fixes.

The complete local suite passed **611 tests**, with **2 skipped**, in **35.63 seconds**.
The run used Windows, Python 3.12.13, and `FFM_BROWSER_TESTS=1`.
It included **17 isolated Chrome cases**: seven draft cases and ten season cases.
The isolated pages use fictional data and intercepted requests.
These tests did not submit changes to a live league.

```powershell
$env:FFM_BROWSER_TESTS = "1"
uv run pytest -q
```

## Final evidence and limits

| Check | Evidence state |
|---|---|
| Visible complete league history | Verified: 160 selections. |
| Selected roster | Verified: 16 players, with execution sources separated above. |
| Final server sync and stored-history comparison | Pending. The visible completion does not establish server reconciliation. |
| Season handoff for this roster | Pending. No result is claimed here. |
| Unchanged installed v0.3.0 live execution | Not Tested by this modified runtime. |
| Final corrected source in a live draft | Not Tested. The source fixes passed isolated regression tests after the failures. |
| Unattended completion and automatic fallback recovery | Not established. Operator interventions were required. |

The [compatibility matrix](ESPN_COMPATIBILITY.md) records supported layouts and earlier failures.
The [multi-team acceptance plan](MULTI_TEAM_ACCEPTANCE.md) defines further trials.
Live waivers, drops, trades, and automatic week rollover remain outside the implemented action scope.
Private receipts and captures remain outside the public repository.
This report contains no account, league, team, member, or proposal identifiers.
