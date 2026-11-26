"""CEB Mauritius integration."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CebApi, CebAuthError
from .const import CONF_ACCOUNT, CONF_DEVICE_ID, CONF_PIN, DOMAIN, SCAN_INTERVAL_HOURS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
RETRY_INTERVAL = timedelta(minutes=15)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = CebApi(
        async_get_clientsession(hass),
        entry.data[CONF_DEVICE_ID],
        entry.data[CONF_PIN],
    )
    account = entry.data[CONF_ACCOUNT]

    async def _update() -> dict:
        try:
            data = await api.dashboard(account)
            data["_invoice"] = await api.latest_invoice(account)
            data["_daily"] = await api.daily_consumption(account)
            data["_hourly"] = await api.hourly_consumption(account)
        except Exception as err:
            # one failed poll (e.g. a DNS blip) must not cost a whole 6 h interval
            coordinator.update_interval = RETRY_INTERVAL
            _LOGGER.warning("CEB update failed, retrying in %s: %r", RETRY_INTERVAL, err)
            if isinstance(err, CebAuthError):
                raise UpdateFailed(f"CEB auth failed: {err}") from err
            raise
        coordinator.update_interval = timedelta(hours=SCAN_INTERVAL_HOURS)
        return data

    coordinator: DataUpdateCoordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=_update,
        update_interval=timedelta(hours=SCAN_INTERVAL_HOURS),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok
