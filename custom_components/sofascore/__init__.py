"""The SofaScore integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from .api import SofascoreApi
from .coordinator import SofascoreCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type SofascoreConfigEntry = ConfigEntry[SofascoreCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SofascoreConfigEntry) -> bool:
    api = SofascoreApi()
    coordinator = SofascoreCoordinator(hass, entry, api)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await api.close()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SofascoreConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.api.close()
    return ok
