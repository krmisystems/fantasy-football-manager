"""Build five fictional teams without a database or provider connection."""

from .demo import make_demo
from .models import LeagueSnapshot, ManagerConfig
from .portfolio import _Entry, _Frame
from .season import recommend_lineup


def make_portfolio_demo():
    names = ["Northside Wolves", "Harbor Lights", "Sunday Pilots", "Cedar Rovers", "Westside Union"]
    leagues = ["Fictional Founders League", "Fictional Harbor League", "Fictional Sunday League",
               "Fictional Cedar League", "Fictional Union League"]
    frames = []
    for index, (name, league) in enumerate(zip(names, leagues)):
        snapshot = make_demo()
        snapshot.league_id = f"fictional-portfolio-{index + 1}"
        snapshot.own_team().name = name
        config = ManagerConfig()
        config.automation.preset = "review" if index in {0, 2} else "advisory"
        config.strategy.season = ["projected_points", "floor", "upside", "projected_points", "floor"][index]
        config.limits.protected_ids = snapshot.own_team().roster_ids[:2]
        config.limits.max_season_age_seconds = 86400
        config.limits.max_projection_age_seconds = 86400
        snapshot.budget.balance = 100 - index * 8
        snapshot.budget.spent_season = index * 8
        for player in snapshot.players:
            player.weekly_projection = round(player.weekly_projection * (1 + index * .035), 2)
            player.weekly_floor = round(player.weekly_floor * (1 + index * .035), 2)
            player.weekly_ceiling = round(player.weekly_ceiling * (1 + index * .035), 2)
        if index == 4:
            missing = next(player for player in snapshot.players if player.id == snapshot.own_team().roster_ids[0])
            missing.weekly_projection = None
            missing.weekly_floor = None
            missing.weekly_ceiling = None
        snapshot = LeagueSnapshot.model_validate(snapshot.model_dump())
        key = name.lower().replace(" ", "-")
        entry = _Entry(key, None, name, league, "football", "synthetic",
                       (snapshot.league_id, snapshot.team_id, snapshot.season))
        frame = _Frame(entry, snapshot, config, 3, 1, "ready")
        if index in {0, 1, 2}:
            proposal = {"id": f"fictional-proposal-{index + 1}", "team_key": key, "team_name": name,
                        "action": "set_lineup", "status": "confirmed" if index == 1 else "prepared",
                        "mode": "review", "created_at": snapshot.source.observed_at.isoformat(),
                        "authorized_at": None, "summary": "Fictional lineup change",
                        "payload": {"lineup": recommend_lineup(snapshot, config)["lineup"]},
                        "revision": 3, "config_revision": 1, "is_current": index != 1,
                        "source": "synthetic", "scope": "synthetic_demo_only", "synthetic": True}
            proposal["player_names"] = {player.id: player.name for player in snapshot.players
                                        if player.id in proposal["payload"]["lineup"].values()}
            frame.proposals = [proposal]
            frame.proposal_count = 1
            frame.pending_count = int(index != 1)
        frames.append(frame)
    return frames
