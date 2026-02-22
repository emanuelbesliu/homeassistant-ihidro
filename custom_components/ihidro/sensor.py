"""Senzori pentru integrarea iHidro."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTRIBUTION,
    ATTR_ACCOUNT_NUMBER,
    ATTR_UTILITY_ACCOUNT_NUMBER,
    ATTR_ADDRESS,
    ATTR_METER_NUMBER,
    ATTR_LAST_READING,
    ATTR_LAST_READING_DATE,
    ATTR_CONSUMPTION,
    ATTR_AMOUNT,
    ATTR_DUE_DATE,
    ATTR_STATUS,
)
from .coordinator import IhidroDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurare senzori din config entry."""
    coordinator: IhidroDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Obținem lista de POD-uri din datele coordinator-ului
    accounts = coordinator.data.get("accounts", [])
    
    if not accounts:
        _LOGGER.warning("Nu s-au găsit POD-uri pentru a crea senzori")
        return

    entities = []

    # Pentru fiecare POD, creăm un set complet de senzori
    for idx, account_data in enumerate(accounts):
        account_info = account_data.get("account_info", {})
        uan = account_info.get("UtilityAccountNumber")
        an = account_info.get("AccountNumber")

        if not uan or not an:
            _LOGGER.warning("POD %d lipsește UAN sau AN, sărim peste", idx)
            continue

        # Creăm senzorii pentru acest POD
        entities.extend([
            # Senzor pentru sold curent (factură curentă)
            IhidroCurrentBalanceSensor(coordinator, entry, idx),
            
            # Senzor pentru ultima factură
            IhidroLastBillSensor(coordinator, entry, idx),
            
            # Senzor pentru index curent contor
            IhidroMeterReadingSensor(coordinator, entry, idx),
            
            # Senzor pentru consum lunar
            IhidroMonthlyConsumptionSensor(coordinator, entry, idx),
            
            # Senzor pentru ultima plată
            IhidroLastPaymentSensor(coordinator, entry, idx),
            
            # Senzor pentru informații POD
            IhidroPODInfoSensor(coordinator, entry, idx),
        ])

    async_add_entities(entities)
    _LOGGER.info("Au fost creați %d senzori iHidro", len(entities))


class IhidroBaseSensor(CoordinatorEntity, SensorEntity):
    """Senzor de bază pentru iHidro."""

    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: IhidroDataUpdateCoordinator,
        entry: ConfigEntry,
        account_idx: int,
    ) -> None:
        """Inițializare senzor de bază."""
        super().__init__(coordinator)
        self.entry = entry
        self.account_idx = account_idx

        # Informații despre POD
        account_info = self._get_account_info()
        self._uan = account_info.get("UtilityAccountNumber", "")
        self._an = account_info.get("AccountNumber", "")
        self._address = account_info.get("Address", "")

    def _get_account_info(self) -> Dict[str, Any]:
        """Obține informațiile despre POD din datele coordinator-ului."""
        accounts = self.coordinator.data.get("accounts", [])
        if self.account_idx < len(accounts):
            return accounts[self.account_idx].get("account_info", {})
        return {}

    def _get_account_data(self) -> Dict[str, Any]:
        """Obține toate datele pentru acest POD."""
        accounts = self.coordinator.data.get("accounts", [])
        if self.account_idx < len(accounts):
            return accounts[self.account_idx]
        return {}

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informații despre device (grupare senzori per POD)."""
        return {
            "identifiers": {(DOMAIN, f"{self.entry.entry_id}_{self._uan}")},
            "name": f"iHidro POD {self._uan}",
            "manufacturer": "Hidroelectrica România",
            "model": "Punct de Consum Electric",
            "entry_type": "service",
        }


class IhidroCurrentBalanceSensor(IhidroBaseSensor):
    """Senzor pentru sold curent (factură curentă)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_icon = "mdi:cash"

    def __init__(
        self,
        coordinator: IhidroDataUpdateCoordinator,
        entry: ConfigEntry,
        account_idx: int,
    ) -> None:
        """Inițializare senzor sold curent."""
        super().__init__(coordinator, entry, account_idx)
        self._attr_name = f"iHidro Sold Curent {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_current_balance"

    @property
    def native_value(self) -> Optional[float]:
        """Returnează soldul curent."""
        account_data = self._get_account_data()
        current_bill = account_data.get("current_bill")
        
        if not current_bill:
            return None
        
        try:
            # Extragem suma din structura API
            data = current_bill.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                amount_str = table[0].get("Amount", "0")
                # Curățăm string-ul (eliminăm simboluri și convertem în float)
                amount_str = amount_str.replace("RON", "").replace(",", "").strip()
                return float(amount_str)
        except (ValueError, TypeError, KeyError) as err:
            _LOGGER.debug("Eroare la parsarea soldului curent: %s", err)
        
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale."""
        account_data = self._get_account_data()
        current_bill = account_data.get("current_bill")
        
        attrs = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
            ATTR_ADDRESS: self._address,
        }
        
        if current_bill:
            data = current_bill.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                bill_info = table[0]
                attrs[ATTR_DUE_DATE] = bill_info.get("DueDate")
                attrs["bill_number"] = bill_info.get("BillNumber")
                attrs["bill_date"] = bill_info.get("BillDate")
                attrs[ATTR_STATUS] = bill_info.get("Status")
        
        return attrs


class IhidroLastBillSensor(IhidroBaseSensor):
    """Senzor pentru ultima factură."""

    _attr_icon = "mdi:file-document"

    def __init__(
        self,
        coordinator: IhidroDataUpdateCoordinator,
        entry: ConfigEntry,
        account_idx: int,
    ) -> None:
        """Inițializare senzor ultima factură."""
        super().__init__(coordinator, entry, account_idx)
        self._attr_name = f"iHidro Ultima Factură {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_last_bill"

    @property
    def native_value(self) -> Optional[str]:
        """Returnează numărul ultimei facturi."""
        account_data = self._get_account_data()
        bill_history = account_data.get("bill_history")
        
        if not bill_history:
            return None
        
        try:
            data = bill_history.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                return table[0].get("BillNumber")
        except (TypeError, KeyError) as err:
            _LOGGER.debug("Eroare la parsarea ultimei facturi: %s", err)
        
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale."""
        account_data = self._get_account_data()
        bill_history = account_data.get("bill_history")
        
        attrs = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }
        
        if bill_history:
            data = bill_history.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                last_bill = table[0]
                attrs["bill_date"] = last_bill.get("BillDate")
                attrs[ATTR_AMOUNT] = last_bill.get("Amount")
                attrs[ATTR_CONSUMPTION] = last_bill.get("Consumption")
                attrs[ATTR_DUE_DATE] = last_bill.get("DueDate")
                attrs[ATTR_STATUS] = last_bill.get("Status")
        
        return attrs


class IhidroMeterReadingSensor(IhidroBaseSensor):
    """Senzor pentru index curent contor."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:counter"

    def __init__(
        self,
        coordinator: IhidroDataUpdateCoordinator,
        entry: ConfigEntry,
        account_idx: int,
    ) -> None:
        """Inițializare senzor index contor."""
        super().__init__(coordinator, entry, account_idx)
        self._attr_name = f"iHidro Index Contor {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_meter_reading"

    @property
    def native_value(self) -> Optional[float]:
        """Returnează indexul curent al contorului."""
        account_data = self._get_account_data()
        meter_details = account_data.get("meter_details")
        
        if not meter_details:
            return None
        
        try:
            data = meter_details.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                reading_str = table[0].get("MeterReading", "0")
                return float(reading_str)
        except (ValueError, TypeError, KeyError) as err:
            _LOGGER.debug("Eroare la parsarea indexului contor: %s", err)
        
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale."""
        account_data = self._get_account_data()
        meter_details = account_data.get("meter_details")
        meter_window = account_data.get("meter_window")
        
        attrs = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }
        
        if meter_details:
            data = meter_details.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                meter_info = table[0]
                attrs[ATTR_METER_NUMBER] = meter_info.get("MeterNumber")
                attrs[ATTR_LAST_READING] = meter_info.get("MeterReading")
                attrs[ATTR_LAST_READING_DATE] = meter_info.get("ReadingDate")
        
        if meter_window:
            data = meter_window.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                window_info = table[0]
                attrs["reading_window_start"] = window_info.get("WindowStartDate")
                attrs["reading_window_end"] = window_info.get("WindowEndDate")
        
        return attrs


