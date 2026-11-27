"""Binary sensor: is a planned outage coming up in the configured district/locality."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ACCOUNT, CONF_DISTRICT, CONF_LOCALITY, DOMAIN
from .outages import filter_outages, upcoming


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add_entities
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    add_entities([CebOutageBinarySensor(store["outages"], entry)])


class CebOutageBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """On when a future CEB outage matches the chosen district + locality."""

    _attr_has_entity_name = True
    _attr_name = "Outage in my area"
    _attr_icon = "mdi:flash-alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        account = entry.data[CONF_ACCOUNT]
        self._entry = entry
        self._attr_unique_id = f"{account}_outage_in_locality"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account)}, name=f"CEB {account}"
        )

    def _matches(self) -> list[dict]:
        rows = filter_outages(
            self.coordinator.data or [],
            self._entry.options.get(CONF_DISTRICT),
            self._entry.options.get(CONF_LOCALITY),
        )
        return upcoming(rows)

    @property
    def is_on(self) -> bool:
        return bool(self._matches())

    @property
    def extra_state_attributes(self):
        m = self._matches()
        nxt = m[0] if m else None
        return {
            "district": self._entry.options.get(CONF_DISTRICT) or "all",
            "locality_filter": self._entry.options.get(CONF_LOCALITY) or None,
            "upcoming_count": len(m),
            "next_date": nxt["date"] if nxt else None,
            "next_start": nxt["start"] if nxt else None,
            "next_end": nxt["end"] if nxt else None,
            "next_locality": nxt["locality"] if nxt else None,
            "next_streets": nxt["streets"] if nxt else None,
            "upcoming": m,  # all future matches, soonest first
        }
