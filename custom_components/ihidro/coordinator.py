"""Data Update Coordinator pentru iHidro."""
import logging
from datetime import timedelta, datetime
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import IhidroAPI
from .web_portal_api import IhidroWebPortalAPI
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_BROWSER_SERVICE_URL,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_BROWSER_SERVICE_URL,
)

_LOGGER = logging.getLogger(__name__)


class IhidroDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator pentru actualizarea datelor iHidro."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Inițializare coordinator."""
        self.entry = entry
        
        # Inițializăm ambele API-uri (Mobile + Web Portal)
        self.api = IhidroAPI(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
        )
        
        # Browser service URL: check options first, then data, then default
        browser_service_url = (
            entry.options.get(CONF_BROWSER_SERVICE_URL)
            or entry.data.get(CONF_BROWSER_SERVICE_URL)
            or DEFAULT_BROWSER_SERVICE_URL
        )
        
        self.web_api = IhidroWebPortalAPI(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            browser_service_url=browser_service_url,
        )
        
        # Intervalul de actualizare (implicit 1 oră)
        update_interval = entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """
        Actualizează datele de la API.
        
        Returns:
            Dict cu toate datele pentru toate POD-urile
        """
        try:
            # Mobile API is synchronous — run in executor
            data = await self.hass.async_add_executor_job(self._fetch_mobile_data)
            
            # Web Portal API is async — try to fetch web portal data if configured
            if self.web_api.is_configured:
                try:
                    await self.web_api.scrape_all()
                    
                    # Enrich account data with web portal data
                    for account_data in data.get("accounts", []):
                        account_info = account_data.get("account_info", {})
                        uan = account_info.get("UtilityAccountNumber", "")
                        
                        # Match web portal PODs to mobile API accounts
                        for pod_info in self.web_api.get_cached_pods():
                            pod_value = pod_info.get("pod", "")
                            installation = pod_info.get("installation", "")
                            
                            # Store web portal data on the account
                            account_data["web_pod_info"] = pod_info
                            
                            # Get latest meter reading from web portal
                            latest = self.web_api.get_cached_latest_reading(
                                installation, pod_value
                            )
                            if latest:
                                account_data["meter_reading"] = latest
                            
                            # Get full index history
                            history = self.web_api.get_cached_index_history(
                                installation, pod_value
                            )
                            if history:
                                account_data["meter_history"] = history
                            
                            # For now, match first POD to first account
                            # TODO: proper matching by UAN when multiple PODs
                            break
                            
                except Exception as web_err:
                    _LOGGER.warning(
                        "Web Portal data fetch failed (non-fatal, Mobile API data still available): %s",
                        web_err
                    )
            
            return data
            
        except Exception as err:
            _LOGGER.error("Eroare la actualizarea datelor iHidro: %s", err)
            raise UpdateFailed(f"Eroare la actualizarea datelor: {err}") from err

    def _fetch_mobile_data(self) -> Dict[str, Any]:
        """
        Fetch sincron al datelor de la Mobile API (rulează în executor).
        
        Returns:
            Dict structurat cu toate datele pentru toate POD-urile
        """
        _LOGGER.debug("=== iHidro Coordinator: Începem actualizarea datelor (Mobile API) ===")
        
        # Autentificare Mobile API (dacă e necesar)
        self.api.login_if_needed()
        
        # Obținem lista de POD-uri din Mobile API
        accounts = self.api.get_utility_accounts()
        
        if not accounts:
            _LOGGER.warning("Nu s-au găsit POD-uri pentru utilizatorul curent")
            return {"accounts": []}
        
        _LOGGER.debug("Actualizăm date pentru %d POD-uri", len(accounts))
        
        # Structura de date pe care o vom returna
        data = {
            "accounts": [],
            "user_info": self.api.get_validate_user_login_data(),
            "last_update": datetime.now().isoformat(),
        }
        
        # Pentru fiecare POD, obținem datele din Mobile API
        for account in accounts:
            uan = account["UtilityAccountNumber"]
            an = account["AccountNumber"]
            
            _LOGGER.debug("Actualizăm date pentru POD %s (AN: %s)", uan, an)
            
            account_data = {
                "account_info": account,
                "current_bill": None,
                "bill_history": None,
                "payment_history": None,
                "usage_history": None,
                "meter_details": None,
                "meter_window": None,
            }
            
            # Factură curentă (Mobile API)
            try:
                account_data["current_bill"] = self.api.get_current_bill(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea facturii curente pentru %s: %s", uan, err)
            
            # Istoric facturi (Mobile API - ultimele 12 luni)
            try:
                to_date = datetime.now()
                from_date = to_date.replace(year=to_date.year - 1)
                account_data["bill_history"] = self.api.get_bill_history(
                    uan, an,
                    from_date.strftime("%m/%d/%Y"),
                    to_date.strftime("%m/%d/%Y")
                )
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea istoricului facturilor pentru %s: %s", uan, err)
            
            # Istoric consum (Mobile API)
            try:
                account_data["usage_history"] = self.api.get_usage_generation(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea istoricului de consum pentru %s: %s", uan, err)
            
            # Detalii contor (Mobile API)
            try:
                account_data["meter_details"] = self.api.get_multi_meter_details(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea detaliilor contorului pentru %s: %s", uan, err)
            
            # Fereastră de citire index (Mobile API)
            try:
                account_data["meter_window"] = self.api.get_window_dates_enc(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea ferestrei de citire pentru %s: %s", uan, err)
            
            data["accounts"].append(account_data)
        
        _LOGGER.debug("=== iHidro Coordinator: Actualizare Mobile API finalizată ===")
        return data
