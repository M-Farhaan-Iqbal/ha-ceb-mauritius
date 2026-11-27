"""CEB sensors, all fed by one dashboard poll."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import tariff
from .const import CONF_ACCOUNT, CONF_DISTRICT, CONF_LOCALITY, DOMAIN
from .outages import filter_outages


def _tariff_code(data: dict) -> str:
    # dashboard gives e.g. "TARIF_110A" -> "110A"
    return tariff.normalize(data.get("tariff"))


def _period_start(data: dict) -> str | None:
    """Current billing period start = the last meter-read date (CEB bills ~monthly, read ~6th)."""
    d = data.get("lastMtrDtl_Date")
    return d[:10] if d else None


def _month_kwh(data: dict) -> float | None:
    """Sum of kWh in the current billing period: after the last meter read.
    Falls back to the calendar month if no read date is known."""
    days = data.get("_daily") or []
    start = _period_start(data)
    if start:
        vals = [d["kwh"] for d in days if d.get("date", "") > start]
    else:
        prefix = dt_util.now().strftime("%Y-%m-")
        vals = [d["kwh"] for d in days if d.get("date", "").startswith(prefix)]
    return round(sum(vals), 3) if vals else None


def _month_cost(data: dict):
    kwh = _month_kwh(data)
    if kwh is None:
        return None
    return tariff.monthly_cost(kwh, _tariff_code(data))


def _consumptions(data: dict) -> list[dict]:
    return data.get("consumptions") or []


def _year_kwh(data: dict):
    cs = _consumptions(data)
    return round(sum(c.get("currentConsumption") or 0 for c in cs), 1) if cs else None


def _cost_history(data: dict) -> list[dict]:
    """[{month,kwh,cost}] for the 12-month dashboard chart, cost on the account's tariff."""
    t = _tariff_code(data)
    return [
        {
            "month": c.get("month"),
            "kwh": c.get("currentConsumption") or 0,
            "cost": tariff.monthly_cost(c.get("currentConsumption") or 0, t),
        }
        for c in _consumptions(data)
    ]


def _year_cost(data: dict):
    costs = [c["cost"] for c in _cost_history(data) if c["cost"] is not None]
    return round(sum(costs), 2) if costs else None


def _due_date(data: dict):
    inv = data.get("_invoice")
    if inv and inv.get("dueDate"):
        return dt_util.parse_datetime(inv["dueDate"])
    return None


def _latest_daily(data: dict):
    days = data.get("_daily") or []
    return days[-1]["kwh"] if days else None


def _day_total(data: dict):
    hours = data.get("_hourly") or []
    return round(sum(h["kwh"] for h in hours), 3) if hours else None


@dataclass(frozen=True, kw_only=True)
class CebSensor(SensorEntityDescription):
    value: Callable[[dict], object]


SENSORS: tuple[CebSensor, ...] = (
    CebSensor(
        key="amount_due",
        name="Amount due",
        native_unit_of_measurement="Rs",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",
        value=lambda d: d.get("totalAmtDue"),
    ),
    CebSensor(
        key="last_consumption",
        name="Last consumption",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value=lambda d: d.get("lastConsumptionDtl_consumption"),
    ),
    CebSensor(
        key="last_meter_reading",
        name="Last meter reading",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:counter",
        value=lambda d: d.get("lastMtrDtl_Amt"),
    ),
    CebSensor(
        key="due_date",
        name="Bill due date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_due_date,
    ),
    CebSensor(
        key="last_reading_date",
        name="Last reading date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda d: dt_util.parse_datetime(d["lastMtrDtl_Date"])
        if d.get("lastMtrDtl_Date")
        else None,
    ),
    CebSensor(
        key="tariff",
        name="Tariff",
        icon="mdi:tag",
        value=lambda d: d.get("tariff"),
    ),
    CebSensor(
        key="daily_consumption",
        name="Daily consumption",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:calendar-today",
        value=_latest_daily,
    ),
    CebSensor(
        key="latest_day_total",
        name="Latest day total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:clock-outline",
        value=_day_total,
    ),
    CebSensor(
        key="month_consumption",
        name="Current bill consumption",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:calendar-month",
        value=_month_kwh,
    ),
    CebSensor(
        key="estimated_month_cost",
        name="Estimated current bill",
        native_unit_of_measurement="Rs",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-multiple",
        value=_month_cost,
    ),
    CebSensor(
        key="year_consumption",
        name="Year consumption",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:calendar-range",
        value=_year_kwh,
    ),
    CebSensor(
        key="estimated_year_cost",
        name="Estimated year cost",
        native_unit_of_measurement="Rs",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-multiple",
        value=_year_cost,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add_entities
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    account = entry.data[CONF_ACCOUNT]
    entities: list = [CebEntity(store["main"], account, d) for d in SENSORS]
    entities.append(CebOutageSensor(store["outages"], entry))
    add_entities(entities)


class CebEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    entity_description: CebSensor

    def __init__(self, coordinator, account: str, desc: CebSensor) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_unique_id = f"{account}_{desc.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account)},
            name=f"CEB {account}",
            manufacturer="Central Electricity Board",
            model=(coordinator.data or {}).get("premAdd"),
        )

    @property
    def available(self) -> bool:
        # CEB data lags 1-2 days; keep last values through a failed poll instead of going unavailable
        return self.coordinator.data is not None

    @property
    def native_value(self):
        return self.entity_description.value(self.coordinator.data or {})

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "last_consumption":
            # 12-month history on the monthly-consumption sensor
            return {"history": data.get("consumptions")}
        if key == "daily_consumption":
            days = data.get("_daily") or []
            return {
                "date": days[-1]["date"] if days else None,
                "history": days[-30:],  # last 30 days with values, [{date,kwh}]
            }
        if key == "latest_day_total":
            hours = data.get("_hourly") or []
            return {
                "date": hours[0]["date"] if hours else None,
                "profile": hours,  # 24 hourly slots [{date,time (interval start),kwh}]
            }
        if key == "estimated_month_cost":
            return {
                "kwh_this_period": _month_kwh(data),
                "period_start": _period_start(data),  # last meter read; bill runs from here
                "tariff": _tariff_code(data),
                "estimate": True,  # uncalibrated; correct tariff.py from a real bill
                "excludes": "any VAT/CEB levy/fuel adjustment not in tariff.py",
            }
        if key == "estimated_year_cost":
            return {
                "tariff": _tariff_code(data),
                "estimate": True,
                "history": _cost_history(data),  # [{month,kwh,cost}] oldest->newest
            }
        return None


class CebOutageSensor(CoordinatorEntity, SensorEntity):
    """Count of CEB planned power outages for the configured district/locality."""

    _attr_has_entity_name = True
    _attr_name = "Planned outages"
    _attr_icon = "mdi:transmission-tower-off"
    _attr_native_unit_of_measurement = "outages"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        account = entry.data[CONF_ACCOUNT]
        self._entry = entry
        self._attr_unique_id = f"{account}_planned_outages"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account)}, name=f"CEB {account}"
        )

    def _matches(self) -> list[dict]:
        return filter_outages(
            self.coordinator.data or [],
            self._entry.options.get(CONF_DISTRICT),
            self._entry.options.get(CONF_LOCALITY),
        )

    @property
    def native_value(self):
        return len(self._matches())

    @property
    def extra_state_attributes(self):
        return {
            "district": self._entry.options.get(CONF_DISTRICT) or "all",
            "locality_filter": self._entry.options.get(CONF_LOCALITY) or None,
            "outages": self._matches(),  # [{district,date,start,end,locality,streets,raw}]
        }
