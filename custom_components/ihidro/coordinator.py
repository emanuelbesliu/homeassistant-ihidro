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
        
        # Inițializăm API-ul
        self.api = IhidroAPI(
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
        
        Returns:
            Dict structurat cu toate datele pentru toate POD-urile
        """
        _LOGGER.debug("=== iHidro Coordinator: Începem actualizarea datelor ===")
        
        # Autentificare (dacă e necesar)
        self.api.login_if_needed()
        
        # Obținem lista de POD-uri
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
            }
            
            # Factură curentă
            try:
                account_data["current_bill"] = self.api.get_current_bill(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea facturii curente pentru %s: %s", uan, err)
            
            # Istoric facturi (ultimele 12 luni)
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
            
            # Istoric consum
            try:
                account_data["usage_history"] = self.api.get_usage_generation(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea istoricului de consum pentru %s: %s", uan, err)
            
            # Detalii contor
            try:
                account_data["meter_details"] = self.api.get_multi_meter_details(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea detaliilor contorului pentru %s: %s", uan, err)
            
            # Fereastră de citire index
            try:
                account_data["meter_window"] = self.api.get_window_dates_enc(uan, an)
            except Exception as err:
                _LOGGER.warning("Eroare la obținerea ferestrei de citire pentru %s: %s", uan, err)
            
            data["accounts"].append(account_data)
        
        _LOGGER.debug("=== iHidro Coordinator: Actualizare finalizată cu succes ===")
        return data