class IhidroMonthlyConsumptionSensor(IhidroBaseSensor):
    """Senzor pentru consum lunar."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: IhidroDataUpdateCoordinator,
        entry: ConfigEntry,
        account_idx: int,
    ) -> None:
        """Inițializare senzor consum lunar."""
        super().__init__(coordinator, entry, account_idx)
        self._attr_name = f"iHidro Consum Lunar {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_monthly_consumption"

    @property
    def native_value(self) -> Optional[float]:
        """Returnează consumul lunar."""
        account_data = self._get_account_data()
        usage_history = account_data.get("usage_history")
        
        if not usage_history:
            return None
        
        try:
            data = usage_history.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                # Luăm consumul din prima înregistrare (cea mai recentă)
                consumption_str = table[0].get("Consumption", "0")
                return float(consumption_str)
        except (ValueError, TypeError, KeyError) as err:
            _LOGGER.debug("Eroare la parsarea consumului lunar: %s", err)
        
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale cu istoric."""
        account_data = self._get_account_data()
        usage_history = account_data.get("usage_history")
        
        attrs = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }
        
        if usage_history:
            data = usage_history.get("result", {}).get("Data", {})
            table = data.get("Table", [])
            if table:
                # Adăugăm istoricul ultimelor 6 luni
                history = []
                for entry in table[:6]:
                    history.append({
                        "month": entry.get("Month"),
                        "year": entry.get("Year"),
                        "consumption": entry.get("Consumption"),
                        "cost": entry.get("Cost"),
                    })
                attrs["history"] = history
        
        return attrs


class IhidroLastPaymentSensor(IhidroBaseSensor):
    """Senzor pentru ultima plată."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_icon = "mdi:cash-check"

    def __init__(
        self,
        coordinator: IhidroDataUpdateCoordinator,
        entry: ConfigEntry,
        account_idx: int,
    ) -> None:
        """Inițializare senzor ultima plată."""
        super().__init__(coordinator, entry, account_idx)
        self._attr_name = f"iHidro Ultima Plată {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_last_payment"

    @property
    def native_value(self) -> Optional[float]:
        """Returnează suma ultimei plăți."""
        account_data = self._get_account_data()
        bill_history = account_data.get("bill_history")
        
        if not bill_history:
            return None
        
        try:
            # Plățile sunt în objBillingPaymentHistoryEntity din billing history
            result = bill_history.get("result", {})
            payments = result.get("objBillingPaymentHistoryEntity", [])
            if payments:
                # Plățile sunt sortate descrescător după dată, prima e cea mai recentă
                last_payment = payments[0]
                amount_str = last_payment.get("amount", "0")
                # Curățăm string-ul (poate conține "RON", virgule, etc.)
                amount_str = str(amount_str).replace("RON", "").replace(",", "").strip()
                return float(amount_str)
        except (ValueError, TypeError, KeyError) as err:
            _LOGGER.debug("Eroare la parsarea ultimei plăți: %s", err)
        
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale."""
        account_data = self._get_account_data()
        bill_history = account_data.get("bill_history")
        
        attrs = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }
        
        if bill_history:
            result = bill_history.get("result", {})
            payments = result.get("objBillingPaymentHistoryEntity", [])
            if payments:
                last_payment = payments[0]
                attrs["payment_date"] = last_payment.get("paymentDate")
                attrs["bill_month"] = last_payment.get("billMonth")
                attrs["bill_year"] = last_payment.get("billYear")
        
        return attrs


class IhidroPODInfoSensor(IhidroBaseSensor):
    """Senzor pentru informații generale despre POD."""

    _attr_icon = "mdi:information"

    def __init__(
        self,
        coordinator: IhidroDataUpdateCoordinator,
        entry: ConfigEntry,
        account_idx: int,
    ) -> None:
        """Inițializare senzor informații POD."""
        super().__init__(coordinator, entry, account_idx)
        self._attr_name = f"iHidro POD Info {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_pod_info"

    @property
    def native_value(self) -> str:
        """Returnează adresa POD-ului."""
        return self._address or "Adresă necunoscută"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale cu toate informațiile despre POD."""
        account_info = self._get_account_info()
        
        return {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
            ATTR_ADDRESS: self._address,
            "customer_name": account_info.get("CustomerName"),
            "is_default": account_info.get("IsDefaultAccount"),
        }
