"""Platformă Number pentru integrarea iHidro.

Oferă un NumberEntity nativ per POD pentru introducerea valorii indexului
de transmis la Hidroelectrica. Înlocuiește necesitatea de a crea manual
un input_number helper.

Avantaje:
- Se creează automat la configurarea integrării
- Grupat sub device-ul POD
- Valoare implicită: ultimul index citit din coordinator data
- Min/max/step configurate automat
"""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTRIBUTION,
    ATTR_UTILITY_ACCOUNT_NUMBER,
    ATTR_ACCOUNT_NUMBER,
)
from .coordinator import IhidroAccountCoordinator
from .helpers import safe_get_table, safe_float

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurare entități Number din config entry."""
    from . import IhidroRuntimeData

    runtime_data: IhidroRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinators = runtime_data.coordinators

    entities: List[NumberEntity] = []
    for uan, coordinator in coordinators.items():
        entities.append(IhidroMeterReadingNumber(coordinator, entry))

    async_add_entities(entities)
    _LOGGER.info("Au fost create %d entități Number iHidro", len(entities))


class IhidroMeterReadingNumber(CoordinatorEntity, NumberEntity):
    """Entitate Number pentru introducerea indexului contorului.

    Utilizatorul introduce valoarea indexului aici, iar butonul
    IhidroSubmitReadingButton o citește și o trimite la API.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 999999
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self,
        coordinator: IhidroAccountCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Inițializare Number entity."""
        super().__init__(coordinator)
        self.entry = entry
        self._uan = coordinator.uan
        self._an = coordinator.an
        self._attr_name = f"Index Transmitere {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_meter_reading_input"

        # Valoarea stocată intern
        self._value: Optional[float] = None

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

    @property
    def native_value(self) -> Optional[float]:
        """Returnează valoarea curentă.

        Dacă nu a fost setată manual, returnează ultimul index citit
        ca punct de pornire.
        """
        if self._value is not None:
            return self._value

        # Valoare implicită: ultimul index din coordinator
        if self.coordinator.data:
            meter_table = safe_get_table(
                self.coordinator.data.get("meter_details")
            )
            if meter_table:
                return safe_float(meter_table[0].get("MeterReading"))
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Setează valoarea indexului de transmis."""
        self._value = value
        _LOGGER.debug(
            "Index transmitere setat la %.1f kWh pentru POD %s",
            value,
            self._uan,
        )

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale."""
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        if self.coordinator.data:
            meter_table = safe_get_table(
                self.coordinator.data.get("meter_details")
            )
            if meter_table:
                attrs["last_known_reading"] = meter_table[0].get("MeterReading")
                attrs["meter_number"] = meter_table[0].get("MeterNumber")

        return attrs
