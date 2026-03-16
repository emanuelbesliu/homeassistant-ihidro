"""Config flow pentru iHidro.

Implementează:
- Pas 1: Credențiale (username/password)
- Pas 2: Selecție conturi/POD-uri (dacă utilizatorul are mai multe)
- Reauth flow: Re-autentificare când token-ul expiră
- Options flow: Interval actualizare + senzor energie extern opțional
- Config entry versiune 3
"""

import logging
from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)

from .api import IhidroAPI, IhidroAuthError, IhidroApiError
from .const import (
    DOMAIN,
    CONFIG_VERSION,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_SELECTED_ACCOUNTS,
    CONF_ENERGY_SENSOR,
    CONF_TOKEN_USER_ID,
    CONF_TOKEN_SESSION,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class IhidroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow pentru iHidro."""

    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        """Inițializare config flow."""
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._update_interval: int = DEFAULT_UPDATE_INTERVAL
        self._accounts: List[Dict[str, Any]] = []
        self._reauth_entry: Optional[config_entries.ConfigEntry] = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Pasul 1: Credențiale (username și password)."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._update_interval = user_input.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            )

            # Validăm credențialele
            try:
                session = async_get_clientsession(self.hass)
                api = IhidroAPI(
                    session=session,
                    username=self._username,
                    password=self._password,
                )
                await api.login()
                self._accounts = api.get_utility_accounts()

                if not self._accounts:
                    errors["base"] = "no_accounts"
                elif len(self._accounts) > 1:
                    # Mai multe conturi — mergi la selecție
                    return await self.async_step_select_accounts()
                else:
                    # Un singur cont — creăm direct intrarea
                    return await self._create_entry(
                        selected=[self._accounts[0]["UtilityAccountNumber"]]
                    )

            except IhidroAuthError:
                errors["base"] = "invalid_auth"
            except IhidroApiError:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.error("Eroare neașteptată la autentificare iHidro: %s", err)
                errors["base"] = "unknown"

        # Schema formularului
        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_select_accounts(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Pasul 2: Selecție conturi (dacă utilizatorul are mai multe POD-uri)."""
        if user_input is not None:
            selected = user_input.get(CONF_SELECTED_ACCOUNTS, [])
            if not selected:
                # Dacă nu a selectat nimic, luăm toate conturile
                selected = [
                    acc["UtilityAccountNumber"] for acc in self._accounts
                ]
            return await self._create_entry(selected=selected)

        # Construim opțiunile de selecție folosind SelectSelector (HA native)
        account_options = [
            SelectOptionDict(
                value=acc["UtilityAccountNumber"],
                label=f"{acc.get('Address', 'Adresă necunoscută')} → {acc['UtilityAccountNumber']}",
            )
            for acc in self._accounts
        ]

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_ACCOUNTS,
                    default=[acc["UtilityAccountNumber"] for acc in self._accounts],
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=account_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select_accounts",
            data_schema=data_schema,
        )

    # =========================================================================
    # Reauth flow — re-autentificare când credențialele expiră
    # =========================================================================

    async def async_step_reauth(
        self, entry_data: Dict[str, Any]
    ) -> FlowResult:
        """Pasul de reautentificare (declanșat automat de HA)."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Confirmarea reautentificării cu credențiale noi."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            try:
                session = async_get_clientsession(self.hass)
                api = IhidroAPI(
                    session=session,
                    username=username,
                    password=password,
                )
                await api.login()

                # Actualizăm credențialele în config entry
                if self._reauth_entry:
                    new_data = {**self._reauth_entry.data}
                    new_data[CONF_USERNAME] = username
                    new_data[CONF_PASSWORD] = password
                    # Invalidăm token-urile vechi
                    new_data.pop(CONF_TOKEN_USER_ID, None)
                    new_data.pop(CONF_TOKEN_SESSION, None)
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry, data=new_data
                    )
                    await self.hass.config_entries.async_reload(
                        self._reauth_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")

            except IhidroAuthError:
                errors["base"] = "invalid_auth"
            except IhidroApiError:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.error("Eroare la reautentificare iHidro: %s", err)
                errors["base"] = "unknown"

        # Pre-completăm cu username-ul existent
        existing_username = ""
        if self._reauth_entry:
            existing_username = self._reauth_entry.data.get(CONF_USERNAME, "")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=existing_username): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=errors,
        )

    # =========================================================================
    # Crearea config entry
    # =========================================================================

    async def _create_entry(self, selected: List[str]) -> FlowResult:
        """Creăm config entry cu conturile selectate."""
        # Verificăm dacă nu există deja o intrare cu același username
        await self.async_set_unique_id(self._username)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"iHidro ({self._username})",
            data={
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                CONF_UPDATE_INTERVAL: self._update_interval,
                CONF_SELECTED_ACCOUNTS: selected,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Returnează flow-ul de opțiuni."""
        return IhidroOptionsFlowHandler()


