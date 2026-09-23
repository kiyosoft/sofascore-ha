"""Coordinator: polls SofaScore, adapts interval around matches, fires update events."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SofascoreApi, SofascoreError, SofascoreNotFound
from .const import (
    CONF_TEAM_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_TYPE,
    LIVE_SCAN_INTERVAL,
    PREMATCH_WINDOW,
    STANDINGS_TTL,
    STATUS_FINISHED,
    STATUS_LIVE,
    STATUS_NOT_STARTED,
)
from .helpers import (
    event_status,
    event_ts,
    featured_match,
    format_last_play,
    summarize_event,
    tracker_attributes,
)

_LOGGER = logging.getLogger(__name__)


class SofascoreCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches team, last/next/live match and league standing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: SofascoreApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_TEAM_ID]}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.api = api
        self.team_id: int = int(entry.data[CONF_TEAM_ID])
        self._team: dict[str, Any] | None = None
        self._last_live: dict[str, Any] | None = None
        self._first_run = True
        self._standings_cache: dict[tuple[int, int], tuple[float, dict[int, dict]]] = {}

    # ------------------------------------------------------------------ update

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self._team is None:
                self._team = await self.api.get_team(self.team_id)
            last_events = await self.api.get_team_events(self.team_id, "last")
            next_events = await self.api.get_team_events(self.team_id, "next")
        except SofascoreError as err:
            raise UpdateFailed(f"Error talking to SofaScore: {err}") from err

        by_id = {e["id"]: e for e in [*last_events, *next_events] if "id" in e}
        events = sorted(by_id.values(), key=event_ts)

        live = next((e for e in events if event_status(e) == STATUS_LIVE), None)
        finished = [e for e in last_events if event_status(e) == STATUS_FINISHED]
        last_event = max(finished, key=event_ts, default=None)
        upcoming = [e for e in next_events if event_status(e) == STATUS_NOT_STARTED]
        next_event = min(upcoming, key=event_ts, default=None)

        match_ended = await self._process_live(live, by_id)
        game_state, featured = featured_match(live, last_event, next_event, time.time())
        if featured:
            featured = await self._enrich(featured)
        last_play = None
        if game_state in ("IN", "POST") and featured:
            try:
                last_play = format_last_play(await self.api.get_incidents(featured["id"]))
            except SofascoreError as err:
                _LOGGER.debug("Could not fetch incidents: %s", err)
        table = await self._get_standings(
            [featured, last_event, next_event, *sorted(finished, key=event_ts, reverse=True)],
            force=match_ended,
        )
        self._adjust_interval(live, next_event)
        self._first_run = False

        return {
            "team": self._team,
            "last_event": last_event,
            "next_event": next_event,
            "live_event": live,
            "standings": table.get(self.team_id),
            "game_state": game_state,
            "game_attrs": tracker_attributes(
                game_state, featured, self._team, table, last_play, time.time()
            ),
        }

    async def _enrich(self, event: dict[str, Any]) -> dict[str, Any]:
        """List payloads omit the stadium. One detail call fills it in."""
        try:
            detail = await self.api.get_event(event["id"])
        except SofascoreError as err:
            _LOGGER.debug("Event detail failed: %s", err)
            return event
        return detail or event

    def _adjust_interval(self, live: dict | None, next_event: dict | None) -> None:
        soon = (
            next_event is not None
            and event_ts(next_event) - time.time() <= PREMATCH_WINDOW.total_seconds()
        )
        wanted = LIVE_SCAN_INTERVAL if (live or soon) else DEFAULT_SCAN_INTERVAL
        if wanted != self.update_interval:
            _LOGGER.debug("Team %s: polling every %s", self.team_id, wanted)
            self.update_interval = wanted

    # ------------------------------------------------------------ live events

    @staticmethod
    def _snapshot(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event["id"],
            "home": (event.get("homeScore") or {}).get("current") or 0,
            "away": (event.get("awayScore") or {}).get("current") or 0,
            "status_code": (event.get("status") or {}).get("code"),
        }

    async def _process_live(self, live: dict | None, by_id: dict[int, dict]) -> bool:
        """Fire bus events for changes. Returns True if a tracked match just ended."""
        prev = self._last_live
        ended = False

        if live:
            snap = self._snapshot(live)
            if not self._first_run:
                if prev is None or prev["event_id"] != snap["event_id"]:
                    self._fire("kickoff", live)
                else:
                    for side in ("home", "away"):
                        if snap[side] > prev[side]:
                            await self._fire_goal(live, side)
                    if snap["status_code"] != prev["status_code"]:
                        self._fire("status_change", live)
            self._last_live = snap
        elif prev is not None:
            ended_event = by_id.get(prev["event_id"])
            if ended_event and event_status(ended_event) == STATUS_FINISHED:
                self._fire("full_time", ended_event)
            ended = True
            self._last_live = None

        return ended

    async def _fire_goal(self, event: dict[str, Any], side: str) -> None:
        is_home_goal = side == "home"
        our_side_home = (event.get("homeTeam") or {}).get("id") == self.team_id
        scoring_team = (event.get(f"{side}Team") or {}).get("name")

        player = None
        try:
            incidents = await self.api.get_incidents(event["id"])
            goals = [
                i for i in incidents
                if i.get("incidentType") == "goal" and i.get("isHome") == is_home_goal
            ]
            if goals:
                latest = max(goals, key=lambda i: (i.get("time") or 0, i.get("addedTime") or 0))
                player = (latest.get("player") or {}).get("name") or latest.get("playerName")
        except SofascoreError as err:
            _LOGGER.debug("Could not fetch incidents: %s", err)

        self._fire(
            "goal",
            event,
            scoring_team=scoring_team,
            scored_by_us=is_home_goal == our_side_home,
            player=player,
        )

    def _fire(self, kind: str, event: dict[str, Any], **extra: Any) -> None:
        summary = summarize_event(event, self.team_id) or {}
        if summary.get("start_time"):
            summary["start_time"] = summary["start_time"].isoformat()
        data = {
            "type": kind,
            "team_id": self.team_id,
            "team_name": (self._team or {}).get("name"),
            **summary,
            **extra,
        }
        _LOGGER.debug("Firing %s: %s", EVENT_TYPE, data)
        self.hass.bus.async_fire(EVENT_TYPE, data)

    # -------------------------------------------------------------- standings

    async def _get_standings(self, candidates: list[dict | None], force: bool) -> dict[int, dict]:
        """First league table that contains this team, indexed by team id."""
        seen: set[tuple[int, int]] = set()
        for ev in candidates:
            if not ev:
                continue
            ut = ((ev.get("tournament") or {}).get("uniqueTournament") or {}).get("id")
            season = (ev.get("season") or {}).get("id")
            if not ut or not season or (ut, season) in seen:
                continue
            if len(seen) >= 3:  # don't hammer the API looking through cup games
                break
            seen.add((ut, season))
            table = await self._standings_for(ut, season, force)
            if self.team_id in table:
                return table
        return {}

    async def _standings_for(self, ut: int, season: int, force: bool) -> dict[int, dict]:
        key = (ut, season)
        cached = self._standings_cache.get(key)
        now = time.monotonic()
        if cached and not force and now - cached[0] < STANDINGS_TTL.total_seconds():
            return cached[1]

        try:
            data = await self.api.get_standings(ut, season)
        except SofascoreNotFound:
            data = {}
        except SofascoreError as err:
            _LOGGER.debug("Standings fetch failed: %s", err)
            return cached[1] if cached else {}

        index = self._index_rows(data)
        self._standings_cache[key] = (now, index)
        return index

    def _index_rows(self, data: dict[str, Any]) -> dict[int, dict]:
        indexed: dict[int, dict] = {}
        for table in data.get("standings", []):
            for r in table.get("rows", []):
                tid = (r.get("team") or {}).get("id")
                if tid is None or tid in indexed:
                    continue
                sf, sa = r.get("scoresFor") or 0, r.get("scoresAgainst") or 0
                indexed[tid] = {
                    "position": r.get("position"),
                    "points": r.get("points"),
                    "matches": r.get("matches"),
                    "wins": r.get("wins"),
                    "draws": r.get("draws"),
                    "losses": r.get("losses"),
                    "scores_for": sf,
                    "scores_against": sa,
                    "goal_difference": sf - sa,
                    "promotion": (r.get("promotion") or {}).get("text"),
                    "table": table.get("name"),
                    "tournament": ((table.get("tournament") or {}).get("uniqueTournament") or {}).get("name"),
                }
        return indexed
