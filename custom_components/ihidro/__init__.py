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
        """
        Handler pentru serviciul de trimitere index.
        
        FOLOSEȘTE WEB PORTAL API pentru trimitere!
        """
        utility_account_number = call.data[ATTR_UTILITY_ACCOUNT_NUMBER]
        account_number = call.data[ATTR_ACCOUNT_NUMBER]
        meter_number = call.data[ATTR_METER_NUMBER]
        meter_reading = call.data["meter_reading"]
        reading_date_input = call.data.get("reading_date")
        
        # Convertim data din format MM/DD/YYYY (Mobile API) în DD/MM/YYYY (Web Portal)
        if reading_date_input:
            try:
                # Parsăm data (suportăm ambele formate)
                if "/" in reading_date_input:
                    parts = reading_date_input.split("/")
                    if len(parts) == 3:
                        # Detectăm formatul automat
                        if int(parts[0]) > 12:
                            # Format DD/MM/YYYY
                            reading_date = reading_date_input
                        else:
                            # Format MM/DD/YYYY - convertim
                            reading_date = f"{parts[1]}/{parts[0]}/{parts[2]}"
                    else:
                        reading_date = datetime.now().strftime("%d/%m/%Y")
                else:
                    reading_date = datetime.now().strftime("%d/%m/%Y")
            except:
                reading_date = datetime.now().strftime("%d/%m/%Y")
        else:
            reading_date = datetime.now().strftime("%d/%m/%Y")
        
        _LOGGER.info(
            "Trimitem index %s pentru contorul %s (UAN: %s, AN: %s, Data: %s)",
            meter_reading, meter_number, utility_account_number, account_number, reading_date
        )
        
        try:
            # Găsim POD-ul corespunzător în date
            account_data = None
            for acc in coordinator.data.get("accounts", []):
                acc_info = acc.get("account_info", {})
                if acc_info.get("UtilityAccountNumber") == utility_account_number:
                    account_data = acc
                    break
            
            if not account_data:
                _LOGGER.error("Nu am găsit POD-ul %s în date", utility_account_number)
                return
            
            # Obținem datele necesare din Web Portal
            web_pod_info = account_data.get("web_pod_info")
            meter_reading_data = account_data.get("meter_reading")
            
            if not web_pod_info:
                _LOGGER.error(
                    "Nu avem date Web Portal pentru POD %s. "
                    "Asigurați-vă că integrarea este configurată corect.",
                    utility_account_number
                )
                return
            
            if not meter_reading_data:
                _LOGGER.warning("Nu avem index anterior pentru POD %s", utility_account_number)
                prev_reading = 0
            else:
                prev_reading = int(meter_reading_data.get("index", 0))
            
            # Date pentru submit
            pod = web_pod_info["pod"]
            installation = web_pod_info["installation"]
            counter_series = meter_reading_data.get("counter_series") if meter_reading_data else meter_number
            
            _LOGGER.debug(
                "Date pentru submit: POD=%s, Installation=%s, CounterSeries=%s, PrevReading=%s",
                pod, installation, counter_series, prev_reading
            )
            
            # Trimitem indexul prin Web Portal API
            result = await hass.async_add_executor_job(
                coordinator.web_api.submit_meter_reading,
                pod,
                installation,
                utility_account_number,
                counter_series,
                prev_reading,
                int(meter_reading),
                reading_date,
                None  # additional_data - folosim defaults
            )
            
            if result.get("success"):
                _LOGGER.info("✅ Index trimis cu succes prin Web Portal: %s", result.get("message"))
                # Refresh data după submit
                await coordinator.async_request_refresh()
            else:
                _LOGGER.error("❌ Eroare la trimiterea indexului: %s", result.get("message"))
                
        except Exception as err:
            _LOGGER.error("❌ Excepție la trimiterea indexului: %s", err, exc_info=True)
    
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
        # Închidem sesiunile API (ambele)
        await hass.async_add_executor_job(coordinator.api.close)
        await hass.async_add_executor_job(coordinator.web_api.close)
    
    # Dezînregistrăm serviciul doar dacă nu mai sunt alte entry-uri
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SUBMIT_METER_READING)
    
    return unload_ok
