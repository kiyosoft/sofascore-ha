"""Helpers to turn raw SofaScore event JSON into flat, HA-friendly dicts."""
from __future__ import annotations

import time
from typing import Any

from homeassistant.util import dt as dt_util

from .const import STATUS_FINISHED, STATUS_LIVE, TEAM_IMAGE_URL


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
