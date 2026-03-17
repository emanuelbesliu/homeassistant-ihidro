"""Platformă Switch pentru integrarea iHidro.

Oferă un switch de autotransmitere a indexului contorului.
Când este activat și fereastra de autocitire se deschide,
integrarea citește automat senzorul de energie extern,
calculează indexul prin calibrare offset, și îl trimite la API.

Switch-ul și entitatea de delay sunt indisponibile (greyed out)
dacă utilizatorul nu a configurat un senzor de energie extern
în opțiunile integrării.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTRIBUTION,
    CONF_ENERGY_SENSOR,
    ATTR_UTILITY_ACCOUNT_NUMBER,
    ATTR_ACCOUNT_NUMBER,
)
from .coordinator import IhidroAccountCoordinator
from .helpers import safe_float, is_reading_window_open, parse_date, get_meter_index_cascading, get_data_list, get_meter_window_info

_LOGGER = logging.getLogger(__name__)

# Cheia pentru stocarea stării switch-ului în hass.data
_AUTOSUBMIT_STATE_KEY = "ihidro_autosubmit_state"
_AUTOSUBMIT_SUBMITTED_KEY = "ihidro_autosubmit_submitted"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurare switch-uri din config entry."""
    from . import IhidroRuntimeData

    runtime_data: IhidroRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinators = runtime_data.coordinators

    entities: list = []
    for uan, coordinator in coordinators.items():
        entities.append(IhidroAutoSubmitSwitch(coordinator, entry))

    async_add_entities(entities)
    _LOGGER.info("Au fost create %d entități switch iHidro", len(entities))


