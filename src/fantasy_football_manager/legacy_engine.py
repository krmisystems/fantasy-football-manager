"""Draft estimates from roster value and simulated opponent selections.

The model compares the next two user selections. It does not estimate win odds.
All projections and ADP values must come from the caller.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import random
from typing import Iterable


POSITIONS = ("QB", "RB", "WR", "TE", "DST", "K")
FLEX_POSITIONS = ("RB", "WR", "TE")
DEFAULT_STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1}
DEFAULT_CAPS = {"QB": 4, "RB": 8, "WR": 8, "TE": 3, "DST": 3, "K": 3}
BENCH_WEIGHTS = {"QB": 0.07, "RB": 0.23, "WR": 0.20, "TE": 0.12, "DST": 0.015, "K": 0.01}
POSITION_WEIGHTS = {"QB": 1.0, "RB": 1.0, "WR": 1.0, "TE": 1.0, "DST": 0.35, "K": 0.20}
DRAFT_STRATEGIES = {"balanced_value", "rb_priority", "wr_priority", "hero_rb", "zero_rb"}


def strategy_weight(strategy: str, position: str, position_rank: int,
                    draft_round: int, total_rounds: int) -> float:
    """Apply a soft preference. Position limits and starter rules remain unchanged."""
    if strategy == "rb_priority":
        return {"RB": 1.30, "WR": 0.95}.get(position, 1.0)
    if strategy == "wr_priority":
        return {"WR": 1.30, "RB": 0.95}.get(position, 1.0)
    if strategy == "hero_rb":
        if position == "RB":
            return 1.25 if position_rank == 0 else 0.70
        return 1.12 if position == "WR" else 1.0
    if strategy == "zero_rb":
        early = draft_round <= max(3, total_rounds // 2)
        if position == "RB":
            return 0.55 if early else 1.15
        return 1.15 if early and position in {"WR", "TE"} else 1.0
    return 1.0


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    position: str
    team: str
    projection: float
    adp: float
    uncertainty: float = 0.22
    injury_status: str = ""
    bye: object = None


def draft_slot(pick_no: int, teams: int = 14, snake: bool = True) -> int:
    """Return the one-based owner slot for a normal future pick."""
    if pick_no < 1 or teams < 1:
        raise ValueError("Pick numbers and team counts must be positive.")
    round_index, offset = divmod(pick_no - 1, teams)
    return teams - offset if snake and round_index % 2 else offset + 1


def minimum_missing(counts: dict, starters: dict, flex_eligible=FLEX_POSITIONS) -> int:
    """Count unfilled starters. Assign each player to one position or FLEX."""
    base = sum(max(0, starters.get(pos, 0) - counts.get(pos, 0)) for pos in POSITIONS)
    spare = sum(max(0, counts.get(pos, 0) - starters.get(pos, 0)) for pos in flex_eligible)
    return base + max(0, starters.get("FLEX", 0) - spare)


def can_draft(position: str, counts: dict, roster_size: int, rounds: int,
              starters: dict, caps: dict, flex_eligible=FLEX_POSITIONS) -> bool:
    """Check position limits and the number of remaining starter selections."""
    if position not in POSITIONS or roster_size >= rounds:
        return False
    if counts.get(position, 0) >= caps.get(position, rounds):
        return False
    updated = dict(counts)
    updated[position] = updated.get(position, 0) + 1
    return minimum_missing(updated, starters, flex_eligible) <= rounds - roster_size - 1


def _position(value: object) -> str:
    value = str(value or "").upper().strip()
    return {"D/ST": "DST", "DEF": "DST", "D": "DST", "PK": "K"}.get(value, value)


def _parse_players(rows: list[dict], warnings: list[str]) -> list[Player]:
    result = []
    seen = set()
    omitted = 0
    for row in rows:
        try:
            pid = str(row["id"])
            pos = _position(row.get("position"))
            projection = float(row["projection"])
            adp = float(row.get("adp") or 999)
            injury = str(row.get("injury_status") or "")
            default_uncertainty = 0.35 if injury.upper() in {"IR", "OUT", "PUP", "DOUBTFUL"} else 0.22
            uncertainty = float(row.get("uncertainty", default_uncertainty))
            if not pid or pos not in POSITIONS or not math.isfinite(projection) or projection < 0:
                raise ValueError("Invalid player data.")
            if not math.isfinite(adp) or adp <= 0:
                adp = 999.0
            if not math.isfinite(uncertainty):
                uncertainty = default_uncertainty
            if pid in seen:
                omitted += 1
                continue
            seen.add(pid)
            result.append(Player(pid, str(row.get("name") or pid), pos, str(row.get("team") or ""),
                                 projection, adp, max(0.0, min(1.0, uncertainty)), injury, row.get("bye")))
        except (KeyError, TypeError, ValueError):
            omitted += 1
    if omitted:
        warnings.append(f"The model omitted {omitted} duplicate or invalid player rows.")
    return result


def _replacement(players: list[Player], teams: int, starters: dict, bench: int,
                 flex_eligible=FLEX_POSITIONS) -> dict[str, float]:
    # Compare starters with the last expected league starter at each position.
    # A deep waiver baseline would overstate RB scarcity in this short horizon.
    flex_share = {"RB": 0.45, "WR": 0.50, "TE": 0.05}
    if set(flex_eligible) != set(FLEX_POSITIONS):
        flex_share = {pos: 1 / len(flex_eligible) for pos in flex_eligible}
    values = {}
    for pos in POSITIONS:
        pool = sorted((p.projection for p in players if p.position == pos), reverse=True)
        rank = teams * starters.get(pos, 0) + round(teams * starters.get("FLEX", 0) * flex_share.get(pos, 0))
        values[pos] = pool[min(max(rank, 1), len(pool)) - 1] if pool else 0.0
    values["FLEX"] = max((values[pos] for pos in flex_eligible), default=0.0)
    return values


def roster_utility(roster: Iterable[Player | dict], starters: dict, replacement: dict,
                   outcomes: dict[str, float] | None = None, strategy: str = "balanced_value",
                   draft_round: int = 1, total_rounds: int = 14,
                   flex_eligible=FLEX_POSITIONS) -> float:
    """Estimate value above replacement. Discount bench players and streamable positions.

    Assign starters from supplied projections before evaluating sampled outcomes.
    This prevents a backup from receiving value through knowledge of future results.
    This score is not a direct forecast of team points. Each FLEX player is used once.
    """
    grouped = {pos: [] for pos in POSITIONS}
    for player in roster:
        if isinstance(player, dict):
            pos = _position(player.get("position"))
            pid = str(player.get("id", ""))
            points = float(player.get("projection", 0))
        else:
            pos, pid, points = player.position, player.id, player.projection
        if pos in grouped:
            score = outcomes.get(pid, points) if outcomes is not None else points
            grouped[pos].append((points, score, pid))
    utility = 0.0
    extra = []
    for pos in POSITIONS:
        ordered = sorted(grouped[pos], key=lambda item: (item[0], item[2]), reverse=True)
        count = starters.get(pos, 0)
        baseline = replacement.get(pos, 0.0)
        utility += sum(max(0.0, score - baseline) * POSITION_WEIGHTS[pos]
                       * strategy_weight(strategy, pos, rank, draft_round, total_rounds)
                       for rank, (_, score, _) in enumerate(ordered[:count]))
        extra.extend((projection, score, pid, pos, rank)
                     for rank, (projection, score, pid) in enumerate(ordered) if rank >= count)
    flex_pool = sorted((item for item in extra if item[3] in flex_eligible),
                       key=lambda item: (item[0], item[2]), reverse=True)
    flex_used = set()
    for _, score, pid, pos, rank in flex_pool[:starters.get("FLEX", 0)]:
        utility += (max(0.0, score - replacement.get("FLEX", 0.0))
                    * strategy_weight(strategy, pos, rank, draft_round, total_rounds))
        flex_used.add(pid)
    for _, score, pid, pos, rank in extra:
        if pid not in flex_used:
            utility += (max(0.0, score - replacement.get(pos, 0.0) * 0.70) * BENCH_WEIGHTS[pos]
                        * strategy_weight(strategy, pos, rank, draft_round, total_rounds))
    return utility


class _Market:
    def __init__(self, players: list[Player], starters: dict, caps: dict, rounds: int, teams: int,
                 strategy: str = "balanced_value", draft_round: int = 1,
                 flex_eligible=FLEX_POSITIONS, max_adp_reach: float | None = None):
        self.players = {p.id: p for p in players}
        self.adp_order = {pos: sorted((p for p in players if p.position == pos), key=lambda p: (p.adp, p.id))
                          for pos in POSITIONS}
        self.value_order = {pos: sorted((p for p in players if p.position == pos),
                                       key=lambda p: (-p.projection, p.adp, p.id)) for pos in POSITIONS}
        self.starters, self.caps, self.rounds, self.teams = starters, caps, rounds, teams
        self.strategy, self.draft_round = strategy, draft_round
        self.flex_eligible, self.max_adp_reach = tuple(flex_eligible), max_adp_reach

    def utility(self, roster: Iterable[Player | dict], replacement: dict,
                outcomes: dict[str, float] | None = None) -> float:
        return roster_utility(roster, self.starters, replacement, outcomes,
                              self.strategy, self.draft_round, self.rounds, self.flex_eligible)

    def within_reach(self, player: Player, pick_no: int) -> bool:
        return self.max_adp_reach is None or player.adp - pick_no <= self.max_adp_reach

    def own_positions(self, available: set[str], counts: dict, roster_size: int) -> set[str]:
        """Reserve DST and K for the final three selections when a legal alternative exists."""
        legal = {pos for pos in POSITIONS
                 if can_draft(pos, counts, roster_size, self.rounds, self.starters, self.caps, self.flex_eligible)
                 and any(player.id in available for player in self.value_order[pos])}
        if self.rounds - roster_size > 3:
            alternatives = legal.difference({"DST", "K"})
            if alternatives:
                return alternatives
        return legal

    def opponent_pick(self, available: set[str], counts: dict, roster_size: int,
                      pick_no: int, rng: random.Random) -> Player | None:
        best = None
        best_score = -math.inf
        round_no = (pick_no - 1) // self.teams + 1
        for pos in POSITIONS:
            if not can_draft(pos, counts, roster_size, self.rounds, self.starters, self.caps, self.flex_eligible):
                continue
            count = counts.get(pos, 0)
            need = self.starters.get(pos, 0) - count
            bias = 4.0 + 0.8 * round_no if need > 0 else 0.0
            if need <= 0:
                bias -= {"QB": 36, "TE": 24, "DST": 65, "K": 75}.get(pos, 5 * max(1, -need))
            if pos in {"DST", "K"} and roster_size < self.rounds - 3:
                bias -= 25
            # Gumbel noise provides a stochastic ranking around ADP.
            temperature = 4.0 + min(15.0, pick_no * 0.07)
            found = 0
            for player in self.adp_order[pos]:
                if player.id not in available:
                    continue
                noise = -math.log(-math.log(max(1e-12, min(1 - 1e-12, rng.random()))))
                score = -player.adp + bias + temperature * noise
                if score > best_score:
                    best, best_score = player, score
                found += 1
                if found >= 4:
                    break
        return best

    def advance(self, available: set[str], counts: dict[int, Counter], sizes: dict[int, int],
                start: int, end: int, snake: bool, rng: random.Random, skip_slot: int | None = None) -> None:
        for pick_no in range(start, end):
            owner = draft_slot(pick_no, self.teams, snake)
            if owner == skip_slot:
                continue
            player = self.opponent_pick(available, counts[owner], sizes[owner], pick_no, rng)
            if player is not None:
                available.remove(player.id)
                counts[owner][player.position] += 1
                sizes[owner] += 1

    def best_addition(self, available: set[str], roster: list[Player], counts: dict,
                      replacement: dict, pick_no: int) -> Player | None:
        best, best_value = None, -math.inf
        eligible = self.own_positions(available, counts, len(roster))
        for pos in POSITIONS:
            if pos not in eligible:
                continue
            # Utility is monotonic within one position. Only its best player is needed.
            player = next((p for p in self.value_order[pos] if p.id in available and self.within_reach(p, pick_no)), None)
            if player is None:
                continue
            value = self.utility(roster + [player], replacement)
            if value > best_value or (value == best_value and best and player.adp < best.adp):
                best, best_value = player, value
        return best


def run_batch(players: list[dict], picks: list[dict], config: dict,
              trials: int = 80, seed: int | None = None) -> dict:
    """Run an independent batch. Merge its sums only with identical input state.

    score_sum / simulation_count gives the mean conditional two-pick score.
    survival_count / availability_count gives survival after the user passes.
    availability_count / trials gives availability at the next user selection.
    """
    warnings = []
    teams = int(config.get("teams", 14))
    slot = int(config.get("slot", 1))
    snake = bool(config.get("snake", True))
    starters = {pos: 0 for pos in (*POSITIONS, "FLEX")}
    starters.update({_position(k): int(v) for k, v in config.get("starters", DEFAULT_STARTERS).items()})
    caps = dict(DEFAULT_CAPS)
    caps.update({_position(k): int(v) for k, v in config.get("caps", {}).items()})
    bench = int(config.get("bench", 5))
    rounds = int(config.get("rounds", sum(starters.values()) + bench))
    trials = int(trials)
    strategy = str(config.get("strategy", "balanced_value"))
    flex_eligible = tuple(config.get("flex_eligible", FLEX_POSITIONS))
    max_adp_reach = config.get("max_adp_reach")
    if strategy not in DRAFT_STRATEGIES:
        raise ValueError("Select a supported draft strategy.")
    if not flex_eligible or set(flex_eligible).difference(POSITIONS):
        raise ValueError("FLEX eligibility must use supported positions.")
    if max_adp_reach is not None and (not math.isfinite(float(max_adp_reach)) or float(max_adp_reach) < 0):
        raise ValueError("The ADP reach limit must be a nonnegative number.")
    if teams < 1 or not 1 <= slot <= teams or rounds < 1 or trials < 1:
        raise ValueError("Check teams, slot, rounds, and trials. Each value must be positive and valid.")
    if any(value < 0 for value in starters.values()) or any(value < 0 for value in caps.values()):
        raise ValueError("Starter counts and position limits cannot be negative.")
    if sum(starters.values()) > rounds:
        raise ValueError("The draft needs enough rounds to fill all starters.")
    parsed = _parse_players(players, warnings)
    by_id = {p.id: p for p in parsed}
    counts = {owner: Counter() for owner in range(1, teams + 1)}
    sizes = {owner: 0 for owner in range(1, teams + 1)}
    my_roster = []
    selected = set()
    pick_numbers = set()
    for pick in sorted(picks, key=lambda row: int(row.get("pick_no", 0))):
        number = int(pick.get("pick_no", 0))
        if number < 1 or number > teams * rounds or number in pick_numbers:
            warnings.append("The pick log contains an invalid or duplicate pick number.")
            continue
        pick_numbers.add(number)
        owner = int(pick.get("slot") or draft_slot(number, teams, snake))
        pid = str(pick.get("player_id", ""))
        if owner not in counts or pid in selected:
            warnings.append("The pick log contains an invalid owner or duplicate player.")
            continue
        selected.add(pid)
        sizes[owner] += 1
        player = by_id.get(pid)
        if player is None:
            warnings.append(f"Player data is missing for drafted player {pid}. Roster estimates can be incomplete.")
            continue
        counts[owner][player.position] += 1
        if owner == slot:
            my_roster.append(player)
    current_pick = max(pick_numbers, default=0) + 1
    if pick_numbers and len(pick_numbers) < current_pick - 1:
        warnings.append("The pick log has gaps. The model assumes that the latest recorded pick sets the draft position.")
    remaining_picks = [number for number in range(current_pick, teams * rounds + 1)
                       if draft_slot(number, teams, snake) == slot]
    next_pick = remaining_picks[0] if remaining_picks else None
    following_pick = remaining_picks[1] if len(remaining_picks) > 1 else None
    available = set(by_id).difference(selected)
    result = {"recommendations": [], "trials": 0, "current_pick": current_pick,
              "my_next_pick": next_pick, "following_pick": following_pick,
              "available_count": len(available), "warnings": warnings,
              "model": "Monte Carlo opponent draft with two-pick roster lookahead",
              "score_label": "Estimated roster value above replacement",
              "survival_label": "Estimated availability at your following pick if you pass",
              "completed": next_pick is None}
    if next_pick is None:
        return result
    if not parsed:
        warnings.append("No valid player projections are available.")
        return result
    if sizes[slot] != len(my_roster):
        warnings.append("Recommendations cannot use position limits until all players on your roster have player data.")
        return result
    for pos in POSITIONS:
        if starters.get(pos, 0) > caps.get(pos, rounds):
            warnings.append(f"The {pos} position limit cannot fill the required starters.")
            return result
    replacement = _replacement(parsed, teams, starters, bench, flex_eligible)
    result["replacement_projections"] = {pos: round(value, 2) for pos, value in replacement.items()}
    market = _Market(parsed, starters, caps, rounds, teams, strategy, (next_pick - 1) // teams + 1,
                     flex_eligible, max_adp_reach)
    own_counts = counts[slot]
    baseline = market.utility(my_roster, replacement)
    eligible_positions = market.own_positions(available, own_counts, len(my_roster))
    legal = [p for p in parsed if p.id in available and p.position in eligible_positions]
    result["blocked_candidates"] = [{"id": p.id, "name": p.name, "position": p.position, "adp": p.adp,
                                      "reason": "ADP reach exceeds the configured limit."}
                                     for p in legal if not market.within_reach(p, next_pick)]
    legal = [p for p in legal if market.within_reach(p, next_pick)]
    if not legal:
        warnings.append("No available player can satisfy the current roster limits and starter requirements.")
        return result
    immediate = {p.id: market.utility(my_roster + [p], replacement) - baseline for p in legal}
    def shortlist_value(player: Player) -> float:
        # This prior only selects candidates. Simulations estimate their actual availability.
        spread = 5 + player.adp * 0.08
        prior = 1 / (1 + math.exp(max(-30, min(30, (next_pick - player.adp) / spread))))
        if next_pick == current_pick:
            prior = 1.0
        return immediate[player.id] * (0.05 + 0.95 * prior)
    ordered = sorted(legal, key=lambda p: (-shortlist_value(p), p.adp, p.id))
    candidate_limit = max(12, min(48, int(config.get("candidate_limit", 36))))
    # Keep market favorites even when the positional value model ranks them lower.
    # Otherwise the model could omit an elite player who falls below ADP.
    adp_candidates = sorted(legal, key=lambda p: (p.adp, p.id))[:min(24, candidate_limit)]
    candidates = list(adp_candidates)
    candidate_ids = {p.id for p in candidates}
    for candidate in ordered:
        if len(candidates) >= candidate_limit:
            break
        if candidate.id not in candidate_ids:
            candidates.append(candidate)
            candidate_ids.add(candidate.id)
    # Retain three projected options per legal position, including value near the replacement baseline.
    for pos in POSITIONS:
        position_candidates = sorted((p for p in legal if p.position == pos),
                                     key=lambda p: (-p.projection, p.adp, p.id))[:3]
        for candidate in position_candidates:
            if candidate.id not in candidate_ids:
                candidates.append(candidate)
                candidate_ids.add(candidate.id)
    result["candidate_count"] = len(candidates)
    accum = {p.id: {"score_sum": 0.0, "score_sq_sum": 0.0, "simulation_count": 0,
                    "availability_count": 0, "survival_count": 0} for p in candidates}
    rng = random.Random(seed)
    for _ in range(trials):
        trial_available = set(available)
        trial_counts = {owner: Counter(value) for owner, value in counts.items()}
        trial_sizes = dict(sizes)
        market.advance(trial_available, trial_counts, trial_sizes, current_pick, next_pick, snake, rng)
        present = [p for p in candidates if p.id in trial_available]
        for player in present:
            accum[player.id]["availability_count"] += 1
        branch_seed = rng.getrandbits(64)
        shocks = {p.id: rng.gauss(0.0, p.projection * p.uncertainty) for p in parsed}
        outcomes = {p.id: max(0.0, p.projection + shocks[p.id]) for p in parsed}
        opposite_outcomes = {p.id: max(0.0, p.projection - shocks[p.id]) for p in parsed}
        trial_base = market.utility(my_roster, replacement, outcomes)
        opposite_base = market.utility(my_roster, replacement, opposite_outcomes)
        if following_pick is not None:
            pass_available = set(trial_available)
            pass_counts = {owner: Counter(value) for owner, value in trial_counts.items()}
            pass_sizes = dict(trial_sizes)
            market.advance(pass_available, pass_counts, pass_sizes, next_pick + 1, following_pick,
                           snake, random.Random(branch_seed), skip_slot=slot)
            for player in present:
                if player.id in pass_available:
                    accum[player.id]["survival_count"] += 1
        for player in present:
            roster = my_roster + [player]
            if following_pick is not None:
                branch_available = set(trial_available)
                branch_available.remove(player.id)
                branch_counts = {owner: Counter(value) for owner, value in trial_counts.items()}
                branch_sizes = dict(trial_sizes)
                branch_counts[slot][player.position] += 1
                branch_sizes[slot] += 1
                market.advance(branch_available, branch_counts, branch_sizes, next_pick + 1, following_pick,
                               snake, random.Random(branch_seed), skip_slot=slot)
                addition = market.best_addition(branch_available, roster, branch_counts[slot], replacement, following_pick)
                if addition is not None:
                    roster.append(addition)
            # Pair opposite projection shocks to reduce sampling noise.
            # The next selection still uses supplied projections, not future outcomes.
            score = 0.5 * (market.utility(roster, replacement, outcomes) - trial_base
                           + market.utility(roster, replacement, opposite_outcomes) - opposite_base)
            values = accum[player.id]
            values["simulation_count"] += 1
            values["score_sum"] += score
            values["score_sq_sum"] += score * score
    result["trials"] = trials
    if current_pick != next_pick:
        warnings.append("Your selection is not current. Each score assumes that the player reaches your next pick.")
    warnings.append("Estimates depend on the supplied projections, ADP, roster settings, and opponent model.")
    warnings.append("Scores compare your next two selections. They do not estimate championship odds.")
    warnings.append("The draft policy reserves DST and K for the final three selections unless roster limits require an earlier pick.")
    if any(p.injury_status.upper() not in {"", "ACTIVE", "HEALTHY"} for p in candidates):
        warnings.append("Review injury status before each selection. The model does not verify live injury reports.")
    recommendations = []
    for player in candidates:
        values = accum[player.id]
        n = values["simulation_count"]
        if not n:
            continue
        mean = values["score_sum"] / n
        variance = max(0.0, values["score_sq_sum"] / n - mean * mean)
        survival = values["survival_count"] / values["availability_count"] if following_pick is not None else None
        updated_counts = dict(own_counts)
        updated_counts[player.position] = updated_counts.get(player.position, 0) + 1
        fills = minimum_missing(updated_counts, starters, flex_eligible) < minimum_missing(own_counts, starters, flex_eligible)
        role = "Fills an open starter position." if fills else "Adds roster depth or improves a starter."
        timing = ("This is your final selection." if survival is None else
                  f"Estimated chance to reach your following pick: {survival:.0%}.")
        reason = f"{role} {timing}"
        if player.position in {"DST", "K"}:
            reason += " The model discounts value at this position because replacement options are common."
        recommendations.append({"id": player.id, "name": player.name, "position": player.position,
                                "team": player.team, "projection": player.projection, "adp": player.adp,
                                "injury_status": player.injury_status, "bye": player.bye,
                                "score": mean, "score_se": math.sqrt(variance / n),
                                "immediate_value": immediate[player.id], "survival_next_pick": survival,
                                "availability_at_pick": values["availability_count"] / trials,
                                "trial_count": trials, "reason": reason, **values})
    recommendations.sort(key=lambda item: (-item["score"], -item["availability_at_pick"],
                                            item["survival_next_pick"] or 0, item["adp"]))
    result["recommendations"] = recommendations
    result["warnings"] = list(dict.fromkeys(warnings))
    return result


def merge_batches(previous: dict | None, batch: dict) -> dict:
    """Combine batches for identical players, picks, and configuration.

    The caller must reset the aggregate when any input changes.
    """
    if previous is None:
        return batch
    if previous.get("analysis_fingerprint") != batch.get("analysis_fingerprint"):
        raise ValueError("Reset the aggregate when analysis inputs change.")
    if any(previous.get(key) != batch.get(key) for key in ("current_pick", "my_next_pick", "following_pick", "available_count")):
        raise ValueError("Reset the aggregate when the draft state changes.")
    if batch.get("completed"):
        return dict(batch, trials=0)
    combined = dict(batch)
    combined["trials"] = previous["trials"] + batch["trials"]
    items = {row["id"]: dict(row) for row in previous["recommendations"]}
    for row in batch["recommendations"]:
        if row["id"] not in items:
            items[row["id"]] = dict(row)
            continue
        entry = items[row["id"]]
        for key in ("score_sum", "score_sq_sum", "simulation_count", "availability_count", "survival_count", "trial_count"):
            entry[key] += row[key]
    for entry in items.values():
        n = entry["simulation_count"]
        entry["score"] = entry["score_sum"] / n
        variance = max(0.0, entry["score_sq_sum"] / n - entry["score"] ** 2)
        entry["score_se"] = math.sqrt(variance / n)
        entry["availability_at_pick"] = entry["availability_count"] / combined["trials"]
        entry["survival_next_pick"] = (entry["survival_count"] / entry["availability_count"]
                                       if combined["following_pick"] is not None else None)
        if entry["survival_next_pick"] is not None:
            # Keep the static roster reason and replace the old probability.
            prefix = entry["reason"].split(" Estimated chance")[0]
            entry["reason"] = f"{prefix} Estimated chance to reach your following pick: {entry['survival_next_pick']:.0%}."
    combined["recommendations"] = sorted(items.values(), key=lambda item: (-item["score"], -item["availability_at_pick"],
                                                                           item["survival_next_pick"] or 0, item["adp"]))
    return combined
