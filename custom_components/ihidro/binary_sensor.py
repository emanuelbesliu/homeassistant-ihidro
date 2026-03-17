"""Senzori binari pentru integrarea iHidro.

Convertește senzorii Da/Nu din sensor.py în proper BinarySensorEntity:
- Sold Factură — factură plătită (on = plătit, off = neplătit)
- Factură Restantă — factură restantă (on = restant, off = nu)
- Citire Permisă — fereastra de autocitire deschisă (on = deschis, off = închis)

Avantaje față de senzori string:
- Iconiță on/off nativă în HA
- Compatibilitate cu automatizări condition: state is on/off
- Integrare cu HA history și logbook
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTRIBUTION,
    ATTR_UTILITY_ACCOUNT_NUMBER,
    ATTR_AMOUNT,
    ATTR_DUE_DATE,
)
from .coordinator import IhidroAccountCoordinator
from .helpers import (
    safe_float,
    format_date_ro,
    format_ron,
    is_reading_window_open,
    parse_date,
    get_current_bill_data,
    get_meter_window_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurare senzori binari din config entry."""
    from . import IhidroRuntimeData

    runtime_data: IhidroRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinators = runtime_data.coordinators

    entities: List[BinarySensorEntity] = []

    for uan, coordinator in coordinators.items():
        entities.extend(
            [
                IhidroSoldFacturaBinarySensor(coordinator, entry),
                IhidroFacturaRestantaBinarySensor(coordinator, entry),
                IhidroCitirePermisaBinarySensor(coordinator, entry),
            ]
        )

    async_add_entities(entities)
    _LOGGER.info("Au fost creați %d senzori binari iHidro", len(entities))


# =============================================================================
# Senzor binar de bază
# =============================================================================


class IhidroBaseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Senzor binar de bază pentru iHidro."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IhidroAccountCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Inițializare senzor binar de bază."""
        super().__init__(coordinator)
        self.entry = entry
        self._uan = coordinator.uan
        self._an = coordinator.an

    @property
    def _data(self) -> Dict[str, Any]:
        """Shortcut la datele coordinatorului."""
        return self.coordinator.data or {}

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informații despre device (grupare cu senzorii per POD)."""
        return {
            "identifiers": {(DOMAIN, f"{self.entry.entry_id}_{self._uan}")},
            "name": f"iHidro POD {self._uan}",
            "manufacturer": "Hidroelectrica România",
            "model": "Punct de Consum Electric",
            "entry_type": DeviceEntryType.SERVICE,
        }


# =============================================================================
# Sold Factură (plătit / neplătit)
# =============================================================================


class IhidroSoldFacturaBinarySensor(IhidroBaseBinarySensor):
    """Senzor binar: Factură plătită (on = plătit, off = neplătit/credit).

    on (is_on=True): Sold = 0 sau negativ (plătit/credit)
    off (is_on=False): Sold > 0 (neplătit)
    """

    _attr_icon = "mdi:check-decagram"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Sold Factură"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_sold_factura"

    @property
    def is_on(self) -> Optional[bool]:
        """True = factură plătită (sold ≤ 0), False = neplătit (sold > 0)."""
        bill = get_current_bill_data(self._data.get("current_bill"))
        if not bill:
            return None
        amount = safe_float(bill.get("rembalance") or bill.get("billamount"))
        return amount <= 0

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        bill = get_current_bill_data(self._data.get("current_bill"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
        }
        if bill:
            raw_amount = bill.get("rembalance") or bill.get("billamount")
            amount = safe_float(raw_amount)
            attrs[ATTR_AMOUNT] = raw_amount
            attrs["amount_formatat"] = format_ron(amount)
            if amount < 0:
                attrs["status_detaliat"] = "Credit"
            elif amount == 0:
                attrs["status_detaliat"] = "Plătit"
            else:
                attrs["status_detaliat"] = "Neplătit"
        return attrs


# =============================================================================
# Factură Restantă (overdue)
# =============================================================================


class IhidroFacturaRestantaBinarySensor(IhidroBaseBinarySensor):
    """Senzor binar: Factură restantă (on = restant, off = ok).

    on (is_on=True): Sold > 0 ȘI data scadenței a trecut
    off (is_on=False): Sold ≤ 0 SAU data scadenței nu a trecut
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Factură Restantă"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_factura_restanta"

    @property
    def is_on(self) -> Optional[bool]:
        """True = factură restantă, False = ok."""
        bill = get_current_bill_data(self._data.get("current_bill"))
        if not bill:
            return None

        amount = safe_float(bill.get("rembalance") or bill.get("billamount"))
        if amount <= 0:
            return False

        due_date_str = bill.get("duedate")
        if not due_date_str:
            return False

        due_dt = parse_date(due_date_str)
        if due_dt and datetime.now() > due_dt:
            return True
        return False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        bill = get_current_bill_data(self._data.get("current_bill"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
        }
        if bill:
            raw_amount = bill.get("rembalance") or bill.get("billamount")
            amount = safe_float(raw_amount)
            attrs[ATTR_AMOUNT] = raw_amount
            attrs["amount_formatat"] = format_ron(amount)
            attrs[ATTR_DUE_DATE] = format_date_ro(bill.get("duedate"))

            # Zile restante
            due_dt = parse_date(bill.get("duedate"))
            if due_dt and amount > 0:
                delta = datetime.now() - due_dt
                if delta.days > 0:
                    attrs["zile_restante"] = delta.days
        return attrs


# =============================================================================
# Citire Permisă (fereastra de autocitire)
# =============================================================================


class IhidroCitirePermisaBinarySensor(IhidroBaseBinarySensor):
    """Senzor binar: Fereastra de autocitire (on = deschisă, off = închisă).

    on (is_on=True): Fereastra de autocitire este deschisă
    off (is_on=False): Fereastra de autocitire este închisă
    """

    _attr_device_class = BinarySensorDeviceClass.LOCK
    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Citire Permisă"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_citire_permisa"

    @property
    def is_on(self) -> Optional[bool]:
        """True = fereastra de autocitire este deschisă."""
        window_data = self._data.get("meter_window")
        if not window_data:
            return None
        return is_reading_window_open(window_data)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        window_data = self._data.get("meter_window")
        window = get_meter_window_info(window_data)
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
        }
        if window:
            attrs["window_start"] = format_date_ro(
                window.get("NextMonthOpeningDate") or window.get("OpeningDate")
            )
            attrs["window_end"] = format_date_ro(
                window.get("NextMonthClosingDate") or window.get("ClosingDate")
            )
        return attrs