class IhidroAutoSubmitSwitch(CoordinatorEntity, RestoreEntity, SwitchEntity):
    """Switch pentru autotransmiterea indexului contorului.

    Când este activat:
    1. Monitorizează fereastra de autocitire (din coordinator data)
    2. Când fereastra se deschide + delay-ul configurat a trecut:
       a. Citește senzorul de energie extern
       b. Calculează indexul contor prin offset calibration:
          offset = last_meter_index - energy_sensor_at_calibration
          index_to_submit = current_energy_sensor + offset
       c. Apelează GetMeterValue pentru pre-validare
       d. Trimite indexul cu SubmitSelfMeterRead

    Folosește RestoreEntity pentru a persista starea ON/OFF între restarturile HA.
    Switch-ul este indisponibil (greyed out) dacă:
    - Nu este configurat un senzor de energie extern
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_icon = "mdi:send-clock"

    def __init__(
        self,
        coordinator: IhidroAccountCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Inițializare switch."""
        super().__init__(coordinator)
        self.entry = entry
        self._uan = coordinator.uan
        self._an = coordinator.an
        self._attr_name = "Autotransmitere"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_autosubmit"

        # Stare internă
        self._is_on: bool = False
        # Flag: am trimis deja indexul în această fereastră de citire?
        self._submitted_this_window: bool = False
        # Offset de calibrare (calculat la activare)
        self._calibration_offset: Optional[float] = None
        # Timestamp ultima calibrare
        self._calibration_time: Optional[str] = None

    async def async_added_to_hass(self) -> None:
        """Restaurează starea switch-ului la adăugarea în HA."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"
            if self._is_on:
                _LOGGER.debug(
                    "Autotransmitere restaurată ON pentru POD %s, recalibrăm offset",
                    self._uan,
                )
                # Recalibrăm offset-ul (datele din senzorul extern s-au schimbat)
                await self._calibrate_offset()

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

    def _get_energy_sensor_id(self) -> Optional[str]:
        """Returnează entity_id senzorului de energie extern configurat."""
        energy_sensor = self.entry.options.get(CONF_ENERGY_SENSOR, "")
        return energy_sensor if energy_sensor else None

    @property
    def available(self) -> bool:
        """Switch-ul este disponibil doar dacă există senzor de energie configurat."""
        return self._get_energy_sensor_id() is not None

    @property
    def is_on(self) -> bool:
        """Returnează starea switch-ului."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activează autotransmiterea.

        La activare, calibrăm offset-ul:
        offset = last_meter_index - current_energy_sensor_value
        """
        self._is_on = True
        self._submitted_this_window = False

        # Calibrare offset
        await self._calibrate_offset()

        self.async_write_ha_state()
        _LOGGER.info(
            "Autotransmitere activată pentru POD %s (offset: %s)",
            self._uan,
            self._calibration_offset,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Dezactivează autotransmiterea."""
        self._is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Autotransmitere dezactivată pentru POD %s", self._uan)

    async def _calibrate_offset(self) -> None:
        """Calculează offset-ul de calibrare.

        offset = last_meter_index - current_energy_sensor_value

        Astfel: index_to_submit = energy_sensor_current + offset
        """
        energy_sensor_id = self._get_energy_sensor_id()
        if not energy_sensor_id:
            self._calibration_offset = None
            return

        # Citim valoarea curentă din senzorul de energie
        state_obj = self.hass.states.get(energy_sensor_id)
        if state_obj is None or state_obj.state in ("unavailable", "unknown", None):
            _LOGGER.warning(
                "Nu se poate calibra offset-ul: senzor '%s' indisponibil",
                energy_sensor_id,
            )
            self._calibration_offset = None
            return

        try:
            energy_value = float(state_obj.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Nu se poate calibra offset-ul: senzor '%s' are stare non-numerică '%s'",
                energy_sensor_id,
                state_obj.state,
            )
            self._calibration_offset = None
            return

        # Conversie din Wh în kWh dacă este cazul
        unit = state_obj.attributes.get("unit_of_measurement", "")
        if unit == "Wh":
            energy_value = energy_value / 1000.0

        # Obținem ultimul index cunoscut al contorului
        last_meter_index = self._get_last_meter_index()
        if last_meter_index is None:
            _LOGGER.warning(
                "Nu se poate calibra offset-ul: index contor necunoscut pentru POD %s",
                self._uan,
            )
            self._calibration_offset = None
            return

        self._calibration_offset = round(last_meter_index - energy_value, 3)
        self._calibration_time = datetime.now().isoformat()
        _LOGGER.info(
            "Offset calibrat pentru POD %s: %.3f (meter_index=%.1f, energy_sensor=%.3f)",
            self._uan,
            self._calibration_offset,
            last_meter_index,
            energy_value,
        )

    def _get_last_meter_index(self) -> Optional[float]:
        """Obține ultimul index al contorului din datele coordinator-ului."""
        if not self.coordinator.data:
            return None
        value, _src = get_meter_index_cascading(self.coordinator.data)
        if value is not None and value > 0:
            return float(value)
        return None

    def _get_meter_number(self) -> Optional[str]:
        """Obține numărul contorului din datele coordinator-ului."""
        if not self.coordinator.data:
            return None
        # meter_details este mereu gol; fallback la previous_meter_read sau meter_counter_series
        prev_reads = get_data_list(self.coordinator.data.get("previous_meter_read"))
        if prev_reads:
            sn = prev_reads[0].get("serialNumber")
            if sn:
                return sn
        counter_series = get_data_list(self.coordinator.data.get("meter_counter_series"))
        if counter_series:
            cs = counter_series[0].get("CounterSeries")
            if cs:
                return cs
        return None

    def _get_current_energy_kwh(self) -> Optional[float]:
        """Citește valoarea curentă din senzorul de energie extern (kWh)."""
        entity_id = self._get_energy_sensor_id()
        if not entity_id:
            return None
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None or state_obj.state in ("unavailable", "unknown", None):
            return None
        try:
            value = float(state_obj.state)
        except (ValueError, TypeError):
            return None
        unit = state_obj.attributes.get("unit_of_measurement", "")
        if unit == "Wh":
            value = value / 1000.0
        return value

    def _compute_meter_index(self) -> Optional[float]:
        """Calculează indexul contorului din senzorul extern + offset.

        index_to_submit = energy_sensor_current + calibration_offset
        """
        if self._calibration_offset is None:
            return None
        current_kwh = self._get_current_energy_kwh()
        if current_kwh is None:
            return None
        return round(current_kwh + self._calibration_offset, 1)

    def _get_delay_days(self) -> int:
        """Obține delay-ul configurat (zile) din entitatea number aferentă.

        Caută starea entității number cu unique_id corespunzător.
        Default: 1 zi.
        """
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        delay_unique_id = f"{self.entry.entry_id}_{self._uan}_autosubmit_delay"
        delay_entity_id = registry.async_get_entity_id(
            "number", DOMAIN, delay_unique_id
        )

        if delay_entity_id:
            state = self.hass.states.get(delay_entity_id)
            if state and state.state not in ("unknown", "unavailable", None):
                try:
                    return int(float(state.state))
                except (ValueError, TypeError):
                    pass
        return 1  # Default: 1 zi

    def _get_window_start_date(self) -> Optional[datetime]:
        """Obține data de start a ferestrei de citire."""
        if not self.coordinator.data:
            return None
        window_data = self.coordinator.data.get("meter_window")
        window = get_meter_window_info(window_data)
        if window:
            start_str = window.get("NextMonthOpeningDate") or window.get("OpeningDate")
            if start_str:
                return parse_date(start_str)
        return None

    def _is_reading_window_open(self) -> bool:
        """Verifică dacă fereastra de autocitire este deschisă."""
        if not self.coordinator.data:
            return False
        window_data = self.coordinator.data.get("meter_window")
        return is_reading_window_open(window_data)

    def _should_submit_now(self) -> bool:
        """Verifică dacă trebuie să transmitem acum.

        Condiții:
        1. Switch-ul este ON
        2. Fereastra de citire este deschisă
        3. Nu am transmis deja în această fereastră
        4. Delay-ul configurat a trecut (zile de la deschiderea ferestrei)
        5. Avem offset de calibrare valid
        6. Putem calcula indexul din senzorul extern
        """
        if not self._is_on:
            return False
        if not self._is_reading_window_open():
            # Fereastra s-a închis — resetăm flag-ul pentru următoarea fereastră
            self._submitted_this_window = False
            return False
        if self._submitted_this_window:
            return False
        if self._calibration_offset is None:
            return False

        # Verificăm delay
        delay_days = self._get_delay_days()
        window_start = self._get_window_start_date()
        if window_start is not None:
            days_since_open = (datetime.now() - window_start).days
            if days_since_open < delay_days:
                return False

        # Verificăm că putem calcula indexul
        computed_index = self._compute_meter_index()
        if computed_index is None or computed_index <= 0:
            return False

        return True

    @callback
    def _handle_coordinator_update(self) -> None:
        """Reacționează la actualizările coordinator-ului.

        La fiecare refresh, verificăm dacă trebuie să transmitem automat.
        """
        super()._handle_coordinator_update()

        if self._should_submit_now():
            self.hass.async_create_task(self._auto_submit())

    async def _auto_submit(self) -> None:
        """Transmite automat indexul contorului.

        Flux:
        1. Recalibrează offset-ul (în caz că indexul s-a actualizat)
        2. Calculează indexul din senzorul extern
        3. Pre-validează cu GetMeterValue
        4. Trimite cu SubmitSelfMeterRead
        5. Marchează ca transmis pentru această fereastră
        """
        _LOGGER.info(
            "iHidro Autotransmitere [%s]: Începem trimiterea automată",
            self._uan,
        )

        # Recalibrăm offset-ul (indexul contorului s-ar putea să fi fost
        # actualizat de o factură nouă de la ultima calibrare)
        await self._calibrate_offset()

        # Calculăm indexul
        computed_index = self._compute_meter_index()
        if computed_index is None or computed_index <= 0:
            _LOGGER.warning(
                "Autotransmitere [%s]: Nu se poate calcula indexul — "
                "senzor extern indisponibil sau offset invalid",
                self._uan,
            )
            return

        # Obținem numărul contorului
        meter_number = self._get_meter_number()
        if not meter_number:
            _LOGGER.error(
                "Autotransmitere [%s]: Număr contor necunoscut",
                self._uan,
            )
            return

        # Validare suplimentară: indexul trebuie să fie mai mare decât ultimul cunoscut
        last_index = self._get_last_meter_index()
        if last_index is not None and computed_index < last_index:
            _LOGGER.warning(
                "Autotransmitere [%s]: Index calculat (%.1f) < ultimul index (%.1f). "
                "Posibilă eroare de calibrare. Recalibrăm și amânăm.",
                self._uan,
                computed_index,
                last_index,
            )
            return

        # Obținem API-ul din runtime data
        from . import IhidroRuntimeData

        runtime_data: IhidroRuntimeData = self.hass.data[DOMAIN][self.entry.entry_id]
        api = runtime_data.api

        # Pre-validare cu GetMeterValue
        try:
            _LOGGER.info(
                "Autotransmitere [%s]: Pre-validare index %.1f",
                self._uan,
                computed_index,
            )
            validation_result = await api.get_meter_value(
                utility_account_number=self._uan,
                account_number=self._an,
                meter_number=meter_number,
                meter_reading=computed_index,
            )
            val_result = validation_result.get("result") if isinstance(validation_result, dict) else None
            if isinstance(val_result, dict):
                status = val_result.get("Status", "")
                message = val_result.get("Message", "")
                if status and str(status).upper() in ("ERROR", "FAIL", "FAILED"):
                    _LOGGER.error(
                        "Autotransmitere [%s]: Pre-validare eșuată: %s",
                        self._uan,
                        message or status,
                    )
                    return
        except Exception as err:
            _LOGGER.warning(
                "Autotransmitere [%s]: Eroare la pre-validare: %s. Continuăm.",
                self._uan,
                err,
            )

        # Trimitere index
        try:
            previous_data = None
            if self.coordinator.data:
                previous_data = self.coordinator.data.get("previous_meter_read")

            result = await api.submit_self_meter_read(
                utility_account_number=self._uan,
                account_number=self._an,
                meter_number=meter_number,
                meter_reading=computed_index,
                previous_meter_read_data=previous_data,
            )

            if result.get("success"):
                self._submitted_this_window = True
                _LOGGER.info(
                    "Autotransmitere [%s]: Index %.1f trimis cu succes! %s",
                    self._uan,
                    computed_index,
                    result.get("message", ""),
                )
                # Notificare persistentă
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": f"iHidro: Index transmis automat ({self._uan})",
                            "message": (
                                f"Indexul {computed_index:.1f} kWh a fost trimis automat "
                                f"la Hidroelectrica pentru POD {self._uan}."
                            ),
                            "notification_id": f"ihidro_autosubmit_{self._uan}",
                        },
                    )
                )
                # Forțăm refresh
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error(
                    "Autotransmitere [%s]: Eroare la trimitere: %s",
                    self._uan,
                    result.get("message"),
                )
        except Exception as err:
            _LOGGER.error(
                "Autotransmitere [%s]: Excepție la trimitere: %s",
                self._uan,
                err,
            )

        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Atribute adiționale."""
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        energy_sensor = self._get_energy_sensor_id()
        if energy_sensor:
            attrs["senzor_energie"] = energy_sensor
            attrs["offset_calibrare"] = self._calibration_offset
            attrs["calibrare_la"] = self._calibration_time
            attrs["transmis_in_fereastra_curenta"] = self._submitted_this_window

            computed = self._compute_meter_index()
            if computed is not None:
                attrs["index_calculat"] = round(computed, 1)

            last_index = self._get_last_meter_index()
            if last_index is not None:
                attrs["ultimul_index_cunoscut"] = last_index

            attrs["delay_zile"] = self._get_delay_days()

            # Starea ferestrei
            attrs["fereastra_deschisa"] = self._is_reading_window_open()
        else:
            attrs["motiv_indisponibil"] = (
                "Configurați un senzor de energie extern în opțiunile integrării"
            )

        return attrs
