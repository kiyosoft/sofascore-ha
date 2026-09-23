"""Minimal async client for the (unofficial) SofaScore API."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

# SofaScore serves the same API from both hosts; try the second if the first is blocked.
BASE_URLS = (
    "https://api.sofascore.com/api/v1",
    "https://www.sofascore.com/api/v1",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.sofascore.com",
    "Referer": "https://www.sofascore.com/",
}


class SofascoreError(Exception):
    """Generic API error."""


class SofascoreNotFound(SofascoreError):
    """Resource does not exist (SofaScore also returns 404 for 'no data')."""


class SofascoreApi:
    """Thin wrapper around the endpoints this integration needs."""

    def __init__(self, session: aiohttp.ClientSession, timeout: int = 15) -> None:
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _get(self, path: str) -> dict[str, Any]:
        last_err: SofascoreError | None = None
        for base in BASE_URLS:
            url = f"{base}{path}"
            try:
                async with self._session.get(
                    url, headers=HEADERS, timeout=self._timeout
                ) as resp:
                    if resp.status == 404:
                        raise SofascoreNotFound(path)
                    if resp.status != 200:
                        last_err = SofascoreError(f"HTTP {resp.status} from {url}")
                        _LOGGER.debug("%s", last_err)
                        continue
                    return await resp.json(content_type=None)
            except SofascoreNotFound:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
                last_err = SofascoreError(f"{url}: {err!r}")
                _LOGGER.debug("%s", last_err)
        raise last_err or SofascoreError(path)

    # --- teams -------------------------------------------------------------

    async def search_teams(self, query: str) -> list[dict[str, Any]]:
        data = await self._get(f"/search/all?q={quote(query)}")
        return [
            r["entity"]
            for r in data.get("results", [])
            if r.get("type") == "team" and isinstance(r.get("entity"), dict)
        ]

    async def get_team(self, team_id: int) -> dict[str, Any]:
        data = await self._get(f"/team/{team_id}")
        return data.get("team", {})

    async def get_team_events(self, team_id: int, direction: str) -> list[dict[str, Any]]:
        """direction is 'last' or 'next'. Returns [] when there are none."""
        try:
            data = await self._get(f"/team/{team_id}/events/{direction}/0")
        except SofascoreNotFound:
            return []
        return data.get("events", [])

    # --- documented endpoints ---------------------------------------------

    async def get_event(self, event_id: int) -> dict[str, Any]:
        data = await self._get(f"/event/{event_id}")
        return data.get("event", {})

    async def get_incidents(self, event_id: int) -> list[dict[str, Any]]:
        try:
            data = await self._get(f"/event/{event_id}/incidents")
        except SofascoreNotFound:
            return []
        return data.get("incidents", [])

    async def get_standings(self, tournament_id: int, season_id: int) -> dict[str, Any]:
        return await self._get(
            f"/unique-tournament/{tournament_id}/season/{season_id}/standings/total"
        )
