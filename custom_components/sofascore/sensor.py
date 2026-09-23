"""Sensors: next match, last match, live match, league position."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SofascoreConfigEntry
from .const import DOMAIN, TEAM_IMAGE_URL
from .coordinator import SofascoreCoordinator
from .helpers import summarize_event


def _summary(c: SofascoreCoordinator, key: str) -> dict[str, Any] | None:
    return summarize_event(c.data.get(key), c.team_id)


def _attrs(c: SofascoreCoordinator, key: str) -> dict[str, Any] | None:
    s = _summary(c, key)
    if not s:
        return None
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in s.items()}


def _last_value(c: SofascoreCoordinator) -> str | None:
    s = _summary(c, "last_event")
    if not s:
        return None
    return f"{s['result']} {s['score']}" if s["result"] else s["score"]


def _live_value(c: SofascoreCoordinator) -> str:
    s = _summary(c, "live_event")
    return s["status"] if s else "Not playing"


@dataclass(frozen=True, kw_only=True)
class SofascoreSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SofascoreCoordinator], Any]
    attrs_fn: Callable[[SofascoreCoordinator], dict[str, Any] | None] = lambda c: None


SENSORS: tuple[SofascoreSensorDescription, ...] = (
    SofascoreSensorDescription(
        key="next_match",
        translation_key="next_match",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: (_summary(c, "next_event") or {}).get("start_time"),
        attrs_fn=lambda c: _attrs(c, "next_event"),
    ),
    SofascoreSensorDescription(
        key="last_match",
        translation_key="last_match",
        icon="mdi:scoreboard",
        value_fn=_last_value,
        attrs_fn=lambda c: _attrs(c, "last_event"),
    ),
    SofascoreSensorDescription(
        key="live_match",
        translation_key="live_match",
        icon="mdi:soccer-field",
        value_fn=_live_value,
        attrs_fn=lambda c: _attrs(c, "live_event"),
    ),
    SofascoreSensorDescription(
        key="league_position",
        translation_key="league_position",
        icon="mdi:podium",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (c.data.get("standings") or {}).get("position"),
        attrs_fn=lambda c: c.data.get("standings"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SofascoreConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SofascoreSensor(coordinator, d) for d in SENSORS)


class SofascoreSensor(CoordinatorEntity[SofascoreCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: SofascoreSensorDescription

    def __init__(self, coordinator: SofascoreCoordinator, description: SofascoreSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.team_id}_{description.key}"
        team = coordinator.data.get("team") or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.team_id))},
            name=team.get("name") or f"Team {coordinator.team_id}",
            manufacturer="SofaScore",
            model=(team.get("sport") or {}).get("name"),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=(
                f"https://www.sofascore.com/team/{(team.get('sport') or {}).get('slug', 'football')}"
                f"/{team.get('slug', '')}/{coordinator.team_id}"
            ),
        )
        self._attr_entity_picture = TEAM_IMAGE_URL.format(team_id=coordinator.team_id)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs_fn(self.coordinator)
