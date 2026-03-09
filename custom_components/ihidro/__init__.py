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
        
        FOLOSEȘTE WEB PORTAL API (async, via ihidro-browser microservice):
        1. scrape_all() → login + fetch PODs + index history
        2. submit_meter_reading() → login + submit
        """
        utility_account_number = call.data[ATTR_UTILITY_ACCOUNT_NUMBER]
        account_number = call.data[ATTR_ACCOUNT_NUMBER]
        meter_number = call.data[ATTR_METER_NUMBER]
        meter_reading = call.data["meter_reading"]
        reading_date_input = call.data.get("reading_date")
        
        # Convertim data în format DD/MM/YYYY (Web Portal)
        if reading_date_input:
            try:
                if "/" in reading_date_input:
                    parts = reading_date_input.split("/")
                    if len(parts) == 3:
                        if int(parts[0]) > 12:
                            reading_date = reading_date_input
                        else:
                            reading_date = f"{parts[1]}/{parts[0]}/{parts[2]}"
                    else:
                        reading_date = datetime.now().strftime("%d/%m/%Y")
                else:
                    reading_date = datetime.now().strftime("%d/%m/%Y")
            except Exception:
                reading_date = datetime.now().strftime("%d/%m/%Y")
        else:
            reading_date = datetime.now().strftime("%d/%m/%Y")
        
        _LOGGER.info(
            "Trimitem index %s pentru contorul %s (UAN: %s, AN: %s, Data: %s)",
            meter_reading, meter_number, utility_account_number, account_number, reading_date
        )
        
        web_api = coordinator.web_api
        
        if not web_api.is_configured:
            _LOGGER.error(
                "Browser service URL is not configured. "
                "Set it in the iHidro integration options."
            )
            return
        
        try:
            # Step 1: Scrape all data (login + fetch PODs + index history)
            _LOGGER.info("Web Portal: Fetching POD data via browser service...")
            await web_api.scrape_all()
            
            pods = web_api.get_cached_pods()
            if not pods:
                _LOGGER.error("Nu s-au găsit POD-uri în Web Portal")
                return
            
            # Step 2: Find the target POD
            # Use first POD (single-POD account) or match by installation/pod
            target_pod = pods[0]
            pod_value = target_pod.get("pod", "")
            installation = target_pod.get("installation", "")
            
            _LOGGER.debug(
                "Using POD: %s, Installation: %s", pod_value, installation
            )
            
            # Step 3: Get latest reading from cache
            latest = web_api.get_cached_latest_reading(installation, pod_value)
            if latest:
                prev_reading = int(latest.get("index", 0))
                counter_series = latest.get("counter_series", meter_number)
            else:
                _LOGGER.warning("Nu am găsit index anterior, folosim 0")
                prev_reading = 0
                counter_series = meter_number
            
            # Step 3b: Get additional fields from raw index history
            # The submit payload needs distCustomer, distCustomerId, etc.
            # which are available in the raw LoadW2UIGridData response.
            additional_data = {}
            raw_history = web_api.get_cached_index_history(installation, pod_value)
            if raw_history:
                first = raw_history[0]
                additional_data = {
                    "registerCat": first.get("Registers", "1.8.0"),
                    "distributor": first.get("Distributor", "DELGAZ GRID"),
                    "meterInterval": first.get("MeterInterval", "lunar"),
                    "supplier": first.get("Supplier", "HE"),
                    "distCustomer": first.get("DistCustomer", ""),
                    "distCustomerId": first.get("DistCustomerId", ""),
                    "distContract": first.get("DistContract", ""),
                    "distContractDate": first.get("DistContractDate", ""),
                }
            
            _LOGGER.info(
                "Web Portal submit: POD=%s, Installation=%s, CounterSeries=%s, "
                "PrevReading=%s, NewReading=%s",
                pod_value, installation, counter_series, prev_reading, int(meter_reading)
            )
            
            # Step 4: Submit the reading (async)
            result = await web_api.submit_meter_reading(
                pod=pod_value,
                installation=installation,
                utility_account_number=utility_account_number,
                counter_series=counter_series,
                prev_reading=prev_reading,
                new_reading=int(meter_reading),
                reading_date=reading_date,
                additional_data=additional_data if additional_data else None,
            )
            
            if result.get("success"):
                _LOGGER.info("Index trimis cu succes prin Web Portal: %s", result.get("message"))
                await coordinator.async_request_refresh()
            else:
                _LOGGER.error("Eroare la trimiterea indexului: %s", result.get("message"))
                
        except Exception as err:
            _LOGGER.error("Exceptie la trimiterea indexului: %s", err, exc_info=True)
    
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
        # Închidem sesiunea Mobile API (sync — in executor)
        await hass.async_add_executor_job(coordinator.api.close)
        # Închidem Web Portal API (async — no-op but clean)
        try:
            await coordinator.web_api.close()
        except Exception:
            _LOGGER.debug("Web Portal API close failed (non-fatal)")
    
    # Dezînregistrăm serviciul doar dacă nu mai sunt alte entry-uri
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SUBMIT_METER_READING)
    
    return unload_ok
