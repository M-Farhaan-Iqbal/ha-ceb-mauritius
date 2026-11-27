"""Config flow for CEB Mauritius.

Default path is friendly: enter email -> CEB emails a code -> enter code, choose a PIN,
enter the account number -> HA registers itself as a new MoKouran device and stores
deviceId + PIN + account. An 'advanced' path takes an existing deviceId + PIN directly.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CebApi,
    CebAuthError,
    CebRegisterError,
    activate_device,
    new_device_id,
    request_registration_code,
)
from .const import (
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_DISTRICT,
    CONF_EMAIL,
    CONF_LOCALITY,
    CONF_PIN,
    DISTRICTS,
    DOMAIN,
)

REGISTER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PIN): str,
        vol.Required(CONF_ACCOUNT): str,
    }
)
ACTIVATE_SCHEMA = vol.Schema({vol.Required("code"): str})
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PIN): str})
MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_PIN): str,
        vol.Required(CONF_ACCOUNT): str,
    }
)


class CebConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CebOptionsFlow()

    def __init__(self) -> None:
        self._email: str | None = None
        self._pin: str | None = None
        self._account: str | None = None
        self._device_id: str | None = None

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Entry: choose the friendly email path or the advanced device-id path."""
        return self.async_show_menu(
            step_id="user", menu_options=["register", "manual"]
        )

    async def async_step_register(self, user_input=None) -> ConfigFlowResult:
        """Step 1: MoKouran email + a chosen PIN + account. CEB emails a one-time code.
        The PIN is sent now and reused at activation (CEB's requestPinReRegistration)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._pin = user_input[CONF_PIN]
            self._account = user_input[CONF_ACCOUNT]
            self._device_id = new_device_id()
            await self.async_set_unique_id(self._account)
            self._abort_if_unique_id_configured()
            try:
                await request_registration_code(
                    async_get_clientsession(self.hass), self._email, self._pin
                )
            except CebRegisterError as err:
                errors["base"] = (
                    "user_not_found" if "USER_NOT_EXIST" in str(err) else "cannot_connect"
                )
            else:
                return await self.async_step_activate()
        return self.async_show_form(
            step_id="register", data_schema=REGISTER_SCHEMA, errors=errors
        )

    async def async_step_activate(self, user_input=None) -> ConfigFlowResult:
        """Step 2: the emailed code -> bind this device and verify, then create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                await activate_device(
                    session, self._email, user_input["code"], self._pin, self._device_id
                )
                api = CebApi(session, self._device_id, self._pin)
                await api.validate()
                await api.dashboard(self._account)
            except CebRegisterError:
                errors["base"] = "bad_code"
            except CebAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"CEB {self._account}",
                    data={
                        CONF_DEVICE_ID: self._device_id,
                        CONF_PIN: self._pin,
                        CONF_ACCOUNT: self._account,
                        CONF_EMAIL: self._email,
                    },
                )
        return self.async_show_form(
            step_id="activate", data_schema=ACTIVATE_SCHEMA, errors=errors
        )

    async def async_step_manual(self, user_input=None) -> ConfigFlowResult:
        """Advanced path: an existing deviceId + PIN (e.g. reused from another device)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_ACCOUNT])
            self._abort_if_unique_id_configured()
            api = CebApi(
                async_get_clientsession(self.hass),
                user_input[CONF_DEVICE_ID],
                user_input[CONF_PIN],
            )
            try:
                await api.validate()
                await api.dashboard(user_input[CONF_ACCOUNT])
            except CebAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"CEB {user_input[CONF_ACCOUNT]}", data=user_input
                )
        return self.async_show_form(
            step_id="manual", data_schema=MANUAL_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the stored PIN stops working (ConfigEntryAuthFailed)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        """Ask for the PIN again and validate it with loginPin before resuming."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            api = CebApi(
                async_get_clientsession(self.hass),
                entry.data[CONF_DEVICE_ID],
                user_input[CONF_PIN],
            )
            try:
                await api.validate()
            except CebAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PIN: user_input[CONF_PIN]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"account": entry.data[CONF_ACCOUNT]},
        )


class CebOptionsFlow(OptionsFlow):
    """Options: which district's planned outages to show, and an optional locality filter."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DISTRICT, default=opts.get(CONF_DISTRICT, "")
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        options=[
                            selector.SelectOptionDict(value="", label="All districts")
                        ]
                        + [
                            selector.SelectOptionDict(value=k, label=v)
                            for k, v in DISTRICTS.items()
                        ],
                    )
                ),
                vol.Optional(CONF_LOCALITY, default=opts.get(CONF_LOCALITY, "")): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
