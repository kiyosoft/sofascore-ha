"""Config flow: search a team by name (or enter its ID), then pick it."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import SofascoreApi, SofascoreError, SofascoreNotFound
from .const import CONF_TEAM_ID, CONF_TEAM_NAME, DOMAIN

CONF_QUERY = "query"


def _label(team: dict[str, Any]) -> str:
    parts = [
        (team.get("sport") or {}).get("name"),
        (team.get("country") or {}).get("name"),
        "Women" if team.get("gender") == "F" else None,
    ]
    extra = ", ".join(p for p in parts if p)
    return f"{team.get('name')} ({extra})" if extra else str(team.get("name"))


class SofascoreConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._teams: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            query = user_input[CONF_QUERY].strip()
            api = SofascoreApi()
            try:
                if query.isdigit():
                    team = await api.get_team(int(query))
                    self._teams = [team] if team else []
                else:
                    self._teams = await api.search_teams(query)
            except SofascoreNotFound:
                self._teams = []
            except SofascoreError:
                errors["base"] = "cannot_connect"
            finally:
                await api.close()

            if not errors:
                if not self._teams:
                    errors["base"] = "no_teams"
                else:
                    return await self.async_step_select()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): str}),
            errors=errors,
        )

    async def async_step_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            team_id = int(user_input[CONF_TEAM_ID])
            team = next(t for t in self._teams if t.get("id") == team_id)
            await self.async_set_unique_id(str(team_id))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=team.get("name", str(team_id)),
                data={CONF_TEAM_ID: team_id, CONF_TEAM_NAME: team.get("name")},
            )

        options = [
            SelectOptionDict(value=str(t["id"]), label=_label(t))
            for t in self._teams[:25]
            if t.get("id")
        ]
        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TEAM_ID, default=options[0]["value"]): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )
