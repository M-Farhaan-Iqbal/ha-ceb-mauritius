"""Tiny CEB MoKouran API client. Token is derived from deviceId+pin via loginPin (14-day ttl),
re-fetched on demand, so nothing but deviceId+pin+account needs storing."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp

from .const import BASE_URL

_LOGGER = logging.getLogger(__name__)
MU_TZ = ZoneInfo("Indian/Mauritius")  # CEB only serves Mauritius


class CebRegisterError(Exception):
    """Registration / activation failed (bad email, code, or server error)."""


def new_device_id() -> str:
    """A fresh device id for registering this HA install as its own MoKouran device."""
    return uuid.uuid4().hex


async def _public_post(session: aiohttp.ClientSession, path: str, body: dict) -> dict:
    """POST with no auth; raise CebRegisterError on any non-2xx."""
    async with session.post(f"{BASE_URL}{path}", json=body) as r:
        text = await r.text()
        if r.status >= 300:
            raise CebRegisterError(f"{path} {r.status}: {text[:200]}")
        return await r.json() if text else {}


async def request_registration_code(
    session: aiohttp.ClientSession, email: str, pin: str
) -> None:
    """Ask CEB to email a one-time code to register this device. The chosen PIN is sent
    now and must be reused at activation. 204 on success; CebRegisterError otherwise
    (e.g. USER_NOT_EXIST if the email is not a MoKouran app user)."""
    await _public_post(
        session,
        "AppUsers/requestPinReRegistration",
        {"contactEmail": email, "pinCode": pin},
    )


async def activate_device(
    session: aiohttp.ClientSession, email: str, code: str, pin: str, device_id: str
) -> None:
    """Bind device_id to the account with the emailed code and a chosen 4-digit PIN."""
    await _public_post(
        session,
        "AppUsers/activateAccountOnAnotherDevice",
        {"contactEmail": email, "code": code, "pinCode": pin, "deviceId": device_id},
    )


def _day(row: dict) -> date:
    return date.fromisoformat(row["date"][:10])


def _req_date(d: date) -> str:
    return f"{d.isoformat()}T00:00:00.000Z"


class CebAuthError(Exception):
    """Bad deviceId/PIN."""


class CebApi:
    def __init__(self, session: aiohttp.ClientSession, device_id: str, pin: str) -> None:
        self._session = session
        self._device_id = device_id
        self._pin = pin
        self._token: str | None = None
        self._registers: list | None = None  # static meter list, fetched once

    async def _login(self) -> str:
        async with self._session.post(
            f"{BASE_URL}Accounts/loginPin",
            json={"deviceId": self._device_id, "pinCode": self._pin},
        ) as r:
            if r.status in (400, 401, 404):
                raise CebAuthError(f"loginPin {r.status}: {await r.text()}")
            r.raise_for_status()
            self._token = (await r.json())["id"]
            return self._token

    async def _get(self, path: str, _retry: bool = True) -> dict | list:
        if self._token is None:
            await self._login()
        async with self._session.get(
            f"{BASE_URL}{path}", headers={"Authorization": self._token}
        ) as r:
            if r.status == 401 and _retry:  # token expired -> relogin once
                self._token = None
                return await self._get(path, _retry=False)
            r.raise_for_status()
            return await r.json()

    async def _post(self, path: str, body: dict, _retry: bool = True) -> dict | list:
        if self._token is None:
            await self._login()
        async with self._session.post(
            f"{BASE_URL}{path}", json=body, headers={"Authorization": self._token}
        ) as r:
            if r.status == 401 and _retry:
                self._token = None
                return await self._post(path, body, _retry=False)
            r.raise_for_status()
            return await r.json()

    async def dashboard(self, account: str) -> dict:
        return await self._get(
            f"ContractAccounts/getMyDashboardDetail?accountNumber={account}"
        )

    async def latest_invoice(self, account: str) -> dict | None:
        rows = await self._get(
            f"MasterInvoices/getMyInvoicesByContractAccount?accountNumber={account}"
        )
        return rows[0] if rows else None

    async def _register(self, account: str) -> dict | None:
        if self._registers is None:
            self._registers = await self._get(
                f"Meters/getMeterRegisterList?contractAcctNo={account}"
            )
        return next(
            (r for r in self._registers if r.get("registerName") == "KWH-IMP"),
            (self._registers or [None])[0],
        )

    async def _ems(self, account: str, reg: dict, graph_type: str, date: str) -> list[dict]:
        # isAmr=True: CEB's register flag mislabels smart meters, but the backend
        # returns real interval data when asked with isAmr true.
        res = await self._post(
            "EmsConsumptions/getEmsConsumptionData",
            {
                "date": date,
                "graphType": graph_type,
                "meterNo": reg["meterNo"],
                "regName": reg["registerName"],
                "contractAcctNo": account,
                "duration1": "",
                "duration2": "",
                "intervalNo": 12,
                "isAmr": True,
            },
        )
        return res.get("consumptionList", [])

    async def daily_consumption(self, account: str) -> list[dict]:
        """Per-day kWh (graphType MONTHLY = days of the current month).
        CEB labels each value with the midnight meter read that closes the day,
        so the value dated D is the usage of day D-1. Returns [{"date","kwh"}]
        keyed by the real usage day, only days with a value."""
        reg = await self._register(account)
        if not reg:
            return []
        today = datetime.now(MU_TZ).date()
        rows = await self._ems(account, reg, "MONTHLY", _req_date(today))
        return [
            {"date": (_day(r) - timedelta(days=1)).isoformat(), "kwh": r["val"]}
            for r in rows
            if r.get("val")
        ]

    async def hourly_consumption(self, account: str) -> list[dict]:
        """Hourly kWh for the most recent complete day (graphType DAILY).
        A DAILY request for day D returns days D-1 and D, 24 rows each, and
        "times" is the interval end: "00:00" on D is 23:00-24:00 of D-1.
        Returns 24 rows [{"date","time" (interval start),"kwh"}], or []."""
        reg = await self._register(account)
        if not reg:
            return []
        today = datetime.now(MU_TZ).date()
        for back in range(1, 4):  # yesterday first; data lags about a day
            day = today - timedelta(days=back)
            rows = await self._ems(
                account, reg, "DAILY", _req_date(day + timedelta(days=1))
            )
            slots = {}
            for r in rows:
                start = datetime.combine(_day(r), datetime.min.time()) + timedelta(
                    hours=int(r["times"][:2]) - 1
                )
                if start.date() == day:
                    slots[start] = r.get("val") or 0
            # complete = all 24 hours present and the last one (next day's 00:00) has data
            last = datetime.combine(day, datetime.min.time()) + timedelta(hours=23)
            if len(slots) == 24 and slots.get(last):
                return [
                    {"date": day.isoformat(), "time": k.strftime("%H:%M"), "kwh": v}
                    for k, v in sorted(slots.items())
                ]
        return []

    async def validate(self) -> None:
        """Raise CebAuthError if deviceId/PIN are wrong."""
        await self._login()
