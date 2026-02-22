"""Config flow pentru iHidro."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .api import IhidroAPI
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class IhidroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow pentru iHidro."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Gestionează pasul inițial de configurare (username și password)."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Validăm credențialele
            try:
                # Testăm autentificarea în background
                api = IhidroAPI(
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                )
                
                await self.hass.async_add_executor_job(api.login)
                await self.hass.async_add_executor_job(api.close)
                
                # Verificăm dacă nu există deja o intrare cu același username
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()
                
                # Creăm intrarea de configurare
                return self.async_create_entry(
                    title=f"iHidro ({user_input[CONF_USERNAME]})",
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_UPDATE_INTERVAL: user_input.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    },
                )
                
            except Exception as err:
                _LOGGER.error("Eroare la autentificare iHidro: %s", err)
                errors["base"] = "invalid_auth"

        # Schema formularului
        data_schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=DEFAULT_UPDATE_INTERVAL
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Returnează flow-ul de opțiuni."""
        return IhidroOptionsFlowHandler(config_entry)


class IhidroOptionsFlowHandler(config_entries.OptionsFlow):
    """Gestionează opțiunile pentru iHidro."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Inițializare options flow handler."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Gestionează pasul de opțiuni."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Obținem valoarea curentă sau valoarea din data
        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )

        options_schema = vol.Schema({
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=current_interval
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
