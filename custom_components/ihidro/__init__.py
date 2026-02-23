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
        
        FOLOSEȘTE WEB PORTAL API on-demand:
        1. Login la Web Portal (cu 2captcha)
        2. GetAllPODBind → găsește POD-ul
        3. LoadW2UIGridData → obține ultimul index
        4. SubmitSelfMeterReading → trimite noul index
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
        
        try:
            # On-demand: Login la Web Portal + fetch PODs + get latest reading + submit
            def _do_web_portal_submit():
                """Execută tot fluxul Web Portal sincron (rulează în executor)."""
                web_api = coordinator.web_api
                
                # Step 1: Login (rezolvă captcha via 2captcha)
                _LOGGER.info("Web Portal: Autentificare on-demand pentru submit...")
                web_api.login()
                
                # Step 2: Obținem lista de POD-uri
                pods = web_api.get_all_pods()
                if not pods:
                    return {"success": False, "message": "Nu s-au găsit POD-uri în Web Portal", "data": None}
                
                # Step 3: Găsim POD-ul corespunzător
                target_pod = None
                for pod in pods:
                    if pod.get("contractAccountID") == utility_account_number:
                        target_pod = pod
                        break
                
                if not target_pod:
                    # Dacă nu găsim după contractAccountID, luăm primul POD
                    _LOGGER.warning(
                        "Nu am găsit POD cu contractAccountID=%s, folosim primul POD: %s",
                        utility_account_number, pods[0].get("pod")
                    )
                    target_pod = pods[0]
                
                pod_value = target_pod["pod"]
                installation = target_pod["installation"]
                
                # Step 4: Obținem ultimul index
                latest = web_api.get_latest_meter_reading(installation, pod_value)
                if latest:
                    prev_reading = int(latest.get("index", 0))
                    counter_series = latest.get("counter_series", meter_number)
                else:
                    _LOGGER.warning("Nu am găsit index anterior, folosim 0")
                    prev_reading = 0
                    counter_series = meter_number
                
                _LOGGER.info(
                    "Web Portal submit: POD=%s, Installation=%s, CounterSeries=%s, "
                    "PrevReading=%s, NewReading=%s",
                    pod_value, installation, counter_series, prev_reading, int(meter_reading)
                )
                
                # Step 5: Trimitem indexul
                return web_api.submit_meter_reading(
                    pod=pod_value,
                    installation=installation,
                    utility_account_number=utility_account_number,
                    counter_series=counter_series,
                    prev_reading=prev_reading,
                    new_reading=int(meter_reading),
                    reading_date=reading_date,
                )
            
            result = await hass.async_add_executor_job(_do_web_portal_submit)
            
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
        # Închidem sesiunile API (ambele)
        await hass.async_add_executor_job(coordinator.api.close)
        try:
            await hass.async_add_executor_job(coordinator.web_api.close)
        except Exception:
            _LOGGER.debug("Web Portal API close failed (non-fatal)")
    
    # Dezînregistrăm serviciul doar dacă nu mai sunt alte entry-uri
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SUBMIT_METER_READING)
    
    return unload_ok
