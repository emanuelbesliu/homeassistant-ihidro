"""Diagnostics support pentru integrarea iHidro.

Oferă un dump complet al datelor coordinatorilor (anonimizat)
pentru troubleshooting. Accesibil din:
- HA Settings → Integrations → iHidro → Diagnostics
- /api/diagnostics/config_entry/{entry_id}

Secțiuni incluse:
- config_entry: configurare curentă (fără credențiale)
- api: starea sesiunii API
- energy_sensor: starea senzorului de energie extern (dacă configurat)
- coordinators: per POD/UAN:
  - coordinator_state: refresh count, interval, last success
  - endpoints_summary: rezumat util al fiecărui endpoint API
  - sensor_states: snapshot al tuturor entităților (valoare + atribute cheie)
  - computed_values: valori derivate (index live, consum lunar/zilnic, tarif)
  - raw_data: date API complete (anonimizate, fără noise)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_ENERGY_SENSOR
from .helpers import (
    anonymize_data,
    safe_float,
    format_ron,
    format_date_ro,
    parse_date,
    get_current_bill_data,
    get_bill_history_list,
    get_data_list,
    get_data_dict,
    get_meter_window_info,
    get_meter_index_cascading,
    get_tentative_data,
    is_reading_window_open,
    is_prosumer,
)

_LOGGER = logging.getLogger(__name__)

# Chei care produc zgomot în raw_data (null, zero-value, color codes, etc.)
_NOISE_KEYS = {
    # Zero-value boilerplate din bill_history / payment_history
    "BillingDataBaseDate",
    "BillingDate",
    "BillAmountThisPeriod",
    "DisplayBillAmountThisPeriod",
    "BillingDueDate",
    "DocType",
    "TransactionDataBaseDate",
    "TransactionDate",
    "TransactionAmount",
    "TransactionAmountVal",
    "TransactionStatus",
    "PowerAmount",
    "PowerAmountVal",
    "GroupId",
    "paymenttype",
    "paymenttypeid",
    "type",
    "status",
    # Color codes din daily_usage / usage_history
    "SoFarColorCode",
    "ExpectedUsageColorCode",
    "PeakLoadColorCode",
    "LoadFactorColorCode",
    "AverageColorCode",
    "HighestColorCode",
    "LowColor",
    "MidColor",
    "HighColor",
    "WaterAllocationColor",
    "SolarGenerationColor",
    "ComparePreviousColor",
    "CompareUtilityColor",
    "CompareCurrentColor",
    "CompareZipAllocationColor",
    "IsLastUsages",
    "DisplayMonth",
    # Alte câmpuri fără valoare informativă
    "objResponseProxy",
    "Table1",
    "MessageCode",
    "Skey",
    "UpToDecimalPlaces",
    "Min",
    "Mid",
    "Max",
    "PeakLoad",
    "LoadFactor",
}


def _strip_noise(data: Any) -> Any:
    """Elimină câmpuri cu zgomot din datele API (null, zero-value, color codes).

    Recursiv pe dict/list. Elimină și valorile None/null din dict-uri.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in _NOISE_KEYS:
                continue
            cleaned = _strip_noise(value)
            # Păstrăm None doar pentru câmpuri care ar trebui să aibă date
            # dar nu le au (e informativ)
            if cleaned is not None or key in (
                "net_usage",
                "generation_data",
                "MeterCheckIsAMI",
            ):
                result[key] = cleaned
        return result if result else None
    elif isinstance(data, list):
        cleaned_list = [_strip_noise(item) for item in data]
        return [item for item in cleaned_list if item is not None] or None
    return data


def _build_endpoints_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """Construiește rezumate utile pentru fiecare endpoint API.

    În loc de detecție generică pe Table (care nu funcționa), fiecare
    endpoint primește un rezumat specific structurii sale reale.
    """
    summary: Dict[str, Any] = {}

    # --- current_bill ---
    bill = get_current_bill_data(data.get("current_bill"))
    if bill:
        amount = safe_float(bill.get("rembalance") or bill.get("billamount"))
        summary["current_bill"] = {
            "status": "ok",
            "billamount": bill.get("billamount"),
            "rembalance": bill.get("rembalance"),
            "duedate": format_date_ro(bill.get("duedate")),
            "paid": amount <= 0,
        }
    else:
        summary["current_bill"] = {"status": "null_or_empty"}

    # --- meter_window ---
    window_data = data.get("meter_window")
    window = get_meter_window_info(window_data)
    if window:
        summary["meter_window"] = {
            "status": "ok",
            "is_window_open": is_reading_window_open(window_data),
            "opening_date": window.get("OpeningDate"),
            "closing_date": window.get("ClosingDate"),
            "next_opening": window.get("NextMonthOpeningDate"),
            "next_closing": window.get("NextMonthClosingDate"),
        }
    else:
        summary["meter_window"] = {"status": "null_or_empty"}

    # --- pods ---
    pods = get_data_list(data.get("pods"))
    if pods:
        summary["pods"] = {
            "status": "ok",
            "count": len(pods),
            "pod_ids": [p.get("pod", "?") for p in pods],
        }
    else:
        summary["pods"] = {"status": "null_or_empty"}

    # --- meter_details ---
    md_raw = data.get("meter_details")
    if md_raw and isinstance(md_raw, dict):
        result = md_raw.get("result", {})
        details = result.get("MeterDetails", [])
        summary["meter_details"] = {
            "status": "ok" if details else "empty",
            "meter_count": len(details) if details else 0,
            "is_ami": result.get("MeterCheckIsAMI"),
        }
    else:
        summary["meter_details"] = {"status": "null"}

    # --- bill_history ---
    bills_list = get_bill_history_list(data.get("bill_history"))
    if bills_list:
        summary["bill_history"] = {
            "status": "ok",
            "bill_count": len(bills_list),
            "latest_bill": {
                "amount": bills_list[-1].get("amount") if bills_list else None,
                "date": bills_list[-1].get("invoiceDate") if bills_list else None,
                "type": bills_list[-1].get("invoiceType") if bills_list else None,
            },
        }
        # Plăți
        bh_raw = data.get("bill_history")
        if bh_raw and isinstance(bh_raw, dict):
            payments = (
                bh_raw.get("result", {}).get("objBillingPaymentHistoryEntity") or []
            )
            summary["bill_history"]["payment_count"] = len(payments)
            if payments:
                summary["bill_history"]["latest_payment"] = {
                    "amount": payments[0].get("amount"),
                    "date": payments[0].get("paymentDate"),
                    "channel": payments[0].get("channel"),
                }
    else:
        summary["bill_history"] = {"status": "null_or_empty"}

    # --- meter_read_history ---
    readings = get_data_list(data.get("meter_read_history"))
    if readings:
        summary["meter_read_history"] = {
            "status": "ok",
            "reading_count": len(readings),
            "readings": [
                {
                    "index": r.get("Index"),
                    "date": r.get("Date"),
                    "type": r.get("ReadingType"),
                }
                for r in readings
            ],
        }
    else:
        summary["meter_read_history"] = {"status": "null_or_empty"}

    # --- meter_counter_series ---
    mcs = get_data_list(data.get("meter_counter_series"))
    if mcs:
        entry = mcs[0] if mcs else {}
        summary["meter_counter_series"] = {
            "status": "ok",
            "index_values": entry.get("Index"),
            "last_read_date": entry.get("MrDate"),
        }
    else:
        summary["meter_counter_series"] = {"status": "null_or_empty"}

    # --- previous_meter_read ---
    pmr = get_data_list(data.get("previous_meter_read"))
    if pmr:
        entry = pmr[0] if pmr else {}
        summary["previous_meter_read"] = {
            "status": "ok",
            "prev_index": entry.get("prevMRResult"),
            "prev_date": entry.get("prevMRDate"),
            "register": entry.get("registerCat"),
            "distributor": entry.get("distributor"),
            "meter_interval": entry.get("meterInterval"),
            "uom": entry.get("uom"),
        }
    else:
        summary["previous_meter_read"] = {"status": "null_or_empty"}

    # --- daily_usage ---
    tentative = get_tentative_data(data.get("daily_usage"))
    if tentative:
        summary["daily_usage"] = {
            "status": "ok",
            "so_far": tentative.get("SoFar"),
            "expected": tentative.get("ExpectedUsage"),
            "average": tentative.get("Average"),
            "highest": tentative.get("Highest"),
            "is_ami": tentative.get("IsOnlyAMI"),
            "usage_cycle": tentative.get("UsageCycle"),
        }
    else:
        summary["daily_usage"] = {"status": "null_or_empty"}

    # --- usage_history ---
    uh = data.get("usage_history")
    if uh and isinstance(uh, dict):
        uh_data = uh.get("result", {}).get("Data", {})
        has_data = any(
            v is not None
            for k, v in (uh_data or {}).items()
            if k.startswith("obj") or k == "getTentativeData"
        )
        summary["usage_history"] = {
            "status": "ok" if has_data else "all_null",
        }
    else:
        summary["usage_history"] = {"status": "null"}

    # --- generation_data ---
    gd = data.get("generation_data")
    if gd and isinstance(gd, dict):
        gd_data = gd.get("result", {}).get("Data", {})
        has_data = any(v is not None for v in (gd_data or {}).values())
        summary["generation_data"] = {
            "status": "has_data" if has_data else "all_null (not prosumer)",
        }
    else:
        summary["generation_data"] = {"status": "null"}

    # --- net_usage ---
    nu = data.get("net_usage")
    summary["net_usage"] = {
        "status": "has_data" if nu else "null (not prosumer or error)",
    }

    # --- master_data_status ---
    mds = get_data_list(data.get("master_data_status"))
    if mds:
        summary["master_data_status"] = {
            "status": "ok",
            "service_count": len(mds),
        }
    else:
        summary["master_data_status"] = {"status": "null_or_empty"}

    return summary


def _build_computed_values(
    data: Dict[str, Any], active_meter: Optional[str]
) -> Dict[str, Any]:
    """Calculează valorile derivate pe care senzorii le afișează.

    Util pentru verificare: dacă un senzor arată Unknown dar computed_values
    arată valoarea corectă, problema e în senzor. Dacă ambele sunt None,
    problema e în date.
    """
    computed: Dict[str, Any] = {}

    # Index contor (cascading)
    last_index, index_source = get_meter_index_cascading(
        data, register="1.8.0", active_meter=active_meter
    )
    computed["meter_index"] = last_index
    computed["meter_index_source"] = index_source

    # Factură curentă
    bill = get_current_bill_data(data.get("current_bill"))
    if bill:
        computed["current_bill_amount"] = safe_float(
            bill.get("rembalance") or bill.get("billamount")
        )
        due_str = bill.get("duedate")
        if due_str:
            due_dt = parse_date(due_str)
            if due_dt:
                days = (due_dt.date() - datetime.now().date()).days
                computed["days_until_due"] = days
                computed["is_paid"] = computed["current_bill_amount"] <= 0

    # Meter read history — lista indexilor
    readings = get_data_list(data.get("meter_read_history"))
    if readings:
        indices = [r.get("Index") for r in readings if r.get("Index") is not None]
        computed["meter_read_indices"] = indices
        if len(indices) >= 2:
            # Consum lunar bazat pe ultimele 2 citiri pozitive
            for i in range(len(indices) - 1, 0, -1):
                delta = indices[i] - indices[i - 1]
                if delta > 0:
                    computed["last_positive_delta"] = delta
                    computed["delta_pair"] = f"{indices[i-1]} → {indices[i]}"
                    break

    # Fereastra de citire
    window_data = data.get("meter_window")
    computed["is_window_open"] = is_reading_window_open(window_data)

    # Tentative data (AMI)
    tentative = get_tentative_data(data.get("daily_usage"))
    if tentative:
        computed["tentative_so_far"] = tentative.get("SoFar")
        computed["tentative_is_ami"] = tentative.get("IsOnlyAMI")

    # Bill history — medie ultimele 3
    bills_list = get_bill_history_list(data.get("bill_history"))
    if bills_list:
        amounts = []
        for b in bills_list:
            a = safe_float(b.get("amount"))
            if a > 0:
                amounts.append(a)
        if amounts:
            last_3 = amounts[-3:] if len(amounts) >= 3 else amounts
            computed["avg_last_3_bills"] = round(sum(last_3) / len(last_3), 2)
            computed["bill_count_positive"] = len(amounts)

    # Prosumer
    computed["is_prosumer"] = is_prosumer(data.get("meter_read_history"))

    return computed


def _build_sensor_states(
    hass: HomeAssistant, entry: ConfigEntry, uan: str
) -> List[Dict[str, Any]]:
    """Capturează starea curentă a tuturor entităților iHidro pentru un UAN.

    Iterează prin entity registry și citește starea live din HA.
    """
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    states: List[Dict[str, Any]] = []

    # Găsim toate entitățile care aparțin acestui config entry
    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        # Filtrăm doar entitățile care conțin UAN-ul curent în unique_id
        if uan not in (entity_entry.unique_id or ""):
            continue

        state_obj = hass.states.get(entity_entry.entity_id)
        entity_info: Dict[str, Any] = {
            "entity_id": entity_entry.entity_id,
            "platform": entity_entry.domain,
            "name": entity_entry.name or entity_entry.original_name,
            "state": state_obj.state if state_obj else "not_loaded",
        }

        # Adăugăm atributele cheie (fără cele generice)
        if state_obj and state_obj.attributes:
            key_attrs = {}
            skip_keys = {
                "attribution",
                "friendly_name",
                "icon",
                "unit_of_measurement",
                "device_class",
                "state_class",
            }
            for attr_key, attr_val in state_obj.attributes.items():
                if attr_key not in skip_keys:
                    key_attrs[attr_key] = attr_val
            if key_attrs:
                entity_info["attributes"] = key_attrs

        states.append(entity_info)

    # Sortăm: sensors primul, apoi switch, number, button
    platform_order = {"sensor": 0, "switch": 1, "number": 2, "button": 3}
    states.sort(key=lambda s: (platform_order.get(s["platform"], 9), s["entity_id"]))

    return states


def _build_energy_sensor_info(
    hass: HomeAssistant, entry: ConfigEntry
) -> Optional[Dict[str, Any]]:
    """Informații despre senzorul de energie extern configurat."""
    energy_sensor_id = entry.options.get(CONF_ENERGY_SENSOR, "")
    if not energy_sensor_id:
        return {"configured": False}

    info: Dict[str, Any] = {
        "configured": True,
        "entity_id": energy_sensor_id,
    }

    state_obj = hass.states.get(energy_sensor_id)
    if state_obj is None:
        info["status"] = "not_found"
        return info

    info["status"] = state_obj.state
    if state_obj.state not in ("unavailable", "unknown"):
        try:
            info["value_kwh"] = float(state_obj.state)
        except (ValueError, TypeError):
            info["value_kwh"] = None
            info["parse_error"] = f"Cannot parse '{state_obj.state}' as float"

    info["unit"] = state_obj.attributes.get("unit_of_measurement")
    info["device_class"] = state_obj.attributes.get("device_class")
    info["state_class"] = state_obj.attributes.get("state_class")

    return info


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """Returnează date de diagnosticare pentru config entry.

    Datele sunt anonimizate automat: UAN-uri, adrese, nume, contracte,
    POD-uri, numere de serie sunt parțial mascate.
    """
    from . import IhidroRuntimeData

    runtime_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    result: Dict[str, Any] = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "version": entry.version,
            "source": entry.source,
            "data": anonymize_data(
                {
                    k: v
                    for k, v in entry.data.items()
                    if k not in ("password", "token_session")
                }
            ),
            "options": dict(entry.options),
        },
    }

    if not isinstance(runtime_data, IhidroRuntimeData):
        result["error"] = "Runtime data not available or wrong type"
        return result

    # API state
    api = runtime_data.api
    result["api"] = {
        "has_session_token": api._session_token is not None,
        "user_id": (
            anonymize_data({"v": api._user_id}).get("v") if api._user_id else None
        ),
        "accounts_count": len(api.get_utility_accounts()),
    }

    # Energy sensor info
    result["energy_sensor"] = _build_energy_sensor_info(hass, entry)

    # Coordinator data (per UAN)
    coordinators_data: Dict[str, Any] = {}
    for uan, coordinator in runtime_data.coordinators.items():
        anon_uan = anonymize_data({"v": uan}).get("v", uan)

        coord_info: Dict[str, Any] = {}

        # --- Coordinator state ---
        coord_info["coordinator_state"] = {
            "uan": anon_uan,
            "active_meter": coordinator.active_meter,
            "refresh_count": coordinator._refresh_count,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "last_update_success": coordinator.last_update_success,
            "last_update": (
                coordinator.data.get("last_update") if coordinator.data else None
            ),
            "is_heavy_refresh": (
                coordinator.data.get("is_heavy_refresh") if coordinator.data else None
            ),
            "data_keys": list(coordinator.data.keys()) if coordinator.data else [],
        }

        if coordinator.data:
            data = coordinator.data

            # --- Endpoints summary (structure-aware) ---
            coord_info["endpoints_summary"] = _build_endpoints_summary(data)

            # --- Computed values ---
            coord_info["computed_values"] = _build_computed_values(
                data, coordinator.active_meter
            )

            # --- Sensor states snapshot ---
            coord_info["sensor_states"] = _build_sensor_states(hass, entry, uan)

            # --- Raw data (anonimizat + fără noise) ---
            stripped = _strip_noise(data)
            coord_info["raw_data"] = anonymize_data(stripped)
        else:
            coord_info["endpoints_summary"] = {}
            coord_info["computed_values"] = {}
            coord_info["sensor_states"] = []
            coord_info["raw_data"] = None

        coordinators_data[anon_uan] = coord_info

    result["coordinators"] = coordinators_data
    result["coordinators_count"] = len(runtime_data.coordinators)

    return result