class IhidroOptionsFlowHandler(config_entries.OptionsFlow):
    """Gestionează opțiunile pentru iHidro."""

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Gestionează pasul de opțiuni."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Validăm senzorul de energie extern dacă a fost selectat
            energy_sensor_id = user_input.get(CONF_ENERGY_SENSOR, "")
            if energy_sensor_id:
                validation_error = self._validate_energy_sensor(energy_sensor_id)
                if validation_error:
                    errors["energy_sensor"] = validation_error
                else:
                    # Validarea a trecut — salvăm
                    return self.async_create_entry(title="", data=user_input)
            else:
                # Niciun senzor selectat (opțional, OK) — ștergem valoarea veche
                user_input[CONF_ENERGY_SENSOR] = ""
                return self.async_create_entry(title="", data=user_input)

        # Obținem valorile curente
        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            self.config_entry.data.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            ),
        )
        current_energy_sensor = self.config_entry.options.get(
            CONF_ENERGY_SENSOR, ""
        )

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                ),
                vol.Optional(
                    CONF_ENERGY_SENSOR, default=current_energy_sensor
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor",
                        device_class=SensorDeviceClass.ENERGY,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )

    def _validate_energy_sensor(self, entity_id: str) -> Optional[str]:
        """Validează senzorul de energie extern selectat.

        Verificări:
        1. Entitatea există în HA
        2. Are device_class = energy
        3. Are state_class = total_increasing (contor cumulativ)
        4. Starea nu este unavailable/unknown
        5. Starea este un număr valid
        6. Unitatea de măsură este kWh sau Wh (nu W, kW etc.)

        Returnează None dacă totul e OK, sau o cheie de eroare din strings.json.
        """
        hass = self.hass

        # 1. Entitatea există?
        state_obj = hass.states.get(entity_id)
        if state_obj is None:
            _LOGGER.warning(
                "Senzor energie extern '%s' nu a fost găsit în HA", entity_id
            )
            return "energy_sensor_not_found"

        attributes = state_obj.attributes

        # 2. device_class trebuie să fie "energy"
        device_class = attributes.get("device_class", "")
        if device_class != SensorDeviceClass.ENERGY:
            _LOGGER.warning(
                "Senzor '%s' are device_class='%s', așteptat 'energy'",
                entity_id,
                device_class,
            )
            return "energy_sensor_wrong_class"

        # 3. state_class trebuie să fie "total_increasing" (contor cumulativ kWh)
        state_class = attributes.get("state_class", "")
        if state_class not in (
            SensorStateClass.TOTAL_INCREASING,
            SensorStateClass.TOTAL,
            "total_increasing",
            "total",
        ):
            _LOGGER.warning(
                "Senzor '%s' are state_class='%s', așteptat 'total_increasing' sau 'total' "
                "(contor cumulativ de energie)",
                entity_id,
                state_class,
            )
            return "energy_sensor_not_cumulative"

        # 4. Unitatea trebuie să fie kWh sau Wh
        unit = attributes.get("unit_of_measurement", "")
        if unit not in ("kWh", "Wh"):
            _LOGGER.warning(
                "Senzor '%s' are unitate='%s', așteptat 'kWh' sau 'Wh'",
                entity_id,
                unit,
            )
            return "energy_sensor_wrong_unit"

        # 5. Starea nu este unavailable/unknown
        state_val = state_obj.state
        if state_val in ("unavailable", "unknown", None):
            _LOGGER.warning(
                "Senzor '%s' are starea '%s' — nu este disponibil momentan",
                entity_id,
                state_val,
            )
            return "energy_sensor_unavailable"

        # 6. Starea trebuie să fie un număr valid
        try:
            float(state_val)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Senzor '%s' are starea '%s' — nu este un număr valid",
                entity_id,
                state_val,
            )
            return "energy_sensor_not_numeric"

        _LOGGER.debug(
            "Senzor energie extern '%s' validat cu succes: state=%s, unit=%s, "
            "state_class=%s, device_class=%s",
            entity_id,
            state_val,
            unit,
            state_class,
            device_class,
        )
        return None
