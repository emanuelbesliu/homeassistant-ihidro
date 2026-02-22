"""Integrarea iHidro pentru Home Assistant."""
import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    SERVICE_SUBMIT_METER_READING,
    ATTR_UTILITY_ACCOUNT_NUMBER,
    ATTR_ACCOUNT_NUMBER,
    ATTR_METER_NUMBER,
)
from .coordinator import IhidroDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# Schema pentru serviciul de trimitere index
SUBMIT_METER_READING_SCHEMA = vol.Schema({
    vol.Required(ATTR_UTILITY_ACCOUNT_NUMBER): str,
    vol.Required(ATTR_ACCOUNT_NUMBER): str,
    vol.Required(ATTR_METER_NUMBER): str,
    vol.Required("meter_reading"): vol.Coerce(float),
    vol.Optional("reading_date"): str,
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Configurare componentă din configuration.yaml (nu este folosită)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurare integrare din config entry."""
    _LOGGER.debug("=== iHidro: Începem setup pentru entry %s ===", entry.entry_id)
    
    # Inițializăm coordinator-ul
    coordinator = IhidroDataUpdateCoordinator(hass, entry)
    
    # Facem primul refresh de date
    await coordinator.async_config_entry_first_refresh()
    
    # Stocăm coordinator-ul în hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Înregistrăm platformele (sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Înregistrăm serviciul de trimitere index
    async def handle_submit_meter_reading(call: ServiceCall) -> None:
        """Handler pentru serviciul de trimitere index."""
        utility_account_number = call.data[ATTR_UTILITY_ACCOUNT_NUMBER]
        account_number = call.data[ATTR_ACCOUNT_NUMBER]
        meter_number = call.data[ATTR_METER_NUMBER]
        meter_reading = call.data["meter_reading"]
        reading_date = call.data.get("reading_date", datetime.now().strftime("%m/%d/%Y"))
        
        _LOGGER.info(
            "Trimitem index %s pentru contorul %s (UAN: %s, AN: %s)",
            meter_reading, meter_number, utility_account_number, account_number
        )
        
        try:
            # Apelăm metoda API pentru trimitere index
            result = await hass.async_add_executor_job(
                coordinator.api.submit_meter_reading,
                utility_account_number,
                account_number,
                meter_number,
                meter_reading,
                reading_date
            )
            
            if result.get("success"):
                _LOGGER.info("Index trimis cu succes: %s", result.get("message"))
            else:
                _LOGGER.error("Eroare la trimiterea indexului: %s", result.get("message"))
                
        except Exception as err:
            _LOGGER.error("Excepție la trimiterea indexului: %s", err)
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_SUBMIT_METER_READING,
        handle_submit_meter_reading,
        schema=SUBMIT_METER_READING_SCHEMA,
    )
    
    _LOGGER.debug("=== iHidro: Setup completat cu succes ===")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Dezinstalare integrare."""
    _LOGGER.debug("=== iHidro: Dezinstalăm entry %s ===", entry.entry_id)
    
    # Dezinstalăm platformele
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Ștergem coordinator-ul din hass.data
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # Închidem sesiunea API
        await hass.async_add_executor_job(coordinator.api.close)
    
    # Dezînregistrăm serviciul doar dacă nu mai sunt alte entry-uri
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SUBMIT_METER_READING)
    
    return unload_ok
