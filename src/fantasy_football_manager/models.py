"""Validated league snapshots and user configuration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

POSITIONS = ("QB", "RB", "WR", "TE", "DST", "K")
ACTIONS = ("draft_pick", "set_lineup", "waiver_claim", "free_agent_add", "drop_player", "trade_offer", "trade_accept")
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1}
CAPS = {"QB": 4, "RB": 8, "WR": 8, "TE": 3, "DST": 3, "K": 3}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BrowserObservation(Model):
    page_url: str = Field(max_length=2048)
    league_id: str
    team_id: str
    current_pick: int | None = Field(default=None, ge=1, le=1281)
    autopick_enabled: bool | None = None
    draft_complete: bool = False

    @model_validator(mode="after")
    def valid_location(self):
        url = urlsplit(self.page_url)
        if url.scheme != "https" or url.hostname != "fantasy.espn.com" or url.username or url.password:
            raise ValueError("ESPN observations require the official HTTPS fantasy site.")
        query = parse_qs(url.query)
        if query.get("leagueId") != [self.league_id]:
            raise ValueError("The browser URL must identify the observed league.")
        if "teamId" in query and query["teamId"] != [self.team_id]:
            raise ValueError("The browser URL identifies a different team.")
        return self


class Source(Model):
    provider: str = Field(min_length=1, max_length=80)
    observed_at: datetime
    complete: bool = True
    locks_verified: bool = False
    locks_scope: Literal["league", "selected_team"] = "league"
    synthetic: bool = False
    projections_observed_at: datetime | None = None
    browser: BrowserObservation | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def legacy_browser_lock_scope(cls, value):
        # Earlier ESPN browser snapshots verified only the selected team's UI.
        # Do not upgrade that stored evidence to league-wide lock coverage.
        if isinstance(value, dict) and value.get("provider") == "espn_browser" and "locks_scope" not in value:
            return {**value, "locks_scope": "selected_team"}
        return value

    @field_validator("observed_at", "projections_observed_at")
    @classmethod
    def aware_date(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Source timestamps require a UTC offset.")
        if value is not None and (value - datetime.now(timezone.utc)).total_seconds() > 30:
            raise ValueError("Source timestamp is in the future.")
        return value


class Rules(Model):
    teams: int = Field(default=14, ge=2, le=32)
    slot: int = Field(default=1, ge=1, le=32)
    rounds: int = Field(default=14, ge=1, le=40)
    snake: bool = True
    starters: dict[str, int] = Field(default_factory=lambda: dict(STARTERS))
    caps: dict[str, int] = Field(default_factory=lambda: dict(CAPS))
    flex_eligible: list[str] = Field(default_factory=lambda: ["RB", "WR", "TE"])
    bench: int = Field(default=5, ge=0, le=30)
    ir: int = Field(default=2, ge=0, le=10)

    @model_validator(mode="after")
    def valid_rules(self):
        if self.slot > self.teams:
            raise ValueError("Draft slot exceeds the team count.")
        if set(self.starters) - set(POSITIONS) - {"FLEX"} or set(self.caps) - set(POSITIONS):
            raise ValueError("Unsupported position in league rules.")
        if any(type(v) is not int or v < 0 or v > 30 for v in self.starters.values()):
            raise ValueError("Starter counts must be nonnegative integers.")
        if any(type(v) is not int or v < 0 or v > 40 for v in self.caps.values()):
            raise ValueError("Position caps must be nonnegative integers.")
        if not self.flex_eligible or set(self.flex_eligible) - set(POSITIONS):
            raise ValueError("FLEX eligibility must use supported positions.")
        if any(self.caps.get(pos, 0) < self.starters.get(pos, 0) for pos in POSITIONS):
            raise ValueError("Position caps cannot exclude required starters.")
        if sum(self.starters.values()) + self.bench != self.rounds:
            raise ValueError("Draft rounds must equal starter slots plus bench slots. IR is separate.")
        if sum(self.caps.values()) < self.rounds:
            raise ValueError("Position caps must permit a complete active roster.")
        return self

    @property
    def roster_size(self) -> int:
        return self.rounds

    def lineup_slots(self) -> dict[str, list[str]]:
        return {f"{pos}{number}": list(self.flex_eligible) if pos == "FLEX" else [pos]
                for pos, count in self.starters.items() for number in range(1, count + 1)}


class Player(Model):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    position: Literal["QB", "RB", "WR", "TE", "DST", "K"]
    eligible_positions: list[str] = Field(default_factory=list)
    team: str = ""
    projection: float | None = Field(default=None, ge=0)
    weekly_projection: float | None = None
    weekly_floor: float | None = None
    weekly_ceiling: float | None = None
    adp: float = Field(default=999, gt=0)
    availability: str = "UNKNOWN"
    locked: bool = False
    bye: int | None = Field(default=None, ge=1, le=18)

    @model_validator(mode="after")
    def valid_player(self):
        if not self.eligible_positions:
            self.eligible_positions = [self.position]
        if set(self.eligible_positions) - set(POSITIONS):
            raise ValueError("Unsupported player eligibility.")
        self.availability = self.availability.upper()
        if self.weekly_floor is not None and self.weekly_ceiling is not None and self.weekly_floor > self.weekly_ceiling:
            raise ValueError("Weekly floor cannot exceed weekly ceiling.")
        return self


class Team(Model):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    slot: int = Field(ge=1, le=32)
    roster_ids: list[str] = Field(default_factory=list)
    reserve_ids: list[str] = Field(default_factory=list)
    lineup: dict[str, str | None] = Field(default_factory=dict)


class Pick(Model):
    pick_no: int = Field(ge=1, le=1280)
    player_id: str
    slot: int = Field(ge=1, le=32)


class Budget(Model):
    balance: int = Field(ge=0)
    spent_week: int = Field(default=0, ge=0)
    spent_season: int = Field(default=0, ge=0)
    pending_amount: int | None = Field(default=None, ge=0)
    pending_moves: int | None = Field(default=None, ge=0)
    roster_moves_week: int = Field(default=0, ge=0)


class LeagueSnapshot(Model):
    schema_version: Literal[1] = 1
    league_id: str = Field(min_length=1, max_length=120)
    team_id: str = Field(min_length=1, max_length=120)
    season: int = Field(ge=2020, le=2100)
    week: int = Field(default=1, ge=1, le=18)
    phase: Literal["draft", "season"] = "season"
    source: Source
    rules: Rules
    players: list[Player] = Field(min_length=1, max_length=10000)
    teams: list[Team] = Field(min_length=2, max_length=32)
    picks: list[Pick] = Field(default_factory=list)
    budget: Budget | None = None

    @model_validator(mode="after")
    def consistent_snapshot(self):
        if self.source.browser is not None:
            if (self.source.browser.league_id, self.source.browser.team_id) != (self.league_id, self.team_id):
                raise ValueError("Browser observations must match the selected league and team.")
            query = parse_qs(urlsplit(self.source.browser.page_url).query)
            if "seasonId" in query and query["seasonId"] != [str(self.season)]:
                raise ValueError("The browser URL identifies a different season.")
        players = {p.id: p for p in self.players}
        if len(players) != len(self.players):
            raise ValueError("Player identifiers must be unique.")
        if len(self.teams) != self.rules.teams:
            raise ValueError("The snapshot must include every league team.")
        teams = {t.id: t for t in self.teams}
        if len(teams) != len(self.teams) or {t.slot for t in self.teams} != set(range(1, self.rules.teams + 1)):
            raise ValueError("Team identifiers and draft slots must be unique and complete.")
        if self.team_id not in teams or teams[self.team_id].slot != self.rules.slot:
            raise ValueError("The selected team must match the configured draft slot.")
        owned = set()
        slots = self.rules.lineup_slots()
        for team in self.teams:
            ids = team.roster_ids + team.reserve_ids
            if len(ids) != len(set(ids)) or owned.intersection(ids) or set(ids) - players.keys():
                raise ValueError("Roster ownership must be unique and reference known players.")
            owned.update(ids)
            if len(team.roster_ids) > self.rules.rounds or len(team.reserve_ids) > self.rules.ir:
                raise ValueError("A team exceeds its active or reserve roster size.")
            if any(sum(players[pid].position == pos for pid in team.roster_ids) > self.rules.caps.get(pos, 0) for pos in POSITIONS):
                raise ValueError("A roster exceeds a position cap.")
            assigned = [pid for pid in team.lineup.values() if pid is not None]
            if len(set(assigned)) != len(assigned) or set(assigned) - set(team.roster_ids):
                raise ValueError("Lineups cannot duplicate players or use unowned players.")
            for slot, pid in team.lineup.items():
                if slot not in slots or (pid is not None and not set(players[pid].eligible_positions).intersection(slots[slot])):
                    raise ValueError("Lineup slot or player eligibility is invalid.")
        if len(self.picks) > self.rules.teams * self.rules.rounds:
            raise ValueError("Draft history exceeds the configured rounds.")
        if [p.pick_no for p in self.picks] != list(range(1, len(self.picks) + 1)):
            raise ValueError("Draft history must be ordered and contain no gaps.")
        if len({p.player_id for p in self.picks}) != len(self.picks):
            raise ValueError("A player cannot be drafted twice.")
        for pick in self.picks:
            rnd, offset = divmod(pick.pick_no - 1, self.rules.teams)
            expected = self.rules.teams - offset if self.rules.snake and rnd % 2 else offset + 1
            if pick.slot != expected or pick.player_id not in players:
                raise ValueError("Draft history has an invalid owner or player.")
        if self.phase == "draft":
            opponent_ids = {pick.player_id for pick in self.picks if pick.slot != self.rules.slot}
            if any(player.projection is None and player.id not in opponent_ids for player in self.players):
                raise ValueError("Available and selected-team draft players require full-season projections.")
            for team in self.teams:
                if set(team.roster_ids) != {p.player_id for p in self.picks if p.slot == team.slot} or team.reserve_ids:
                    raise ValueError("Draft rosters must match the complete pick history.")
        return self

    def own_team(self) -> Team:
        return next(team for team in self.teams if team.id == self.team_id)

    def age_seconds(self) -> float:
        return max(0, (datetime.now(timezone.utc) - self.source.observed_at).total_seconds())


Mode = Literal["disabled", "advisory", "review", "automatic"]


class Automation(Model):
    preset: Literal["advisory", "review", "bounded_automation", "custom"] = "advisory"
    paused: bool = False
    actions: dict[str, Mode] = Field(default_factory=lambda: {action: "advisory" for action in ACTIONS})

    @model_validator(mode="after")
    def validate_actions(self):
        if set(self.actions) != set(ACTIONS):
            raise ValueError("Automation must specify every supported action type.")
        return self

    def mode_for(self, action: str) -> str:
        if action not in ACTIONS:
            raise ValueError("Unknown action type.")
        return self.actions[action] if self.preset == "custom" else {"advisory": "advisory", "review": "review", "bounded_automation": "automatic"}[self.preset]


class Limits(Model):
    protected_ids: list[str] = Field(default_factory=list)
    drop_mode: Literal["listed_only", "any_unprotected"] = "listed_only"
    allowed_drop_ids: list[str] = Field(default_factory=list)
    max_weekly_moves: int = Field(default=3, ge=0, le=100)
    faab_per_claim: int = Field(default=10, ge=0)
    faab_per_week: int = Field(default=20, ge=0)
    faab_per_season: int = Field(default=70, ge=0)
    faab_reserve: int = Field(default=30, ge=0)
    min_lineup_improvement: float = Field(default=1.5, ge=0)
    max_draft_age_seconds: int = Field(default=15, ge=1, le=300)
    max_season_age_seconds: int = Field(default=300, ge=1, le=86400)
    max_projection_age_seconds: int = Field(default=3600, ge=1, le=604800)
    max_adp_reach: float | None = Field(default=None, ge=0)
    batch_trials: int = Field(default=40, ge=1, le=500)

    @model_validator(mode="after")
    def valid_limits(self):
        if self.faab_per_claim > self.faab_per_week or self.faab_per_week > self.faab_per_season:
            raise ValueError("FAAB caps must satisfy claim <= week <= season.")
        return self


class Strategy(Model):
    draft: Literal["balanced_value", "rb_priority", "wr_priority", "hero_rb", "zero_rb"] = "balanced_value"
    season: Literal["projected_points", "floor", "upside"] = "projected_points"
    waiver: Literal["immediate_starter", "bench_upside", "conserve_faab"] = "immediate_starter"


class ManagerConfig(Model):
    schema_version: Literal[1] = 1
    automation: Automation = Field(default_factory=Automation)
    limits: Limits = Field(default_factory=Limits)
    strategy: Strategy = Field(default_factory=Strategy)
