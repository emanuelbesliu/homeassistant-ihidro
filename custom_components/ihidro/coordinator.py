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
    DEFAULT_UPDATE_INTERVAL,
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
        
        self.web_api = IhidroWebPortalAPI(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
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
            # Rulăm operațiile în executor pentru a nu bloca loop-ul async
            return await self.hass.async_add_executor_job(self._fetch_data)
        except Exception as err:
            _LOGGER.error("Eroare la actualizarea datelor iHidro: %s", err)
            raise UpdateFailed(f"Eroare la actualizarea datelor: {err}") from err

    def _fetch_data(self) -> Dict[str, Any]:
        """
        Fetch sincron al datelor de la API (rulează în executor).
        
        Folosește DUAL API:
        - Mobile API: pentru facturi, balanță, plăți (OBLIGATORIU)
        - Web Portal API: pentru index contor și istoric (OPȚIONAL - poate eșua)
        
        Returns:
            Dict structurat cu toate datele pentru toate POD-urile
        """
        _LOGGER.debug("=== iHidro Coordinator: Începem actualizarea datelor (Dual API) ===")
        
        # Autentificare Mobile API (dacă e necesar) - OBLIGATORIU
        self.api.login_if_needed()
        
        # Obținem lista de POD-uri din Mobile API
        accounts = self.api.get_utility_accounts()
        
        if not accounts:
            _LOGGER.warning("Nu s-au găsit POD-uri pentru utilizatorul curent")
            return {"accounts": []}
        
        # Autentificare Web Portal API (OPȚIONAL - continuăm dacă eșuează)
        web_pods_dict = {}
        web_portal_available = False
        try:
            self.web_api.login_if_needed()
            web_pods = self.web_api.get_all_pods()
            web_pods_dict = {pod["pod"]: pod for pod in web_pods}  # Index by POD number
            web_portal_available = True
            _LOGGER.info("Web Portal API: Autentificare reușită, date disponibile")
        except Exception as err:
            _LOGGER.warning(
                "Web Portal API: Autentificare eșuată (contoare clasice vor afișa doar date Mobile API). "
                "Eroare: %s", err
            )
            _LOGGER.info(
                "Web Portal este blocat de reCAPTCHA și nu poate fi accesat automat. "
                "Integrarea va funcționa doar cu Mobile API (facturi, balanță, plăți). "
                "Senzorul de index contor va folosi date Mobile API (dacă există contor smart)."
            )
        
        _LOGGER.debug("Actualizăm date pentru %d POD-uri", len(accounts))
        
        # Structura de date pe care o vom returna
        data = {
            "accounts": [],
            "user_info": self.api.get_validate_user_login_data(),
            "last_update": datetime.now().isoformat(),
        }
        
        # Pentru fiecare POD, obținem toate datele
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
                "web_pod_info": None,  # NEW: Date din Web Portal
                "meter_reading": None,  # NEW: Index curent din Web Portal
                "meter_history": None,  # NEW: Istoric index din Web Portal
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
            
            # Detalii contor (Mobile API - pentru compatibilitate)
            try:
                account_data["meter_details"] = self.api.get_multi_meter_details(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea detaliilor contorului pentru %s: %s", uan, err)
            
            # Fereastră de citire index (Mobile API)
            try:
                account_data["meter_window"] = self.api.get_window_dates_enc(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea ferestrei de citire pentru %s: %s", uan, err)
            
            # === WEB PORTAL API DATA (OPȚIONAL) ===
            # Încercăm să obținem date din Web Portal doar dacă autentificarea a reușit
            if web_portal_available:
                # Găsim POD-ul corespunzător în datele Web Portal
                # Căutăm după UtilityAccountNumber sau Customer Name
                web_pod = None
                for pod_num, pod_data in web_pods_dict.items():
                    # Match by contract account ID if available
                    if pod_data.get("contractAccountID") == uan:
                        web_pod = pod_data
                        break
                
                if web_pod:
                    account_data["web_pod_info"] = web_pod
                    
                    # Index contor curent și istoric (Web Portal API)
                    try:
                        installation = web_pod["installation"]
                        pod_value = web_pod["pod"]
                        
                        # Get full history
                        meter_history = self.web_api.get_index_history(installation, pod_value)
                        account_data["meter_history"] = meter_history
                        
                        # Get latest reading
                        if meter_history:
                            latest = self.web_api.get_latest_meter_reading(installation, pod_value)
                            account_data["meter_reading"] = latest
                            _LOGGER.debug(
                                "Index curent pentru POD %s: %s (%s)",
                                pod_value, latest.get("index"), latest.get("date")
                            )
                    except Exception as err:
                        _LOGGER.warning(
                            "Eroare la obținerea indexului din Web Portal pentru %s: %s", 
                            uan, err
                        )
                else:
                    _LOGGER.debug(
                        "Nu am găsit POD-ul %s în datele Web Portal.", uan
                    )
            else:
                _LOGGER.debug(
                    "Web Portal API indisponibil - folosim doar date Mobile API pentru POD %s", uan
                )
            
            data["accounts"].append(account_data)
        
        _LOGGER.debug("=== iHidro Coordinator: Actualizare finalizată cu succes (Dual API) ===")
        return data
