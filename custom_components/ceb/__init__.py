"""CEB Mauritius integration."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CebApi, CebAuthError
from .const import (
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_PIN,
    DOMAIN,
    OUTAGE_SCAN_HOURS,
    SCAN_INTERVAL_HOURS,
)
from .outages import fetch_outages

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
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
        except CebAuthError as err:
            # Bad/stale PIN: stop polling and start reauth. Never keep retrying loginPin
            # on a rejected PIN — CEB locks the account after a few bad attempts.
            raise ConfigEntryAuthFailed(f"CEB PIN rejected: {err}") from err
        except Exception as err:
            # Network/transient failure only: a blip must not cost a whole 6 h interval.
            coordinator.update_interval = RETRY_INTERVAL
            _LOGGER.warning("CEB update failed, retrying in %s: %r", RETRY_INTERVAL, err)
            raise UpdateFailed(err) from err
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

    # Separate coordinator for national planned outages (public page scrape, no auth).
    # Kept apart so an account auth failure never blocks outages, and vice versa.
    session = async_get_clientsession(hass)

    async def _update_outages() -> list:
        try:
            return await fetch_outages(session)
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(err) from err

    outage_coordinator: DataUpdateCoordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_outages",
        update_method=_update_outages,
        update_interval=timedelta(hours=OUTAGE_SCAN_HOURS),
    )
    await outage_coordinator.async_refresh()  # non-fatal: outages are optional

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "main": coordinator,
        "outages": outage_coordinator,
    }
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload_on_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options (district/locality) change so the outage sensor updates."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok
