"""Senzori pentru integrarea iHidro.

Senzori existenți (rewritten):
- Sold Curent (factură curentă)
- Ultima Factură
- Index Contor (cu Energy Dashboard support + live tracking din senzor extern)
- Consum Lunar (cu Energy Dashboard support + live tracking din senzor extern)
- Ultima Plată
- POD Info

Senzori noi:
- Data Contract (DateContract din GetBill)
- Consum Anual (din billing history, cu Energy Dashboard support)
- Index Anual (din meter read history, cu cascading fallback)
- Total Plăți Anual (din plățile extrase din bill_history)
- Producție Prosumator (dacă POD-ul este prosumator, cu Energy Dashboard support)
- Compensare ANRE Prosumator (din separarea plăților pe canal)
- Sold Factură (Plătit/Neplătit/Credit — migrat din binary_sensor.py)

Notă: Citire Permisă este senzor string (Da/Nu) aici.
Factură Restantă rămâne BinarySensorEntity în binary_sensor.py.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTRIBUTION,
    CONF_ENERGY_SENSOR,
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
from .coordinator import IhidroAccountCoordinator
from .helpers import (
    safe_float,
    format_date_ro,
    format_ron,
    format_number_ro,
    parse_date,
    is_prosumer,
    is_reading_window_open,
    get_meter_index_cascading,
    get_payment_list_from_bill_history,
    split_payments_by_channel,
    get_current_bill_data,
    get_bill_history_list,
    get_data_list,
    get_data_dict,
    get_meter_window_info,
    get_tentative_data,
)

_LOGGER = logging.getLogger(__name__)

# Monedă România
CURRENCY_RON = "RON"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurare senzori din config entry."""
    from . import IhidroRuntimeData

    runtime_data: IhidroRuntimeData = hass.data[DOMAIN][entry.entry_id]
    coordinators = runtime_data.coordinators

    entities: List[SensorEntity] = []

    for uan, coordinator in coordinators.items():
        # Senzori standard (pentru fiecare POD)
        entities.extend(
            [
                IhidroCurrentBalanceSensor(coordinator, entry),
                IhidroLastBillSensor(coordinator, entry),
                IhidroMeterReadingSensor(coordinator, entry),
                IhidroMonthlyConsumptionSensor(coordinator, entry),
                IhidroLastPaymentSensor(coordinator, entry),
                IhidroPODInfoSensor(coordinator, entry),
                # Senzori noi (faze anterioare)
                IhidroDateContractSensor(coordinator, entry),
                IhidroConsumAnualSensor(coordinator, entry),
                IhidroIndexAnualSensor(coordinator, entry),
                IhidroTotalPlatiAnualSensor(coordinator, entry),
                # Senzori noi (Phase M, P) — disponibili pentru toți utilizatorii
                IhidroDailyConsumptionSensor(coordinator, entry),
                IhidroDaysUntilDueSensor(coordinator, entry),
                # Senzor tarif real all-in (Phase X)
                IhidroTarifRealSensor(coordinator, entry),
                # Senzori inteligenți (Phase Z1, Z2)
                IhidroEstimareFacturaSensor(coordinator, entry),
                IhidroAnomalieConsumSensor(coordinator, entry),
                # Senzor citire permisă (Da/Nu)
                IhidroCitirePermisaSensor(coordinator, entry),
                # Senzor sold factură (Plătit/Neplătit/Credit)
                IhidroSoldFacturaSensor(coordinator, entry),
            ]
        )

        # Senzori prosumator (doar dacă detectăm registrul _P)
        meter_read_history = (
            coordinator.data.get("meter_read_history") if coordinator.data else None
        )
        if is_prosumer(meter_read_history):
            entities.extend(
                [
                    IhidroProductieProsumatorSensor(coordinator, entry),
                    IhidroCompensareANRESensor(coordinator, entry),
                    # Senzori noi prosumator (Phase N, O)
                    IhidroGenerationSensor(coordinator, entry),
                    IhidroNetUsageSensor(coordinator, entry),
                ]
            )

    async_add_entities(entities)
    _LOGGER.info("Au fost creați %d senzori iHidro", len(entities))


# =============================================================================
# Senzor de bază
# =============================================================================


class IhidroBaseSensor(CoordinatorEntity, SensorEntity):
    """Senzor de bază pentru iHidro.

    Fiecare senzor primește un IhidroAccountCoordinator (per UAN),
    nu mai folosim index de account.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IhidroAccountCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Inițializare senzor de bază."""
        super().__init__(coordinator)
        self.entry = entry
        self._uan = coordinator.uan
        self._an = coordinator.an
        self._address = coordinator.account_info.get("Address", "")

    @property
    def _data(self) -> Dict[str, Any]:
        """Shortcut la datele coordinatorului."""
        return self.coordinator.data or {}

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informații despre device (grupare senzori per POD)."""
        return {
            "identifiers": {(DOMAIN, f"{self.entry.entry_id}_{self._uan}")},
            "name": f"iHidro POD {self._uan}",
            "manufacturer": "Hidroelectrica România",
            "model": "Punct de Consum Electric",
            "entry_type": DeviceEntryType.SERVICE,
        }

    # --- Metode comune pentru senzorul de energie extern ---

    def _get_energy_sensor_id(self) -> Optional[str]:
        """Returnează entity_id senzorului de energie extern configurat."""
        energy_sensor = self.entry.options.get(CONF_ENERGY_SENSOR, "")
        return energy_sensor if energy_sensor else None

    def _get_external_energy_kwh(self) -> Optional[float]:
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


class IhidroEnergySensorMixin:
    """Mixin pentru senzorii care folosesc senzorul de energie extern.

    Oferă live meter index tracking prin offset calibration:
    - La fiecare update de coordinator (date API noi), stochează:
      offset = last_known_meter_index - energy_sensor_kwh_la_acel_moment
    - Între update-uri, calculează:
      live_index = current_energy_kwh + offset

    Astfel live_index crește 1:1 cu senzorul de energie între refresh-urile API.

    Utilizare: clasele care moștenesc acest mixin trebuie să aibă și
    IhidroBaseSensor în MRO (pentru acces la _data, entry, hass, etc.)
    """

    _energy_offset: Optional[float] = None
    _energy_snapshot_kwh: Optional[float] = None
    _last_api_index: Optional[float] = None

    def _calibrate_energy_offset(self) -> None:
        """Recalibrează offset-ul la primirea datelor noi de la API.

        Apelat din _handle_coordinator_update() al fiecărui senzor.
        """
        energy_kwh = self._get_external_energy_kwh()  # type: ignore[attr-defined]
        if energy_kwh is None:
            return

        active_meter = self._data.get("active_meter")  # type: ignore[attr-defined]
        last_index, _ = get_meter_index_cascading(
            self._data, register="1.8.0", active_meter=active_meter  # type: ignore[attr-defined]
        )
        if last_index is None or last_index <= 0:
            return

        self._energy_offset = round(last_index - energy_kwh, 3)
        self._energy_snapshot_kwh = energy_kwh
        self._last_api_index = last_index

    def _compute_live_index(self) -> Optional[float]:
        """Calculează indexul live al contorului folosind senzorul extern.

        Între update-urile API:
          live_index = current_energy_kwh + offset
          = current_energy_kwh + (last_api_index - energy_kwh_at_calibration)
          = last_api_index + (current_energy_kwh - energy_kwh_at_calibration)
          = last_api_index + consum_real_de_la_ultima_citire_api

        Când API-ul se actualizează, offset-ul se recalibrează automat.
        """
        if self._energy_offset is None:
            # Prima calibrare (nu avem offset încă)
            self._calibrate_energy_offset()

        if self._energy_offset is None:
            return None

        current_kwh = self._get_external_energy_kwh()  # type: ignore[attr-defined]
        if current_kwh is None:
            return None

        live_index = current_kwh + self._energy_offset
        return round(live_index, 2)

    def _energy_extra_attrs(self) -> Dict[str, Any]:
        """Returnează atributele extra legate de senzorul de energie."""
        attrs: Dict[str, Any] = {}
        energy_id = self._get_energy_sensor_id()  # type: ignore[attr-defined]
        if energy_id:
            attrs["energy_sensor"] = energy_id
            attrs["energy_offset"] = self._energy_offset
            attrs["energy_snapshot_kwh"] = self._energy_snapshot_kwh
            attrs["api_index_at_calibration"] = self._last_api_index
            live = self._compute_live_index()
            if live is not None:
                attrs["live_index"] = live
        return attrs

    def _handle_coordinator_update(self) -> None:
        """Override CoordinatorEntity._handle_coordinator_update.

        Recalibrează offset-ul la fiecare update de la coordinator, apoi
        apelează metoda originală pentru a actualiza starea în HA.
        """
        self._calibrate_energy_offset()
        super()._handle_coordinator_update()  # type: ignore[misc]


# =============================================================================
# Senzor Sold Curent (factură curentă)
# =============================================================================


class IhidroCurrentBalanceSensor(IhidroBaseSensor):
    """Senzor pentru sold curent (factură curentă)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RON
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Sold Curent"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_current_balance"

    @property
    def native_value(self) -> Optional[float]:
        bill = get_current_bill_data(self._data.get("current_bill"))
        if bill:
            return safe_float(bill.get("rembalance") or bill.get("billamount"))
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        bill = get_current_bill_data(self._data.get("current_bill"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
            ATTR_ADDRESS: self._address,
        }
        if bill:
            amount = safe_float(bill.get("rembalance") or bill.get("billamount"))
            attrs[ATTR_DUE_DATE] = format_date_ro(bill.get("duedate"))
            attrs["bill_number"] = bill.get("invoicenumber")
            attrs["bill_amount"] = format_ron(safe_float(bill.get("billamount")))
            attrs["remaining_balance"] = format_ron(safe_float(bill.get("rembalance")))
            attrs["sold_formatat"] = format_ron(amount)
        return attrs


# =============================================================================
# Senzor Ultima Factură
# =============================================================================


class IhidroLastBillSensor(IhidroBaseSensor):
    """Senzor pentru ultima factură."""

    _attr_icon = "mdi:file-document"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Ultima Factură"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_last_bill"

    @property
    def native_value(self) -> Optional[str]:
        bills = get_bill_history_list(self._data.get("bill_history"))
        if bills:
            # Cel mai relevant identificator disponibil
            return bills[0].get("exbel") or bills[0].get("invoiceType")
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        bills = get_bill_history_list(self._data.get("bill_history"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }
        if bills:
            last_bill = bills[0]
            amount = safe_float(last_bill.get("amount"))
            attrs["invoice_date"] = format_date_ro(last_bill.get("invoiceDate"))
            attrs[ATTR_AMOUNT] = last_bill.get("amount")
            attrs["amount_formatat"] = format_ron(amount)
            attrs["invoice_type"] = last_bill.get("invoiceType")
            attrs[ATTR_DUE_DATE] = format_date_ro(last_bill.get("dueDate"))
            attrs["bill_period"] = last_bill.get("billPeriod")
            attrs["bill_days"] = last_bill.get("billDays")
            attrs["current_charges"] = last_bill.get("currentCharges")
        return attrs


# =============================================================================
# Senzor Index Contor — cu Energy Dashboard support
# =============================================================================


class IhidroMeterReadingSensor(IhidroEnergySensorMixin, IhidroBaseSensor):
    """Senzor pentru index curent contor.

    Setează SensorDeviceClass.ENERGY pentru compatibilitate cu Energy Dashboard.
    Folosește cascading fallback: meter_read_history → previous_meter_read → meter_counter_series.

    Dacă un senzor de energie extern este configurat, oferă live index tracking
    între refresh-urile API (offset calibration via IhidroEnergySensorMixin).
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Index Contor"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_meter_reading"

    @property
    def native_value(self) -> Optional[float]:
        # Sursă preferată: live index din senzorul extern (real-time)
        live = self._compute_live_index()
        if live is not None:
            return live

        # Fallback: cascading pe 3 surse API
        active_meter = self._data.get("active_meter")
        value, source = get_meter_index_cascading(
            self._data, register="1.8.0", active_meter=active_meter
        )
        return value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        # Sursa datelor API
        active_meter = self._data.get("active_meter")
        api_value, source = get_meter_index_cascading(
            self._data, register="1.8.0", active_meter=active_meter
        )
        attrs["data_source"] = source
        attrs["active_meter"] = active_meter
        attrs["api_index"] = api_value

        # Info din meter_read_history
        # IMPORTANT: Lista este sortată ASCENDENT (cel mai vechi primul).
        # Folosim [-1] pentru cea mai recentă citire.
        history_entries = get_data_list(self._data.get("meter_read_history"))
        if history_entries:
            entry = history_entries[-1]
            attrs[ATTR_METER_NUMBER] = entry.get("CounterSeries")
            attrs[ATTR_LAST_READING] = entry.get("Index")
            attrs[ATTR_LAST_READING_DATE] = format_date_ro(entry.get("Date"))

        # Info fereastra citire
        window = get_meter_window_info(self._data.get("meter_window"))
        if window:
            attrs["reading_window_start"] = format_date_ro(
                window.get("NextMonthOpeningDate") or window.get("OpeningDate")
            )
            attrs["reading_window_end"] = format_date_ro(
                window.get("NextMonthClosingDate") or window.get("ClosingDate")
            )

        # Info senzor extern de energie (dacă configurat)
        attrs.update(self._energy_extra_attrs())

        return attrs


# =============================================================================
# Senzor Consum Lunar — cu Energy Dashboard support + live tracking
# =============================================================================


class IhidroMonthlyConsumptionSensor(IhidroEnergySensorMixin, IhidroBaseSensor):
    """Senzor pentru consum lunar.

    Surse de date (în ordinea priorității):
    1. getTentativeData.SoFar (pentru contoare AMI)
    2. Senzor extern: live_index - period_start_index (real-time)
    3. Fallback: diferența ultimelor 2 indexuri din meter_read_history
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Consum Lunar"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_monthly_consumption"

    def _get_period_start_index(self) -> Optional[float]:
        """Returnează indexul de la începutul perioadei curente.

        Citirile sunt sortate ASCENDENT: readings[-2] = start perioadă curentă.
        """
        history = get_data_list(self._data.get("meter_read_history"))
        if not history:
            return None
        readings = []
        for entry in history:
            reg = entry.get("Registers", "") or entry.get("Register", "")
            if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                idx = safe_float(entry.get("Index") or entry.get("MeterReading"))
                if idx > 0:
                    readings.append(idx)
        if len(readings) >= 2:
            return readings[-2]
        return None

    @property
    def native_value(self) -> Optional[float]:
        # Sursa 1: getTentativeData din daily_usage (SoFar = consum ciclu curent)
        tentative = get_tentative_data(self._data.get("daily_usage"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            if so_far > 0:
                return so_far

        # Sursa 2: senzor extern → live_index - period_start_index
        live_index = self._compute_live_index()
        if live_index is not None:
            period_start = self._get_period_start_index()
            if period_start is not None:
                consumption = live_index - period_start
                if consumption > 0:
                    return round(consumption, 2)

        # Fallback 3: derivă din diferența ultimelor 2 indexuri din meter_read_history
        history = get_data_list(self._data.get("meter_read_history"))
        if history and len(history) >= 2:
            readings = []
            for entry in history:
                reg = entry.get("Registers", "") or entry.get("Register", "")
                if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                    idx = safe_float(entry.get("Index") or entry.get("MeterReading"))
                    if idx > 0:
                        readings.append(idx)
            if len(readings) >= 2:
                # Ascendent: [-1] = recent, [-2] = precedent
                consumption = readings[-1] - readings[-2]
                if consumption > 0:
                    return round(consumption, 2)

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        tentative = get_tentative_data(self._data.get("daily_usage"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            expected = safe_float(tentative.get("ExpectedUsage"))
            average = safe_float(tentative.get("Average"))
            highest = safe_float(tentative.get("Highest"))
            attrs["usage_cycle"] = tentative.get("UsageCycle")
            attrs["so_far_kwh"] = format_number_ro(so_far) + " kWh" if so_far > 0 else None
            attrs["expected_kwh"] = format_number_ro(expected) + " kWh" if expected > 0 else None
            attrs["average_kwh"] = format_number_ro(average) + " kWh" if average > 0 else None
            attrs["highest_kwh"] = format_number_ro(highest) + " kWh" if highest > 0 else None
            attrs["data_source"] = "daily_usage_tentative"
        else:
            # Info derivată din meter_read_history (cele mai recente primele)
            history = get_data_list(self._data.get("meter_read_history"))
            if history:
                recent = []
                for item in reversed(history):
                    reg = item.get("Registers", "") or item.get("Register", "")
                    if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                        idx = safe_float(item.get("Index") or item.get("MeterReading"))
                        recent.append({
                            "index": idx,
                            "date": format_date_ro(item.get("Date")),
                            "register": reg,
                        })
                        if len(recent) >= 4:
                            break
                attrs["recent_readings"] = recent
                attrs["data_source"] = "meter_read_history_delta"

        # Info senzor extern de energie (dacă configurat)
        attrs.update(self._energy_extra_attrs())

        return attrs


# =============================================================================
# Senzor Ultima Plată
# =============================================================================


class IhidroLastPaymentSensor(IhidroBaseSensor):
    """Senzor pentru ultima plată.

    Plățile sunt extrase din bill_history (GetBillingHistoryList)
    la result.objBillingPaymentHistoryEntity. Endpoint-ul separat
    GetPaymentHistory nu există.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RON
    _attr_icon = "mdi:cash-check"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Ultima Plată"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_last_payment"

    def _get_payments(self) -> List[Dict[str, Any]]:
        """Extrage lista de plăți din bill_history."""
        return get_payment_list_from_bill_history(self._data.get("bill_history"))

    @property
    def native_value(self) -> Optional[float]:
        payments = self._get_payments()
        if payments:
            return safe_float(payments[0].get("amount") or payments[0].get("Amount"))
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        payments = self._get_payments()
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }
        if payments:
            last = payments[0]
            amount = safe_float(last.get("amount") or last.get("Amount"))
            attrs["payment_date"] = format_date_ro(
                last.get("paymentDate") or last.get("PaymentDate")
            )
            attrs["payment_method"] = (
                last.get("channel") or last.get("PaymentChannel") or last.get("PaymentMethod")
            )
            attrs["reference"] = last.get("Reference") or last.get("reference")
            attrs["amount_formatat"] = format_ron(amount)
        return attrs


# =============================================================================
# Senzor POD Info
# =============================================================================


class IhidroPODInfoSensor(IhidroBaseSensor):
    """Senzor pentru informații generale despre POD."""

    _attr_icon = "mdi:information"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "POD Info"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_pod_info"

    @property
    def native_value(self) -> str:
        return self._address or "Adresă necunoscută"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        account_info = self._data.get("account_info", {})
        pods_entries = get_data_list(self._data.get("pods"))
        master_entries = get_data_list(self._data.get("master_data_status"))

        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
            ATTR_ADDRESS: self._address,
            "customer_name": account_info.get("CustomerName"),
            "is_default": account_info.get("IsDefaultAccount"),
            "active_meter": self._data.get("active_meter"),
        }

        # Date POD din GetPods (lowercase keys)
        if pods_entries:
            pod = pods_entries[0]
            attrs["installation"] = pod.get("installation")
            attrs["pod"] = pod.get("pod")
            attrs["contract_account_id"] = pod.get("contractAccountID")

        # Date master din GetMasterDataStatus
        if master_entries:
            master = master_entries[0]
            attrs["master_id"] = master.get("MasterID")
            attrs["service_name"] = master.get("ServiceName")
            attrs["last_updated"] = master.get("LastUpdated")

        return attrs


# =============================================================================
# Senzor Data Contract (NOU)
# =============================================================================


class IhidroDateContractSensor(IhidroBaseSensor):
    """Senzor pentru data contractului (din GetBill)."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Data Contract"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_date_contract"

    @property
    def native_value(self) -> Optional[str]:
        # current_bill nu are DateContract — încercăm previous_meter_read
        prev_entries = get_data_list(self._data.get("previous_meter_read"))
        if prev_entries:
            # Câmpuri posibile: distContractDate, prevMRDate
            date_contract = (
                prev_entries[0].get("distContractDate")
                or prev_entries[0].get("ContractDate")
                or prev_entries[0].get("DateContract")
            )
            if date_contract:
                return format_date_ro(date_contract)

        # Fallback pe current_bill (în cazul în care API-ul se schimbă)
        bill = get_current_bill_data(self._data.get("current_bill"))
        if bill:
            date_contract = bill.get("DateContract") or bill.get("ContractDate")
            if date_contract:
                return format_date_ro(date_contract)

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
        }
        prev_entries = get_data_list(self._data.get("previous_meter_read"))
        if prev_entries:
            entry = prev_entries[0]
            attrs["serial_number"] = entry.get("serialNumber")
            attrs["distributor"] = entry.get("distributor")
            attrs["supplier"] = entry.get("supplier")
        return attrs


# =============================================================================
# Senzor Consum Anual — cu Energy Dashboard support
# =============================================================================


class IhidroConsumAnualSensor(IhidroBaseSensor):
    """Senzor pentru consumul total pe ultimele 12 luni (din billing history)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Consum Anual"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_consum_anual"

    @property
    def native_value(self) -> Optional[float]:
        # bill_history nu are câmpul Consumption — derivăm din meter_read_history
        # Consumul anual = diferența între primul și ultimul index din istoric
        history = get_data_list(self._data.get("meter_read_history"))
        if not history:
            return None

        # Filtrăm doar registrul standard (nu _P)
        readings = []
        for entry in history:
            reg = entry.get("Registers", "") or entry.get("Register", "")
            if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                idx = safe_float(entry.get("Index") or entry.get("MeterReading"))
                if idx > 0:
                    readings.append(idx)

        if len(readings) >= 2:
            # Lista e ordonată cronologic ASCENDENT (cel mai vechi primul)
            # readings[-1] = cel mai recent, readings[0] = cel mai vechi
            consumption = readings[-1] - readings[0]
            return round(consumption, 2) if consumption > 0 else None

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        history = get_data_list(self._data.get("meter_read_history"))
        readings = []
        if history:
            for entry in history:
                reg = entry.get("Registers", "") or entry.get("Register", "")
                if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                    idx = safe_float(entry.get("Index") or entry.get("MeterReading"))
                    if idx > 0:
                        readings.append(idx)

        # Lista ascendentă: [-1] = recent, [0] = vechi
        total = (readings[-1] - readings[0]) if len(readings) >= 2 else 0.0
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            "readings_count": len(readings),
            "consum_formatat": format_number_ro(total) + " kWh" if total > 0 else None,
            "data_source": "meter_read_history_delta",
        }
        return attrs


# =============================================================================
# Senzor Index Anual — cu cascading fallback
# =============================================================================


class IhidroIndexAnualSensor(IhidroBaseSensor):
    """Senzor pentru cel mai recent index din meter read history.

    Folosește cascading fallback:
    1. GetMeterReadHistory (filtrat pe seria activă + registru 1.8.0)
    2. GetPreviousMeterRead
    3. GetMeterCounterSeries
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Index Istoric"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_index_anual"

    @property
    def native_value(self) -> Optional[float]:
        active_meter = self._data.get("active_meter")
        value, _ = get_meter_index_cascading(
            self._data, register="1.8.0", active_meter=active_meter
        )
        return value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        active_meter = self._data.get("active_meter")
        _, source = get_meter_index_cascading(
            self._data, register="1.8.0", active_meter=active_meter
        )

        history_entries = get_data_list(self._data.get("meter_read_history"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            "data_source": source,
            "active_meter": active_meter,
        }
        if history_entries:
            # Ultimele 3 citiri (doar registrul standard)
            # IMPORTANT: Lista e ASCENDENTĂ — iterăm reversed pentru cele mai recente
            history = []
            for item in reversed(history_entries):
                register = item.get("Registers", "") or item.get("Register", "")
                if register == "1.8.0" or (register and not register.endswith("_P")):
                    history.append(
                        {
                            "reading": item.get("Index"),
                            "date": format_date_ro(item.get("Date")),
                            "register": register,
                            "type": item.get("ReadingType"),
                        }
                    )
                    if len(history) >= 3:
                        break
            attrs["recent_readings"] = history
        return attrs


# =============================================================================
# Senzor Total Plăți Anual
# =============================================================================


class IhidroTotalPlatiAnualSensor(IhidroBaseSensor):
    """Senzor pentru totalul plăților pe ultimele 12 luni.

    Plățile sunt extrase din bill_history (GetBillingHistoryList)
    la result.objBillingPaymentHistoryEntity.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RON
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Total Plăți Anual"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_total_plati_anual"

    def _get_payments(self) -> List[Dict[str, Any]]:
        """Extrage lista de plăți din bill_history."""
        return get_payment_list_from_bill_history(self._data.get("bill_history"))

    @property
    def native_value(self) -> Optional[float]:
        payments = self._get_payments()
        if not payments:
            return None

        total = 0.0
        for payment in payments:
            total += safe_float(payment.get("amount") or payment.get("Amount"))
        return round(total, 2) if total > 0 else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        payments = self._get_payments()
        total = 0.0
        if payments:
            for payment in payments:
                total += safe_float(payment.get("amount") or payment.get("Amount"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            "payments_count": len(payments),
            "total_formatat": format_ron(total) if total > 0 else None,
        }
        return attrs


# =============================================================================
# Senzor Producție Prosumator — cu Energy Dashboard support
# =============================================================================


class IhidroProductieProsumatorSensor(IhidroBaseSensor):
    """Senzor pentru producția de energie a prosumatorului (registrul _P).

    Compatibil cu Energy Dashboard: SensorDeviceClass.ENERGY + TOTAL_INCREASING.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:solar-power"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Producție Prosumator"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_productie_prosumator"

    @property
    def native_value(self) -> Optional[float]:
        # Cascading fallback pentru registrul de producție
        active_meter = self._data.get("active_meter")
        value, _ = get_meter_index_cascading(
            self._data, register="1.8.0_P", active_meter=active_meter
        )
        if value is not None:
            return value

        # Fallback: caută orice registru cu _P
        history = get_data_list(self._data.get("meter_read_history"))
        if history:
            for entry_item in history:
                register = entry_item.get("Registers", "") or entry_item.get("Register", "")
                if "_P" in register.upper():
                    reading = safe_float(entry_item.get("Index") or entry_item.get("MeterReading"))
                    if reading > 0:
                        return reading
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        history = get_data_list(self._data.get("meter_read_history"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            "is_prosumer": True,
        }
        if history:
            # Ultimele citiri de producție
            production_history = []
            for item in history:
                register = item.get("Registers", "") or item.get("Register", "")
                if "_P" in register.upper():
                    reading = safe_float(item.get("Index") or item.get("MeterReading"))
                    production_history.append(
                        {
                            "reading": item.get("Index"),
                            "reading_formatat": format_number_ro(reading) + " kWh",
                            "date": format_date_ro(item.get("Date")),
                            "register": register,
                        }
                    )
                    if len(production_history) >= 5:
                        break
            attrs["production_readings"] = production_history
        return attrs


# =============================================================================
# Senzor Compensare ANRE Prosumator — bazat pe separare plăți pe canal
# =============================================================================


class IhidroCompensareANRESensor(IhidroBaseSensor):
    """Senzor pentru compensarea ANRE a prosumatorului.

    Folosește separarea plăților pe canal de plată:
    - "Comp ANRE-*" → compensări ANRE (credite prosumator)
    Calculează totalul compensărilor din plățile extrase din bill_history
    (result.objBillingPaymentHistoryEntity).
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RON
    _attr_icon = "mdi:cash-refund"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Compensare ANRE"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_compensare_anre"

    def _get_payments(self) -> List[Dict[str, Any]]:
        """Extrage lista de plăți din bill_history."""
        return get_payment_list_from_bill_history(self._data.get("bill_history"))

    @property
    def native_value(self) -> Optional[float]:
        """Calculează totalul compensărilor ANRE din separarea plăților pe canal."""
        payments = self._get_payments()
        _, anre_payments = split_payments_by_channel(payments)

        if not anre_payments:
            return None

        total = 0.0
        for payment in anre_payments:
            total += safe_float(payment.get("amount") or payment.get("Amount"))
        return round(total, 2) if total != 0 else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        payments = self._get_payments()
        normal_payments, anre_payments = split_payments_by_channel(payments)

        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            "is_prosumer": True,
            "anre_payments_count": len(anre_payments),
            "normal_payments_count": len(normal_payments),
        }

        if anre_payments:
            total = sum(safe_float(p.get("amount") or p.get("Amount")) for p in anre_payments)
            attrs["total_formatat"] = format_ron(total)
            # Ultimele 3 compensări
            recent = []
            for p in anre_payments[:3]:
                amount = safe_float(p.get("amount") or p.get("Amount"))
                recent.append(
                    {
                        "amount": p.get("amount") or p.get("Amount"),
                        "amount_formatat": format_ron(amount),
                        "date": format_date_ro(
                            p.get("paymentDate") or p.get("PaymentDate")
                        ),
                        "channel": p.get("channel") or p.get("PaymentChannel"),
                    }
                )
            attrs["recent_compensations"] = recent

        # Adăugăm ultimele citiri pentru referință
        history = get_data_list(self._data.get("meter_read_history"))
        if history:
            latest_consumption = None
            latest_production = None
            for item in history:
                register = item.get("Registers", "") or item.get("Register", "")
                reading = safe_float(item.get("Index") or item.get("MeterReading"))
                if "_P" in register.upper() and latest_production is None:
                    latest_production = reading
                elif latest_consumption is None and "_P" not in register.upper():
                    latest_consumption = reading

            attrs["latest_consumption_index"] = latest_consumption
            attrs["latest_production_index"] = latest_production

        return attrs


# =============================================================================
# Senzor Consum Zilnic — cu Energy Dashboard support + energy sensor fallback
# =============================================================================


class IhidroDailyConsumptionSensor(IhidroEnergySensorMixin, IhidroBaseSensor):
    """Senzor pentru consumul zilnic.

    Surse de date (în ordinea priorității):
    1. getTentativeData.SoFar / Average (pentru contoare AMI)
    2. Senzor extern: consumul lunar / zile în perioadă (medie zilnică live)
    3. Fallback: consum lunar din meter_read_history / 30
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:calendar-today"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Consum Zilnic"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_daily_consumption"

    def _get_period_info(self) -> Optional[Dict[str, Any]]:
        """Calculează informații despre perioada curentă.

        Returnează dict cu period_start_index, period_start_date, days_elapsed.
        Folosit pentru a deriva consumul zilnic din senzorul extern.
        """
        history = get_data_list(self._data.get("meter_read_history"))
        if not history or len(history) < 2:
            return None

        # Filtrăm pe 1.8.0, lista e ASCENDENTĂ
        filtered = []
        for entry in history:
            reg = entry.get("Registers", "") or entry.get("Register", "")
            if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                idx = safe_float(entry.get("Index") or entry.get("MeterReading"))
                dt = parse_date(entry.get("Date"))
                if idx > 0 and dt:
                    filtered.append({"index": idx, "date": dt})

        if len(filtered) < 2:
            return None

        # [-1] = cel mai recent, [-2] = start perioadă curentă
        period_start = filtered[-2]
        days_elapsed = (datetime.now() - period_start["date"]).days
        if days_elapsed <= 0:
            days_elapsed = 1  # evităm div by zero

        return {
            "period_start_index": period_start["index"],
            "period_start_date": period_start["date"],
            "days_elapsed": days_elapsed,
        }

    @property
    def native_value(self) -> Optional[float]:
        # Sursa 1: tentative data (AMI)
        tentative = get_tentative_data(self._data.get("daily_usage"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            if so_far > 0:
                return so_far
            average = safe_float(tentative.get("Average"))
            if average > 0:
                return average

        # Sursa 2: senzor extern → (live_index - period_start) / zile
        live_index = self._compute_live_index()
        if live_index is not None:
            period = self._get_period_info()
            if period:
                monthly_consumption = live_index - period["period_start_index"]
                if monthly_consumption > 0:
                    daily = monthly_consumption / period["days_elapsed"]
                    return round(daily, 2)

        # Fallback 3: consum lunar din meter_read_history / 30
        history = get_data_list(self._data.get("meter_read_history"))
        if history and len(history) >= 2:
            readings = []
            for entry in history:
                reg = entry.get("Registers", "") or entry.get("Register", "")
                if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                    idx = safe_float(entry.get("Index") or entry.get("MeterReading"))
                    if idx > 0:
                        readings.append(idx)
            if len(readings) >= 2:
                monthly = readings[-1] - readings[-2]
                if monthly > 0:
                    return round(monthly / 30, 2)

        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        tentative = get_tentative_data(self._data.get("daily_usage"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            expected = safe_float(tentative.get("ExpectedUsage"))
            average = safe_float(tentative.get("Average"))
            highest = safe_float(tentative.get("Highest"))
            attrs["so_far_kwh"] = format_number_ro(so_far) + " kWh" if so_far > 0 else "0 kWh"
            attrs["expected_kwh"] = format_number_ro(expected) + " kWh" if expected > 0 else None
            attrs["average_kwh"] = format_number_ro(average) + " kWh" if average > 0 else None
            attrs["highest_kwh"] = format_number_ro(highest) + " kWh" if highest > 0 else None
            attrs["usage_cycle"] = tentative.get("UsageCycle")
            attrs["data_source"] = "daily_usage_tentative"
        else:
            # Determinăm sursa reală folosită
            live_index = self._compute_live_index()
            period = self._get_period_info()
            if live_index is not None and period:
                monthly = live_index - period["period_start_index"]
                if monthly > 0:
                    attrs["data_source"] = "energy_sensor_daily_avg"
                    attrs["consum_lunar_live"] = format_number_ro(monthly) + " kWh"
                    attrs["zile_in_perioada"] = period["days_elapsed"]
                else:
                    attrs["data_source"] = "meter_read_history_avg"
            else:
                attrs["data_source"] = "meter_read_history_avg"

        # Info senzor extern de energie (dacă configurat)
        attrs.update(self._energy_extra_attrs())

        return attrs


# =============================================================================
# Senzor Producție Generare — prosumator (Phase N)
# =============================================================================


class IhidroGenerationSensor(IhidroBaseSensor):
    """Senzor pentru datele de generare/producție (GetUsageGeneration cu UsageOrGeneration=True).

    Afișează producția de energie (export) ca time-series lunară.
    Doar pentru prosumatori — coexistă cu IhidroProductieProsumatorSensor
    (care raportează indexul contorului de producție din meter_read_history,
    pe când acesta raportează consumul/producția efectivă din usage data).
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:solar-power-variant"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Generare Energie"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_generation"

    @property
    def native_value(self) -> Optional[float]:
        tentative = get_tentative_data(self._data.get("generation_data"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            if so_far > 0:
                return so_far
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
            "is_prosumer": True,
        }
        tentative = get_tentative_data(self._data.get("generation_data"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            expected = safe_float(tentative.get("ExpectedUsage"))
            average = safe_float(tentative.get("Average"))
            highest = safe_float(tentative.get("Highest"))
            attrs["so_far_kwh"] = format_number_ro(so_far) + " kWh" if so_far > 0 else "0 kWh"
            attrs["expected_kwh"] = format_number_ro(expected) + " kWh" if expected > 0 else None
            attrs["average_kwh"] = format_number_ro(average) + " kWh" if average > 0 else None
            attrs["highest_kwh"] = format_number_ro(highest) + " kWh" if highest > 0 else None
            attrs["usage_cycle"] = tentative.get("UsageCycle")
        return attrs


# =============================================================================
# Senzor Consum Net — prosumator (Phase O)
# =============================================================================


class IhidroNetUsageSensor(IhidroBaseSensor):
    """Senzor pentru consumul net (GetUsageGeneration cu IsNetUsage=True).

    Consum net = import - export. Valori negative indică surplus de producție.
    Esențial pentru calcularea ROI-ului panourilor solare.

    Folosim SensorStateClass.MEASUREMENT deoarece valorile pot fi negative.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Consum Net"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_net_usage"

    @property
    def native_value(self) -> Optional[float]:
        tentative = get_tentative_data(self._data.get("net_usage"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            # Net usage poate fi 0 sau negativ (surplus)
            return so_far
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
            "is_prosumer": True,
        }
        tentative = get_tentative_data(self._data.get("net_usage"))
        if tentative:
            so_far = safe_float(tentative.get("SoFar"))
            expected = safe_float(tentative.get("ExpectedUsage"))
            average = safe_float(tentative.get("Average"))
            attrs["net_so_far_kwh"] = format_number_ro(so_far) + " kWh"
            attrs["expected_kwh"] = format_number_ro(expected) + " kWh" if expected != 0 else None
            attrs["average_kwh"] = format_number_ro(average) + " kWh" if average != 0 else None
            attrs["usage_cycle"] = tentative.get("UsageCycle")
            attrs["is_surplus"] = so_far < 0
            attrs["is_ami"] = tentative.get("IsOnlyAMI")
        return attrs


# =============================================================================
# Senzor Zile Până la Scadență (Phase P)
# =============================================================================


class IhidroDaysUntilDueSensor(IhidroBaseSensor):
    """Senzor pentru numărul de zile rămase până la scadența facturii.

    Calculat din current_bill.DueDate. Util pentru automatizări de plată:
    - trigger: state < 3 → trimite notificare urgentă
    - trigger: state == 0 → factură scadentă azi
    - Valori negative = factură restantă de N zile
    """

    _attr_icon = "mdi:calendar-alert"
    _attr_native_unit_of_measurement = "zile"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Zile Până la Scadență"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_days_until_due"

    @property
    def native_value(self) -> Optional[int]:
        bill = get_current_bill_data(self._data.get("current_bill"))
        if bill:
            due_date_str = bill.get("duedate")
            if due_date_str:
                due_dt = parse_date(due_date_str)
                if due_dt:
                    delta = due_dt - datetime.now()
                    return delta.days
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        bill = get_current_bill_data(self._data.get("current_bill"))
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
        }
        if bill:
            due_date_str = bill.get("duedate")
            attrs[ATTR_DUE_DATE] = format_date_ro(due_date_str)
            attrs[ATTR_AMOUNT] = bill.get("rembalance") or bill.get("billamount")
            attrs["invoice_number"] = bill.get("invoicenumber")
            # Stare derivată
            days = self.native_value
            if days is not None:
                if days < 0:
                    attrs["status_plata"] = f"Restantă de {abs(days)} zile"
                elif days == 0:
                    attrs["status_plata"] = "Scadentă azi"
                elif days <= 3:
                    attrs["status_plata"] = "Aproape de scadență"
                else:
                    attrs["status_plata"] = "În termen"
        return attrs


# =============================================================================
# Senzor Tarif Real — cost all-in per kWh (Phase X)
# =============================================================================


class IhidroTarifRealSensor(IhidroBaseSensor):
    """Senzor pentru tariful real all-in per kWh.

    Calculează costul complet pe kWh (inclusiv distribuție, transport,
    certificate verzi, cogenerare, TVA) din raportul Amount/Consumption
    al facturilor. Răspunde la întrebarea: "Cât plătesc de fapt pe kWh?"

    Nicio altă integrare românească nu oferă această informație.

    Atribute expuse:
    - tarif_curent: ultimul tarif (din cea mai recentă factură)
    - tarif_mediu_3_luni: media pe ultimele 3 luni
    - tarif_mediu_12_luni: media pe ultimele 12 luni
    - tendinta: "crește" / "scade" / "stabil" (comparație ultimele 2 facturi)
    - istoric_tarife: lista tarif per lună pe ultimul an
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "RON/kWh"
    _attr_icon = "mdi:currency-eur"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Tarif Real"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_tarif_real"

    def _compute_tariffs(self) -> list:
        """Calculează tariful per kWh din fiecare factură.

        API-ul Hidroelectrica NU returnează câmpul Consumption în bill_history.
        Derivăm consumul din meter_read_history (delta Index între citiri consecutive)
        și asociem cu sumele din bill_history.

        Returns:
            Lista de dict-uri [{month, year, tariff, amount, consumption}, ...]
            ordonate cronologic (cel mai recent primul).
        """
        tariffs = []

        # Obținem facturile și citirile contorului
        bills = get_bill_history_list(self._data.get("bill_history"))
        readings = get_data_list(self._data.get("meter_read_history"))

        # Filtrăm citirile pe registrul de consum (1.8.0) și le sortăm descrescător
        consumption_readings = []
        for r in readings:
            reg = r.get("Registers", "") or r.get("Register", "")
            if reg == "1.8.0":
                idx = safe_float(r.get("Index") or r.get("MeterReading"))
                dt = parse_date(r.get("Date") or r.get("ReadingDate"))
                if idx > 0 and dt:
                    consumption_readings.append({"index": idx, "date": dt})

        # Sortăm descrescător (cel mai recent primul)
        consumption_readings.sort(key=lambda x: x["date"], reverse=True)

        # Calculăm delta între citiri consecutive = consum per perioadă
        consumption_deltas = []
        for i in range(len(consumption_readings) - 1):
            current = consumption_readings[i]
            previous = consumption_readings[i + 1]
            delta = current["index"] - previous["index"]
            if delta > 0:
                consumption_deltas.append({
                    "consumption": delta,
                    "date": current["date"],
                    "period_start": previous["date"],
                })

        # Asociem facturile cu deltas de consum pe baza datei
        for bill in bills:
            amount = safe_float(bill.get("amount") or bill.get("Amount"))
            if amount <= 0:
                continue

            bill_date_str = bill.get("invoiceDate") or bill.get("BillDate")
            bill_date = parse_date(bill_date_str) if bill_date_str else None

            # Căutăm delta de consum cea mai apropiată de data facturii
            matched_consumption = None
            if bill_date and consumption_deltas:
                best_match = None
                best_diff = None
                for delta in consumption_deltas:
                    diff = abs((delta["date"] - bill_date).days)
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        best_match = delta
                # Acceptăm dacă diferența este < 45 zile (ciclu factură)
                if best_match and best_diff is not None and best_diff < 45:
                    matched_consumption = best_match["consumption"]

            if matched_consumption and matched_consumption > 0:
                tariffs.append({
                    "month": bill_date_str,
                    "year": str(bill_date.year) if bill_date else None,
                    "tariff": round(amount / matched_consumption, 4),
                    "amount": amount,
                    "consumption": matched_consumption,
                })

        return tariffs

    @property
    def native_value(self) -> Optional[float]:
        tariffs = self._compute_tariffs()
        if tariffs:
            return tariffs[0]["tariff"]
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        tariffs = self._compute_tariffs()
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        if not tariffs:
            return attrs

        # Tarif curent
        attrs["tarif_curent"] = f"{tariffs[0]['tariff']:.4f} lei/kWh"
        attrs["consum_ultima_factura"] = (
            format_number_ro(tariffs[0]["consumption"]) + " kWh"
        )
        attrs["suma_ultima_factura"] = format_ron(tariffs[0]["amount"])

        # Media pe 3 luni
        last_3 = tariffs[:3]
        if len(last_3) >= 2:
            total_amount = sum(t["amount"] for t in last_3)
            total_consumption = sum(t["consumption"] for t in last_3)
            if total_consumption > 0:
                avg_3 = round(total_amount / total_consumption, 4)
                attrs["tarif_mediu_3_luni"] = f"{avg_3:.4f} lei/kWh"

        # Media pe 12 luni
        if len(tariffs) >= 2:
            total_amount = sum(t["amount"] for t in tariffs)
            total_consumption = sum(t["consumption"] for t in tariffs)
            if total_consumption > 0:
                avg_12 = round(total_amount / total_consumption, 4)
                attrs["tarif_mediu_anual"] = f"{avg_12:.4f} lei/kWh"

        # Tendința (comparăm ultimele 2)
        if len(tariffs) >= 2:
            current = tariffs[0]["tariff"]
            previous = tariffs[1]["tariff"]
            diff_pct = ((current - previous) / previous) * 100 if previous > 0 else 0
            if diff_pct > 2:
                attrs["tendinta"] = "crește"
                attrs["variatie"] = f"+{diff_pct:.1f}%"
            elif diff_pct < -2:
                attrs["tendinta"] = "scade"
                attrs["variatie"] = f"{diff_pct:.1f}%"
            else:
                attrs["tendinta"] = "stabil"
                attrs["variatie"] = f"{diff_pct:+.1f}%"

        # Istoric complet
        attrs["istoric_tarife"] = [
            {
                "luna": t["month"],
                "tarif": f"{t['tariff']:.4f}",
                "consum_kwh": t["consumption"],
                "suma_lei": t["amount"],
            }
            for t in tariffs
        ]

        # Min / Max pe an
        tariff_values = [t["tariff"] for t in tariffs]
        attrs["tarif_minim_an"] = f"{min(tariff_values):.4f} lei/kWh"
        attrs["tarif_maxim_an"] = f"{max(tariff_values):.4f} lei/kWh"

        return attrs


# =============================================================================
# Senzor Estimare Factură Următoare (Phase Z1)
# =============================================================================


class IhidroEstimareFacturaSensor(IhidroBaseSensor):
    """Senzor care estimează factura următoare.

    Calculează pe baza:
    1. Consumul mediu din ultimele 3 luni (trend recent) — metoda implicită
    2. Consumul real de la senzorul de energie extern (dacă este configurat)
    3. Tariful real all-in curent (Amount/Consumption)

    Dacă un senzor de energie extern este configurat (ex. Shelly EM, smart plug),
    estimarea folosește delta kWh acumulată de la ultima factură, extrapolată
    pe luna întreagă. Altfel, se bazează pe media consumului din ultimele 3 facturi.

    Formula cu senzor extern:
        zile_trecute = (azi - data_ultima_factura).days
        consum_zilnic = delta_kwh_extern / zile_trecute
        consum_estimat_luna = consum_zilnic × 30
        estimare = consum_estimat_luna × tarif_real

    Formula fără senzor extern (fallback):
        consum_mediu_3_luni × tarif_real_curent = estimare_factura

    Oferă estimări cu intervale de încredere:
    - estimare_conservatoare (medie + 1 deviație standard)
    - estimare_optimistă (medie - 1 deviație standard)
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RON
    _attr_icon = "mdi:crystal-ball"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Estimare Factură"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_estimare_factura"

    def _get_energy_sensor_id(self) -> Optional[str]:
        """Returnează entity_id-ul senzorului de energie extern, dacă este configurat."""
        energy_sensor = self.entry.options.get(CONF_ENERGY_SENSOR, "")
        return energy_sensor if energy_sensor else None

    def _get_external_energy_kwh(self) -> Optional[float]:
        """Citește valoarea curentă din senzorul de energie extern.

        Returnează valoarea în kWh (convertește din Wh dacă este necesar).
        Returnează None dacă senzorul nu este configurat, indisponibil,
        sau are o valoare invalidă.
        """
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

        # Conversie din Wh în kWh dacă este cazul
        unit = state_obj.attributes.get("unit_of_measurement", "")
        if unit == "Wh":
            value = value / 1000.0

        return value

    def _get_last_bill_date(self) -> Optional[datetime]:
        """Obține data ultimei facturi emise."""
        bills = get_bill_history_list(self._data.get("bill_history"))
        if bills:
            for bill in bills:
                date_str = bill.get("invoiceDate") or bill.get("BillDate")
                if date_str:
                    dt = parse_date(date_str)
                    if dt:
                        return dt
        return None

    def _get_recent_bills(self) -> list:
        """Extrage facturile recente cu Amount + Consumption valide.

        bill_history nu are câmpul Consumption — derivăm consumul din
        meter_read_history (delta Index între citiri consecutive pe 1.8.0).
        """
        bill_list = get_bill_history_list(self._data.get("bill_history"))
        readings = get_data_list(self._data.get("meter_read_history"))

        # Construim perechi de consum din citirile contorului
        consumption_readings = []
        for r in readings:
            reg = r.get("Registers", "") or r.get("Register", "")
            if reg == "1.8.0":
                idx = safe_float(r.get("Index") or r.get("MeterReading"))
                dt = parse_date(r.get("Date") or r.get("ReadingDate"))
                if idx > 0 and dt:
                    consumption_readings.append({"index": idx, "date": dt})
        consumption_readings.sort(key=lambda x: x["date"], reverse=True)

        consumption_deltas = []
        for i in range(len(consumption_readings) - 1):
            delta = consumption_readings[i]["index"] - consumption_readings[i + 1]["index"]
            if delta > 0:
                consumption_deltas.append({
                    "consumption": delta,
                    "date": consumption_readings[i]["date"],
                })

        bills = []
        for bill in bill_list:
            amount = safe_float(bill.get("amount") or bill.get("Amount"))
            if amount <= 0:
                continue

            bill_date_str = bill.get("invoiceDate") or bill.get("BillDate")
            bill_date = parse_date(bill_date_str) if bill_date_str else None

            # Asociem cu delta de consum pe baza datei
            matched_consumption = None
            if bill_date and consumption_deltas:
                best_match = None
                best_diff = None
                for delta in consumption_deltas:
                    diff = abs((delta["date"] - bill_date).days)
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        best_match = delta
                if best_match and best_diff is not None and best_diff < 45:
                    matched_consumption = best_match["consumption"]

            if matched_consumption and matched_consumption > 0:
                bills.append({
                    "amount": amount,
                    "consumption": matched_consumption,
                    "tariff": round(amount / matched_consumption, 4),
                    "month": bill_date_str,
                    "year": str(bill_date.year) if bill_date else None,
                })
        return bills

    def _estimate_from_external_sensor(
        self, bills: list
    ) -> Optional[Dict[str, Any]]:
        """Calculează estimarea folosind senzorul de energie extern + offset calibration.

        Strategia:
        1. Calculăm live_index prin offset: energy_kwh + (last_api_index - energy_kwh_at_calibration)
        2. Obținem indexul contorului la ultima factură (din meter_read_history)
        3. delta_kwh = live_index - index_la_ultima_factura (consum REAL de la ultima factură)
        4. Extrapolăm la o lună completă: daily = delta / days_since_bill, monthly = daily × 30
        5. Aplicăm tariful real curent

        Returnează un dict cu estimarea și metadata, sau None dacă nu se poate calcula.
        """
        current_kwh = self._get_external_energy_kwh()
        if current_kwh is None:
            return None

        last_bill_date = self._get_last_bill_date()
        if last_bill_date is None:
            return None

        # Calculăm zilele de la ultima factură
        now = datetime.now()
        days_since_bill = (now - last_bill_date).days
        if days_since_bill <= 0:
            return None

        # Obținem indexul contorului la ultima factură din meter_read_history
        # Căutăm citirea cu data cea mai apropiată de data facturii
        last_bill_index = None
        readings = get_data_list(self._data.get("meter_read_history"))
        if readings:
            # Lista e ASCENDENTĂ — iterăm reversed pentru a găsi rapid
            for reading in reversed(readings):
                reg = reading.get("Registers", "") or reading.get("Register", "")
                if reg != "1.8.0" and (not reg or "_P" in reg.upper()):
                    continue
                date_str = reading.get("Date")
                if date_str:
                    dt = parse_date(date_str)
                    if dt and abs((dt - last_bill_date).days) <= 10:
                        idx = safe_float(reading.get("Index"))
                        if idx > 0:
                            last_bill_index = idx
                            break

        # Fallback: penultima citire (readings[-2]) — start perioadă curentă
        if last_bill_index is None and readings:
            filtered = []
            for r in readings:
                reg = r.get("Registers", "") or r.get("Register", "")
                if reg == "1.8.0" or (reg and "_P" not in reg.upper()):
                    idx = safe_float(r.get("Index") or r.get("MeterReading"))
                    if idx > 0:
                        filtered.append(idx)
            if len(filtered) >= 2:
                last_bill_index = filtered[-2]

        if last_bill_index is None or last_bill_index <= 0:
            return None

        # Calculăm live_index prin offset calibration
        # offset = last_api_index - current_kwh → live = current_kwh + offset
        active_meter = self._data.get("active_meter")
        last_api_index, _ = get_meter_index_cascading(
            self._data, register="1.8.0", active_meter=active_meter
        )
        if last_api_index is None or last_api_index <= 0:
            return None

        offset = last_api_index - current_kwh
        live_index = current_kwh + offset  # = last_api_index + (current_kwh - current_kwh) la calibrare

        # Delta kWh de la ultima factură (folosind live_index real-time)
        delta_kwh = live_index - last_bill_index
        if delta_kwh < 0:
            # Index reset sau eroare
            return None

        # Consumul zilnic real de la ultima factură
        daily_consumption = delta_kwh / days_since_bill

        # Extrapolăm la 30 de zile (o lună standard)
        estimated_monthly_consumption = daily_consumption * 30

        # Tariful curent
        if not bills:
            return None
        current_tariff = bills[0]["tariff"]

        estimate = round(estimated_monthly_consumption * current_tariff, 2)
        if estimate <= 0:
            return None

        return {
            "estimate": estimate,
            "method": "senzor_extern",
            "daily_consumption": round(daily_consumption, 2),
            "estimated_monthly_kwh": round(estimated_monthly_consumption, 1),
            "days_since_bill": days_since_bill,
            "delta_kwh": round(delta_kwh, 1),
            "live_index": round(live_index, 2),
            "last_bill_index": round(last_bill_index, 2),
            "current_tariff": current_tariff,
            "external_sensor": self._get_energy_sensor_id(),
            "external_sensor_kwh": round(current_kwh, 2),
        }

    @property
    def native_value(self) -> Optional[float]:
        bills = self._get_recent_bills()
        if len(bills) < 2:
            return None

        # Încercăm mai întâi cu senzorul extern
        external_estimate = self._estimate_from_external_sensor(bills)
        if external_estimate is not None:
            return external_estimate["estimate"]

        # Fallback: consum mediu pe ultimele 3 luni
        recent = bills[:3]
        avg_consumption = sum(b["consumption"] for b in recent) / len(recent)

        # Tarif curent (cel mai recent)
        current_tariff = bills[0]["tariff"]

        # Estimare
        estimate = round(avg_consumption * current_tariff, 2)
        return estimate if estimate > 0 else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        bills = self._get_recent_bills()
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        if len(bills) < 2:
            attrs["status"] = "Date insuficiente (minim 2 facturi)"
            return attrs

        # Încercăm mai întâi cu senzorul extern
        external_estimate = self._estimate_from_external_sensor(bills)

        if external_estimate is not None:
            attrs["metoda_calcul"] = "senzor_extern"
            attrs["senzor_extern"] = external_estimate["external_sensor"]
            attrs["senzor_extern_kwh"] = external_estimate["external_sensor_kwh"]
            attrs["estimare"] = format_ron(external_estimate["estimate"])
            attrs["consum_zilnic_estimat"] = (
                format_number_ro(external_estimate["daily_consumption"]) + " kWh"
            )
            attrs["consum_estimat_luna"] = (
                format_number_ro(external_estimate["estimated_monthly_kwh"]) + " kWh"
            )
            attrs["delta_kwh_de_la_factura"] = (
                format_number_ro(external_estimate["delta_kwh"]) + " kWh"
            )
            attrs["zile_de_la_factura"] = external_estimate["days_since_bill"]
            attrs["tarif_curent"] = f"{external_estimate['current_tariff']:.4f} lei/kWh"
        else:
            # Fallback: metoda clasică cu media pe 3 luni
            attrs["metoda_calcul"] = "medie_3_luni"
            if self._get_energy_sensor_id():
                # Senzor configurat dar nu s-a putut folosi
                attrs["senzor_extern_status"] = "indisponibil sau date insuficiente"

            recent = bills[:3]
            consumptions = [b["consumption"] for b in recent]
            avg_consumption = sum(consumptions) / len(consumptions)
            current_tariff = bills[0]["tariff"]

            # Deviația standard pentru interval de încredere
            if len(consumptions) >= 2:
                variance = sum((c - avg_consumption) ** 2 for c in consumptions) / len(
                    consumptions
                )
                std_dev = variance**0.5
            else:
                std_dev = 0.0

            estimate = avg_consumption * current_tariff
            estimate_high = (avg_consumption + std_dev) * current_tariff
            estimate_low = max(0, (avg_consumption - std_dev) * current_tariff)

            attrs["estimare"] = format_ron(estimate)
            attrs["estimare_conservatoare"] = format_ron(estimate_high)
            attrs["estimare_optimista"] = format_ron(estimate_low)
            attrs["consum_mediu_3_luni"] = (
                format_number_ro(avg_consumption) + " kWh"
            )
            attrs["tarif_curent"] = f"{current_tariff:.4f} lei/kWh"
            attrs["baza_calcul"] = f"{len(recent)} facturi recente"

        # Tendință consum (crește/scade) — comun ambelor metode
        if len(bills) >= 2:
            latest = bills[0]["consumption"]
            previous = bills[1]["consumption"]
            if previous > 0:
                diff_pct = ((latest - previous) / previous) * 100
                if diff_pct > 5:
                    attrs["tendinta_consum"] = "crește"
                    attrs["variatie_consum"] = f"+{diff_pct:.1f}%"
                elif diff_pct < -5:
                    attrs["tendinta_consum"] = "scade"
                    attrs["variatie_consum"] = f"{diff_pct:.1f}%"
                else:
                    attrs["tendinta_consum"] = "stabil"
                    attrs["variatie_consum"] = f"{diff_pct:+.1f}%"

        return attrs


# =============================================================================
# Senzor Anomalie Consum (Phase Z2)
# =============================================================================


class IhidroAnomalieConsumSensor(IhidroBaseSensor):
    """Senzor care detectează anomalii în consumul de energie.

    Compară consumul curent cu:
    1. Media ultimelor 3 luni (deviație pe termen scurt)
    2. Aceeași lună anul trecut (deviație sezonieră YoY)

    Starea senzorului: "normal" / "consum_ridicat" / "consum_scazut" / "anomalie"
    Prag de alertă: >20% deviație față de medie sau YoY.

    Cazuri de utilizare:
    - Detectare aparate defecte (consum brusc ridicat)
    - Detectare probleme contor
    - Verificare eficiență măsuri de economisire
    """

    _attr_icon = "mdi:alert-decagram"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Anomalie Consum"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_anomalie_consum"

    def _analyze_consumption(self) -> Dict[str, Any]:
        """Analizează consumul și detectează anomalii.

        Derivează consumul lunar din meter_read_history (diferențe de index
        între citiri consecutive), deoarece bill_history nu conține un câmp
        Consumption.

        Returns:
            Dict cu status, deviații, și detalii de analiză.
        """
        result: Dict[str, Any] = {
            "status": "date_insuficiente",
            "alerts": [],
        }

        # Derivăm consumul din meter_read_history (index deltas)
        readings = get_data_list(self._data.get("meter_read_history"))
        if not readings or len(readings) < 2:
            return result

        # Sortăm citirile cronologic (cele mai recente primele)
        dated_readings = []
        for r in readings:
            dt = parse_date(r.get("Date"))
            idx = safe_float(r.get("Index"))
            if dt and idx > 0:
                dated_readings.append({"date": dt, "index": idx})

        dated_readings.sort(key=lambda x: x["date"], reverse=True)

        if len(dated_readings) < 2:
            return result

        # Calculăm consumul per interval (delta index între citiri consecutive)
        monthly_data = []
        for i in range(len(dated_readings) - 1):
            newer = dated_readings[i]
            older = dated_readings[i + 1]
            delta = newer["index"] - older["index"]
            if delta >= 0:
                monthly_data.append(
                    {
                        "consumption": delta,
                        "month": newer["date"].strftime("%m/%Y"),
                        "date": newer["date"],
                    }
                )

        if len(monthly_data) < 2:
            return result

        current = monthly_data[0]["consumption"]
        alerts = []

        # Analiză 1: Comparație cu media ultimelor 3 luni
        recent = monthly_data[1:4]  # excludem luna curentă
        if recent:
            avg_recent = sum(m["consumption"] for m in recent) / len(recent)
            if avg_recent > 0:
                deviation_pct = ((current - avg_recent) / avg_recent) * 100
                result["deviatie_vs_medie"] = round(deviation_pct, 1)
                result["consum_curent"] = current
                result["consum_mediu_recent"] = round(avg_recent, 2)

                if deviation_pct > 30:
                    alerts.append(
                        f"Consum cu {deviation_pct:.0f}% peste media recentă"
                    )
                elif deviation_pct > 20:
                    alerts.append(
                        f"Consum ușor ridicat (+{deviation_pct:.0f}% vs medie)"
                    )
                elif deviation_pct < -30:
                    alerts.append(
                        f"Consum cu {abs(deviation_pct):.0f}% sub media recentă"
                    )
                elif deviation_pct < -20:
                    alerts.append(
                        f"Consum ușor scăzut ({deviation_pct:.0f}% vs medie)"
                    )

        # Analiză 2: Comparație Year-over-Year (aceeași lună anul trecut)
        # Căutăm un interval cu dată similară (~12 luni în urmă)
        current_date = monthly_data[0].get("date")
        current_month_num = current_date.month if current_date else None
        yoy_match = None
        if current_month_num and current_date:
            for item in monthly_data[1:]:
                item_date = item.get("date")
                if item_date and item_date.month == current_month_num:
                    # Verificăm ca diferența să fie ~12 luni (10-14)
                    months_diff = (current_date.year - item_date.year) * 12 + (
                        current_date.month - item_date.month
                    )
                    if 10 <= months_diff <= 14:
                        yoy_match = item
                        break

        if yoy_match:
            yoy_consumption = yoy_match["consumption"]
            if yoy_consumption > 0:
                yoy_deviation = (
                    (current - yoy_consumption) / yoy_consumption
                ) * 100
                result["deviatie_yoy"] = round(yoy_deviation, 1)
                result["consum_an_trecut"] = yoy_consumption

                if yoy_deviation > 30:
                    alerts.append(
                        f"Consum cu {yoy_deviation:.0f}% peste aceeași lună anul trecut"
                    )
                elif yoy_deviation > 20:
                    alerts.append(
                        f"Consum ușor ridicat vs anul trecut (+{yoy_deviation:.0f}%)"
                    )
                elif yoy_deviation < -30:
                    alerts.append(
                        f"Consum cu {abs(yoy_deviation):.0f}% sub aceeași lună anul trecut"
                    )

        # Determinăm statusul final
        result["alerts"] = alerts
        if not alerts:
            result["status"] = "normal"
        elif any("peste" in a and "30" in a for a in alerts):
            result["status"] = "anomalie"
        elif any("ridicat" in a for a in alerts):
            result["status"] = "consum_ridicat"
        elif any("scăzut" in a or "sub" in a for a in alerts):
            result["status"] = "consum_scazut"
        else:
            result["status"] = "normal"

        return result

    @property
    def native_value(self) -> Optional[str]:
        analysis = self._analyze_consumption()
        return analysis.get("status")

    @property
    def icon(self) -> str:
        """Pictogramă dinamică în funcție de stare."""
        status = self.native_value
        if status == "anomalie":
            return "mdi:alert-octagon"
        elif status == "consum_ridicat":
            return "mdi:arrow-up-bold"
        elif status == "consum_scazut":
            return "mdi:arrow-down-bold"
        return "mdi:check-circle"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        analysis = self._analyze_consumption()
        attrs: Dict[str, Any] = {
            ATTR_UTILITY_ACCOUNT_NUMBER: self._uan,
            ATTR_ACCOUNT_NUMBER: self._an,
        }

        if analysis.get("consum_curent"):
            attrs["consum_curent"] = (
                format_number_ro(analysis["consum_curent"]) + " kWh"
            )
        if analysis.get("consum_mediu_recent"):
            attrs["consum_mediu_recent"] = (
                format_number_ro(analysis["consum_mediu_recent"]) + " kWh"
            )
        if analysis.get("deviatie_vs_medie") is not None:
            dev = analysis["deviatie_vs_medie"]
            attrs["deviatie_vs_medie"] = f"{dev:+.1f}%"
        if analysis.get("consum_an_trecut"):
            attrs["consum_an_trecut"] = (
                format_number_ro(analysis["consum_an_trecut"]) + " kWh"
            )
        if analysis.get("deviatie_yoy") is not None:
            dev = analysis["deviatie_yoy"]
            attrs["deviatie_an_trecut"] = f"{dev:+.1f}%"
        if analysis.get("alerts"):
            attrs["alerte"] = analysis["alerts"]
        else:
            attrs["alerte"] = ["Nicio anomalie detectată"]

        return attrs


# =============================================================================
# Citire Permisă (Da / Nu)
# =============================================================================


class IhidroCitirePermisaSensor(IhidroBaseSensor):
    """Senzor: Fereastra de autocitire este deschisă (Da/Nu).

    Afișează "Da" dacă fereastra de autocitire este deschisă, "Nu" altfel.
    """

    _attr_icon = "mdi:calendar-check"

    def __init__(
        self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Citire Permisă"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_citire_permisa"

    @property
    def native_value(self) -> Optional[str]:
        """Returnează 'Da' sau 'Nu'."""
        window_data = self._data.get("meter_window")
        if not window_data:
            return None
        return "Da" if is_reading_window_open(window_data) else "Nu"

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


# =============================================================================
# Sold Factură (Plătit / Neplătit / Credit) — migrat din binary_sensor.py
# =============================================================================


class IhidroSoldFacturaSensor(IhidroBaseSensor):
    """Senzor text: Starea plății facturii curente.

    Afișează starea clară în română:
    - "Plătit" — sold = 0
    - "Neplătit" — sold > 0
    - "Credit" — sold < 0 (supraplatit)

    Migrat din IhidroSoldFacturaBinarySensor (care afișa doar "On"/"Off").
    Păstrează același unique_id pentru a nu pierde istoricul.
    """

    _attr_icon = "mdi:check-decagram"

    def __init__(self, coordinator: IhidroAccountCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Sold Factură"
        self._attr_unique_id = f"{entry.entry_id}_{self._uan}_sold_factura"

    @property
    def native_value(self) -> Optional[str]:
        """Returnează 'Plătit', 'Neplătit' sau 'Credit'."""
        bill = get_current_bill_data(self._data.get("current_bill"))
        if not bill:
            return None
        amount = safe_float(bill.get("rembalance") or bill.get("billamount"))
        if amount < 0:
            return "Credit"
        elif amount == 0:
            return "Plătit"
        else:
            return "Neplătit"

    @property
    def icon(self) -> str:
        """Pictogramă dinamică în funcție de stare."""
        status = self.native_value
        if status == "Plătit":
            return "mdi:check-decagram"
        elif status == "Credit":
            return "mdi:cash-plus"
        elif status == "Neplătit":
            return "mdi:alert-circle-outline"
        return "mdi:help-circle"

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
            attrs[ATTR_DUE_DATE] = format_date_ro(bill.get("duedate"))
        return attrs
