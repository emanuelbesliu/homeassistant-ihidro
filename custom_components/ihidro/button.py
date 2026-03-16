"""Platformă Button pentru integrarea iHidro.

Oferă un buton nativ în HA pentru trimiterea autoctirii (self meter read).
Butonul citește valoarea din entitatea Number aferentă POD-ului
(number.ihidro_index_transmitere_{uan}) și o trimite la API.

Înainte de trimitere, se apelează GetMeterValue pentru pre-validare
(Phase G) — API-ul verifică dacă valoarea este plauzibilă.
"""

import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.button import ButtonEntity
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
from .helpers import safe_get_table, is_reading_window_open

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurare butoane din config entry."""
    from . import IhidroRuntimeData

    runtime_data: IhidroRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinators = runtime_data.coordinators

    entities: List[ButtonEntity] = []
    for uan, coordinator in coordinators.items():
        entities.append(IhidroSubmitReadingButton(coordinator, entry))

    async_add_entities(entities)
    _LOGGER.info("Au fost create %d butoane iHidro", len(entities))


class IhidroSubmitReadingButton(CoordinatorEntity, ButtonEntity):
    """Buton pentru trimiterea autoctirii la Hidroelectrica.

    Citește valoarea din entitatea Number aferentă (number platform),
    apelează GetMeterValue pentru pre-validare, apoi SubmitSelfMeterRead.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:send"

    def __init__(
        self,
        coordinator: IhidroAccountCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Inițializare buton."""
        super().__init__(coordinator)
        self.entry = entry
        self._uan = coordinator.uan
        self._an = coordinator.an
        self._attr_name = f"Trimite Index {self._uan}"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_submit_reading"

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
    def available(self) -> bool:
        """Butonul este disponibil doar când fereastra de citire este deschisă."""
        if not self.coordinator.data:
            return False
        window_data = self.coordinator.data.get("meter_window")
        return is_reading_window_open(window_data)

    def _get_number_entity_id(self) -> str:
        """Construiește entity_id-ul entității Number aferente acestui POD."""
        # NumberEntity are unique_id: {entry_id}_{uan}_meter_reading_input
        # HA generează entity_id din name: "Index Transmitere {uan}"
        # Format: number.ihidro_index_transmitere_{uan}
        # Dar ca să fim siguri, căutăm prin entity registry
        return f"number.ihidro_index_transmitere_{self._uan.lower()}"

    def _get_meter_reading_value(self) -> Optional[float]:
        """Citește valoarea indexului din entitatea Number aferentă.

        Caută mai întâi prin entity registry (sigur), apoi prin
        entity_id generat (fallback). Dacă Number entity nu are valoare
        setată, returnează None.
        """
        # Metoda 1: Căutăm prin entity registry folosind unique_id
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        number_unique_id = f"{self.entry.entry_id}_{self._uan}_meter_reading_input"
        number_entry = registry.async_get_entity_id(
            "number", DOMAIN, number_unique_id
        )

        entity_id = number_entry if number_entry else self._get_number_entity_id()

        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "None"):
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_meter_number(self) -> Optional[str]:
        """Obține numărul contorului din datele coordinator-ului."""
        if not self.coordinator.data:
            return None
        meter_table = safe_get_table(
            self.coordinator.data.get("meter_details")
        )
        if meter_table:
            return meter_table[0].get("MeterNumber")
        return None

    async def async_press(self) -> None:
        """Apăsare buton — trimite autocitirea.

        Flux:
        1. Citește valoarea din entitatea Number aferentă
        2. Obține numărul contorului din coordinator
        3. Apelează GetMeterValue pentru pre-validare
        4. Dacă validarea trece, apelează SubmitSelfMeterRead
        5. Forțează refresh după trimitere
        """
        # 1. Citim valoarea din Number entity
        meter_reading = self._get_meter_reading_value()
        if meter_reading is None:
            _LOGGER.error(
                "Nu s-a putut citi valoarea indexului pentru POD %s. "
                "Setați valoarea în entitatea Number (Index Transmitere %s) "
                "înainte de a apăsa butonul.",
                self._uan,
                self._uan,
            )
            return

        # 2. Obținem numărul contorului
        meter_number = self._get_meter_number()
        if not meter_number:
            _LOGGER.error(
                "Nu s-a putut determina numărul contorului pentru POD %s",
                self._uan,
            )
            return

        # Obținem API-ul din runtime data
        from . import IhidroRuntimeData

        runtime_data: IhidroRuntimeData = self.hass.data[DOMAIN][self.entry.entry_id]
        api = runtime_data.api

        # 3. Pre-validare cu GetMeterValue (Phase G)
        _LOGGER.info(
            "Pre-validare index %.1f pentru contorul %s (UAN: %s)",
            meter_reading,
            meter_number,
            self._uan,
        )

        try:
            validation_result = await api.get_meter_value(
                utility_account_number=self._uan,
                account_number=self._an,
                meter_number=meter_number,
                meter_reading=meter_reading,
            )

            # Verificăm răspunsul de validare
            # API-ul returnează erori dacă valoarea este nerealistă
            # (prea mare, prea mică, index mai mic decât precedentul)
            validation_table = safe_get_table(validation_result)
            if validation_table:
                status = validation_table[0].get("Status", "")
                message = validation_table[0].get("Message", "")
                if status and str(status).upper() in ("ERROR", "FAIL", "FAILED"):
                    _LOGGER.error(
                        "Pre-validare eșuată pentru POD %s: %s",
                        self._uan,
                        message or status,
                    )
                    return
                _LOGGER.debug(
                    "Pre-validare OK pentru POD %s: Status=%s, Mesaj=%s",
                    self._uan,
                    status,
                    message,
                )
            else:
                # Dacă nu primim Table dar nici eroare, continuăm
                # (unele conturi pot să nu returneze date în GetMeterValue)
                _LOGGER.debug(
                    "GetMeterValue nu a returnat date tabelare pentru POD %s, "
                    "continuăm cu trimiterea",
                    self._uan,
                )

        except Exception as err:
            _LOGGER.warning(
                "Eroare la pre-validare (GetMeterValue) pentru POD %s: %s. "
                "Continuăm cu trimiterea.",
                self._uan,
                err,
            )
            # Nu blocăm trimiterea dacă pre-validarea eșuează cu excepție
            # (endpoint poate fi indisponibil temporar)

        # 4. Trimitem autocitirea cu SubmitSelfMeterRead
        _LOGGER.info(
            "Trimitem index %.1f pentru contorul %s (UAN: %s)",
            meter_reading,
            meter_number,
            self._uan,
        )

        # Obținem datele anterioare pentru metadata completă
        previous_data = None
        if self.coordinator.data:
            previous_data = self.coordinator.data.get("previous_meter_read")

        try:
            result = await api.submit_self_meter_read(
                utility_account_number=self._uan,
                account_number=self._an,
                meter_number=meter_number,
                meter_reading=meter_reading,
                previous_meter_read_data=previous_data,
            )

            if result.get("success"):
                _LOGGER.info(
                    "Index trimis cu succes pentru POD %s: %s",
                    self._uan,
                    result.get("message"),
                )
                # 5. Forțăm refresh după trimitere
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error(
                    "Eroare la trimiterea indexului pentru POD %s: %s",
                    self._uan,
                    result.get("message"),
                )
        except Exception as err:
            _LOGGER.error(
                "Excepție la trimiterea indexului pentru POD %s: %s",
                self._uan,
                err,
            )

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale."""
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        if self.coordinator.data:
            # Info fereastră citire
            window_data = self.coordinator.data.get("meter_window")
            window_table = safe_get_table(window_data)
            if window_table:
                window = window_table[0]
                attrs["window_open"] = is_reading_window_open(window_data)
                attrs["window_start"] = window.get("WindowStartDate") or window.get(
                    "StartDate"
                )
                attrs["window_end"] = window.get("WindowEndDate") or window.get(
                    "EndDate"
                )

            # Numărul contorului
            meter_table = safe_get_table(
                self.coordinator.data.get("meter_details")
            )
            if meter_table:
                attrs["meter_number"] = meter_table[0].get("MeterNumber")

            # Valoarea curentă din Number entity (pt. vizibilitate)
            current_reading = self._get_meter_reading_value()
            if current_reading is not None:
                attrs["pending_reading"] = current_reading

        return attrs
