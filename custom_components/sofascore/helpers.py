"""Helpers to turn raw SofaScore event JSON into flat, HA-friendly dicts."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.util import dt as dt_util

from .const import RESULT_HOLD, STATUS_FINISHED, STATUS_LIVE, TEAM_IMAGE_URL, TOURNAMENT_IMAGE_URL

# Rough football length; used only to decide when a result gives way to the next fixture.
_MATCH_LENGTH = timedelta(hours=2)


def event_ts(event: dict[str, Any]) -> int:
    return event.get("startTimestamp") or 0


def event_status(event: dict[str, Any]) -> str | None:
    return (event.get("status") or {}).get("type")


def live_minute(event: dict[str, Any]) -> int | None:
    """Approximate match minute (football). None outside of running periods."""
    code = (event.get("status") or {}).get("code")
    start = (event.get("time") or {}).get("currentPeriodStartTimestamp")
    # 6 = 1st half, 7 = 2nd half, 41/42 = extra time halves
    offsets = {6: 0, 7: 45, 41: 90, 42: 105}
    if code not in offsets or not start:
        return None
    return offsets[code] + int((time.time() - start) // 60) + 1


def summarize_event(event: dict[str, Any] | None, team_id: int) -> dict[str, Any] | None:
    if not event:
        return None

    home = event.get("homeTeam") or {}
    away = event.get("awayTeam") or {}
    is_home = home.get("id") == team_id
    opponent = away if is_home else home

    home_score = (event.get("homeScore") or {}).get("current")
    away_score = (event.get("awayScore") or {}).get("current")
    score = (
        f"{home_score}-{away_score}"
        if home_score is not None and away_score is not None
        else None
    )

    result = None
    winner = event.get("winnerCode")  # 1 = home, 2 = away, 3 = draw
    if event_status(event) == STATUS_FINISHED and winner in (1, 2, 3):
        result = "D" if winner == 3 else ("W" if (winner == 1) == is_home else "L")

    tournament = event.get("tournament") or {}
    unique = tournament.get("uniqueTournament") or {}
    status = event.get("status") or {}
    ts = event.get("startTimestamp")

    summary = {
        "event_id": event.get("id"),
        "home_team": home.get("name"),
        "away_team": away.get("name"),
        "opponent": opponent.get("name"),
        "opponent_id": opponent.get("id"),
        "opponent_logo": TEAM_IMAGE_URL.format(team_id=opponent.get("id"))
        if opponent.get("id")
        else None,
        "venue": "home" if is_home else "away",
        "home_score": home_score,
        "away_score": away_score,
        "score": score,
        "result": result,
        "status": status.get("description"),
        "status_type": status.get("type"),
        "tournament": unique.get("name") or tournament.get("name"),
        "round": (event.get("roundInfo") or {}).get("round"),
        "start_time": dt_util.utc_from_timestamp(ts) if ts else None,
    }
    if event_status(event) == STATUS_LIVE:
        summary["minute"] = live_minute(event)
    return summary


def featured_match(
    live: dict[str, Any] | None,
    last: dict[str, Any] | None,
    nxt: dict[str, Any] | None,
    now: float,
) -> tuple[str, dict[str, Any] | None]:
    """Pick the one game Team Tracker would show: IN, then a recent POST, else PRE."""
    if live:
        return "IN", live
    if last and now < event_ts(last) + _MATCH_LENGTH.total_seconds() + RESULT_HOLD.total_seconds():
        return "POST", last
    if nxt:
        return "PRE", nxt
    if last:
        return "POST", last
    return "NOT_FOUND", None


def format_last_play(incidents: list[dict[str, Any]]) -> str | None:
    goals = [i for i in incidents if i.get("incidentType") == "goal"]
    if not goals:
        return None
    goal = max(goals, key=lambda i: (i.get("time") or 0, i.get("addedTime") or 0))
    who = (goal.get("player") or {}).get("name") or "Goal"
    minute = goal.get("time")
    return f"{minute}' {who}" if minute else who


def _kickoff_in(ts: int, now: float) -> str:
    minutes = abs(int(ts - now)) // 60
    ahead = ts >= now
    if minutes < 60:
        n, unit = max(minutes, 1), "minute"
    elif minutes < 36 * 60:
        n, unit = minutes // 60, "hour"
    else:
        n, unit = minutes // (60 * 24), "day"
    label = f"{n} {unit}" + ("s" if n != 1 else "")
    return f"in {label}" if ahead else f"{label} ago"


def _record(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    return f"{row.get('wins') or 0}-{row.get('draws') or 0}-{row.get('losses') or 0}"


def _compact(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None and v != ""}


def tracker_attributes(
    state: str,
    event: dict[str, Any] | None,
    team: dict[str, Any] | None,
    table: dict[int, dict[str, Any]] | None,
    last_play: str | None,
    now: float,
) -> dict[str, Any]:
    """Attributes consumed by the Team Tracker card. Missing values are omitted."""
    team = team or {}
    event = event or {}
    table = table or {}
    sport = team.get("sport") or (event.get("homeTeam") or {}).get("sport") or {}
    attrs: dict[str, Any] = {
        "sport": sport.get("name"),
        "sport_path": sport.get("slug"),
        "team_id": team.get("id"),
        "team_abbr": team.get("nameCode"),
        "team_name": team.get("shortName") or team.get("name"),
        "team_long_name": team.get("fullName") or team.get("name"),
        "team_logo": TEAM_IMAGE_URL.format(team_id=team["id"]) if team.get("id") else None,
        "last_update": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "api_message": "SofaScore",
    }
    if team.get("id") and sport.get("slug") and team.get("slug"):
        attrs["team_url"] = (
            f"https://www.sofascore.com/team/{sport['slug']}/{team['slug']}/{team['id']}"
        )
    colors = team.get("teamColors") or {}
    if colors.get("primary"):
        attrs["team_colors"] = [colors.get("primary"), colors.get("secondary") or colors.get("primary")]

    if not event:
        return _compact(attrs)

    home = event.get("homeTeam") or {}
    away = event.get("awayTeam") or {}
    is_home = home.get("id") == team.get("id")
    our = home if is_home else away
    opp = away if is_home else home
    our_row = table.get(our.get("id"))
    opp_row = table.get(opp.get("id"))

    def paint(prefix: str, side: dict[str, Any], row: dict[str, Any] | None, homeaway: str) -> None:
        side_colors = side.get("teamColors") or {}
        attrs[f"{prefix}_abbr"] = side.get("nameCode")
        attrs[f"{prefix}_id"] = side.get("id")
        attrs[f"{prefix}_name"] = side.get("shortName") or side.get("name")
        attrs[f"{prefix}_long_name"] = side.get("name")
        attrs[f"{prefix}_homeaway"] = homeaway
        attrs[f"{prefix}_record"] = _record(row)
        attrs[f"{prefix}_rank"] = (row or {}).get("position")
        if side.get("id"):
            attrs[f"{prefix}_logo"] = TEAM_IMAGE_URL.format(team_id=side["id"])
        if side_colors.get("primary"):
            attrs[f"{prefix}_colors"] = [
                side_colors.get("primary"),
                side_colors.get("secondary") or side_colors.get("primary"),
            ]

    paint("team", our, our_row, "home" if is_home else "away")
    if team.get("fullName"):
        attrs["team_long_name"] = team["fullName"]
    paint("opponent", opp, opp_row, "away" if is_home else "home")

    tournament = event.get("tournament") or {}
    unique = tournament.get("uniqueTournament") or {}
    status = event.get("status") or {}
    ts = event_ts(event)
    venue = event.get("venue") or {}
    city = (venue.get("city") or {}).get("name")
    country = ((venue.get("city") or {}).get("country") or venue.get("country") or {}).get("name")
    home_score = (event.get("homeScore") or {}).get("current")
    away_score = (event.get("awayScore") or {}).get("current")

    attrs.update(
        {
            "league": unique.get("name") or tournament.get("name"),
            "league_path": unique.get("slug") or tournament.get("slug"),
            "league_logo": TOURNAMENT_IMAGE_URL.format(tournament_id=unique["id"])
            if unique.get("id")
            else None,
            "season": (event.get("season") or {}).get("name"),
            "date": datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None,
            "kickoff_in": _kickoff_in(ts, now) if ts else None,
            "event_name": f"{home.get('name')} vs {away.get('name')}",
            "event_url": f"https://www.sofascore.com/event/{event['id']}" if event.get("id") else None,
            "venue": venue.get("name"),
            "location": ", ".join(p for p in (city, country) if p) or None,
            "api_url": f"https://www.sofascore.com/api/v1/event/{event['id']}" if event.get("id") else None,
        }
    )
    if state in ("IN", "POST") and home_score is not None and away_score is not None:
        attrs["team_score"] = home_score if is_home else away_score
        attrs["opponent_score"] = away_score if is_home else home_score
    if state == "IN":
        desc = status.get("description") or ""
        minute = live_minute(event)
        if "half" in desc.lower() and "1st" not in desc.lower() and "2nd" not in desc.lower():
            attrs["clock"] = "HT"
        elif minute:
            attrs["clock"] = f"{minute}'"
        else:
            attrs["clock"] = desc or None
        attrs["quarter"] = desc or None
        attrs["last_play"] = last_play
    elif state == "POST":
        attrs["clock"] = "Final"
        attrs["last_play"] = last_play
        winner = event.get("winnerCode")  # 1 home, 2 away, 3 draw
        if winner in (1, 2):
            attrs["team_winner"] = (winner == 1) == is_home
            attrs["opponent_winner"] = not attrs["team_winner"]
    return _compact(attrs)


def _demo() -> None:
    now = 1_700_000_000.0
    team = {"id": 1, "name": "Benfica", "shortName": "Benfica", "fullName": "SL Benfica", "nameCode": "SLB", "slug": "benfica", "sport": {"name": "Football", "slug": "football"}, "teamColors": {"primary": "#cc0000", "secondary": "#ffffff"}}
    opp = {"id": 2, "name": "Porto", "shortName": "Porto", "nameCode": "FCP", "teamColors": {"primary": "#0000ff", "secondary": "#ffffff"}}
    base = {"id": 9, "homeTeam": team, "awayTeam": opp, "startTimestamp": now + 3600, "status": {"description": "Not started", "type": "notstarted"}, "tournament": {"name": "Liga", "uniqueTournament": {"id": 7, "name": "Liga", "slug": "liga"}}, "venue": {"name": "Estádio da Luz", "city": {"name": "Lisbon", "country": {"name": "Portugal"}}}}
    state, ev = featured_match(None, None, base, now)
    assert state == "PRE" and ev is base
    pre = tracker_attributes(state, ev, team, {1: {"wins": 4, "draws": 1, "losses": 0, "position": 1}, 2: {"wins": 3, "draws": 0, "losses": 2, "position": 4}}, None, now)
    assert pre["team_abbr"] == "SLB" and pre["opponent_abbr"] == "FCP"
    assert pre["team_homeaway"] == "home" and pre["venue"] == "Estádio da Luz"
    assert pre["team_record"] == "4-1-0" and "team_score" not in pre
    live = {**base, "startTimestamp": now - 600, "status": {"code": 6, "description": "1st half", "type": "inprogress"}, "homeScore": {"current": 1}, "awayScore": {"current": 0}, "time": {"currentPeriodStartTimestamp": now - 600}}
    assert featured_match(live, None, base, now)[0] == "IN"
    mid = tracker_attributes("IN", live, team, {}, "10' A. Bah", now)
    assert mid["team_score"] == 1 and mid["clock"].endswith("'") and mid["quarter"] == "1st half"
    done = {**base, "startTimestamp": now - 3 * 3600, "status": {"type": "finished", "description": "Ended"}, "winnerCode": 1, "homeScore": {"current": 3}, "awayScore": {"current": 0}}
    assert featured_match(None, done, base, now)[0] == "POST"
    assert featured_match(None, {**done, "startTimestamp": now - 20 * 3600}, base, now)[0] == "PRE"
    post = tracker_attributes("POST", done, team, {}, None, now)
    assert post["clock"] == "Final" and post["team_winner"] is True and post["opponent_score"] == 0
    print("ok")


if __name__ == "__main__":
    _demo()
