"""Synthetic checks for draft completion with exact player eligibility."""

from collections import Counter
from datetime import datetime, timezone
from itertools import combinations, permutations
import random

from fantasy_football_manager.feasibility import roster_can_complete
from fantasy_football_manager.models import LeagueSnapshot, Player, Rules, Source, Team


def player(pid, position, eligible=None):
    return Player(id=pid, name=f"Synthetic {pid}", position=position,
                  eligible_positions=eligible or [position], availability="ACTIVE")


def fixture(players, own=(), other=(), *, starters=None, caps=None, flex=None, bench=0):
    starters = starters or {"RB": 1, "WR": 1, "FLEX": 1}
    rules = Rules(teams=2, slot=1, starters=starters, rounds=sum(starters.values()) + bench,
                  bench=bench, caps=caps or {"RB": 8, "WR": 8, "QB": 4, "TE": 3, "DST": 3, "K": 3},
                  flex_eligible=flex or ["RB", "WR", "TE"])
    return LeagueSnapshot(league_id="synthetic-feasibility", team_id="a", season=2026,
                          source=Source(provider="synthetic", synthetic=True, observed_at=datetime.now(timezone.utc)),
                          rules=rules, players=players,
                          teams=[Team(id="a", name="Synthetic A", slot=1, roster_ids=list(own)),
                                 Team(id="b", name="Synthetic B", slot=2, roster_ids=list(other))])


def test_cross_position_eligibility_can_fill_flex_with_a_different_primary_position():
    state = fixture([player("rb", "RB"), player("wr", "WR"), player("dual", "RB", ["RB", "WR"])],
                    own=["rb", "wr"], caps={"RB": 2, "WR": 1}, flex=["WR"])
    assert roster_can_complete(state, ["rb", "wr"])


def test_remaining_primary_cap_blocks_an_otherwise_eligible_future_player():
    state = fixture([player("rb-a", "RB"), player("rb-b", "RB"), player("qb", "QB")],
                    own=["rb-a"], starters={"RB": 1, "FLEX": 1}, caps={"RB": 1, "QB": 4}, flex=["RB"])
    assert not roster_can_complete(state, ["rb-a"])


def test_missing_required_position_in_actual_pool_prevents_completion():
    state = fixture([player("rb", "RB"), player("qb", "QB")], own=["rb"],
                    starters={"RB": 1, "FLEX": 1}, caps={"RB": 2, "QB": 4}, flex=["RB"])
    assert not roster_can_complete(state, ["rb"])


def test_players_owned_elsewhere_or_in_reserve_are_not_future_selections():
    state = fixture([player("rb", "RB"), player("wr", "WR"), player("reserve", "WR")],
                    own=["rb"], other=["wr"], starters={"RB": 1, "WR": 1})
    state.teams[1].reserve_ids = ["reserve"]
    assert not roster_can_complete(state, ["rb"])
    assert not roster_can_complete(state, ["rb", "wr"])


def test_proposed_player_is_not_counted_again_as_a_future_player():
    state = fixture([player("rb", "RB"), player("dual", "RB", ["RB", "WR"])], own=["rb"])
    assert not roster_can_complete(state, ["rb", "dual"])


def test_future_selections_cannot_exceed_remaining_roster_slots():
    state = fixture([player("qb-a", "QB"), player("qb-b", "QB"), player("qb-c", "QB"),
                     player("wr-a", "WR"), player("wr-b", "WR")],
                    own=["qb-a", "qb-b", "qb-c"], starters={"QB": 1, "WR": 2}, bench=1)
    assert not roster_can_complete(state, ["qb-a", "qb-b", "qb-c"])


def test_existing_dual_player_can_be_reassigned_to_preserve_a_future_selection():
    state = fixture([player("dual", "RB", ["RB", "WR"]), player("rb", "RB"), player("te", "TE")],
                    own=["dual", "rb"])
    assert roster_can_complete(state, ["dual", "rb"])


def test_duplicate_unknown_and_over_cap_proposed_rosters_are_rejected():
    state = fixture([player("a", "WR"), player("b", "WR")], starters={"WR": 1}, caps={"WR": 1})
    assert not roster_can_complete(state, ["a", "a"])
    assert not roster_can_complete(state, ["missing"])
    assert not roster_can_complete(state, ["a", "b"])


def test_structural_completion_does_not_assume_future_injury_clearance():
    state = fixture([player("rb", "RB"), player("wr", "WR")], own=["rb"], starters={"RB": 1, "WR": 1})
    state.players[1].availability = "OUT"
    assert roster_can_complete(state, ["rb"])


def test_flow_matches_exhaustive_roster_and_slot_assignments():
    rng = random.Random(302)
    for _ in range(24):
        players = [player(f"p{i}", rng.choice(["RB", "WR"]), rng.choice([["RB"], ["WR"], ["RB", "WR"]]))
                   for i in range(6)]
        own = ["p0", "p1"]
        state = fixture(players, own=own, caps={"RB": 3, "WR": 3}, bench=1)
        by_id = {p.id: p for p in players}
        slots = list(state.rules.lineup_slots().values())
        expected = False
        for count in range(state.rules.roster_size - len(own) + 1):
            for additions in combinations(["p2", "p3", "p4", "p5"], count):
                proposed = own + list(additions)
                counts = Counter(by_id[pid].position for pid in proposed)
                if any(n > state.rules.caps[position] for position, n in counts.items()):
                    continue
                if any(all(set(by_id[pid].eligible_positions).intersection(eligible)
                           for pid, eligible in zip(assignment, slots))
                       for assignment in permutations(proposed, len(slots))):
                    expected = True
        assert roster_can_complete(state, own) == expected
