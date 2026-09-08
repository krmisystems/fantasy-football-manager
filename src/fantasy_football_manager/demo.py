"""Fictional data for repeatable local demonstrations."""

from datetime import datetime, timezone

from .models import Budget, LeagueSnapshot, Player, Rules, Source, Team


def make_demo(mode: str = "season") -> LeagueSnapshot:
    if mode not in {"season", "draft"}:
        raise ValueError("Demo mode must be season or draft.")
    players = []
    for position, count, base in [("QB", 42, 345), ("RB", 98, 305), ("WR", 112, 320), ("TE", 42, 240), ("DST", 32, 145), ("K", 32, 150)]:
        for index in range(count):
            projected = max(25, base - index * (2.7 if position in {"RB", "WR"} else 4))
            weekly = max(.5, round(projected / 17 + ((index % 5) - 2) * 1.4, 2))
            players.append(Player(id=f"demo-{position.lower()}-{index + 1:03}", name=f"Fictional {position} {index + 1:03}",
                                  position=position, team=f"D{index % 32 + 1:02}", projection=projected,
                                  weekly_projection=weekly, weekly_floor=round(weekly * .65, 2),
                                  weekly_ceiling=round(weekly * 1.4, 2), availability="ACTIVE", bye=index % 10 + 5))
    ranked = sorted(players, key=lambda p: p.projection, reverse=True)
    for index, player in enumerate(ranked):
        player.adp = index + 1
    rules = Rules()
    teams = [Team(id=f"demo-team-{i}", name=f"Fictional Team {i}", slot=i) for i in range(1, 15)]
    if mode == "season":
        pools = {pos: [p for p in players if p.position == pos] for pos in rules.caps}
        positions = ["QB", "RB", "RB", "WR", "WR", "TE", "RB", "DST", "K", "WR", "RB", "WR", "QB", "TE"]
        for pos in positions:
            for team in teams:
                team.roster_ids.append(pools[pos].pop(0).id)
        for team in teams:
            team.lineup = dict(zip(rules.lineup_slots(), team.roster_ids[:9]))
    now = datetime.now(timezone.utc)
    return LeagueSnapshot(league_id=f"synthetic-{mode}", team_id=teams[0].id, season=now.year, phase=mode,
                          source=Source(provider="synthetic", observed_at=now, projections_observed_at=now,
                                        complete=True, locks_verified=True, synthetic=True), rules=rules,
                          players=players, teams=teams,
                          budget=Budget(balance=100, pending_amount=0, pending_moves=0))
