"""Diagnostics support pentru integrarea iHidro.

Oferă un dump complet al datelor coordinatorilor (anonimizat)
pentru troubleshooting. Accesibil din:
- HA Settings → Integrations → iHidro → Diagnostics
- /api/diagnostics/config_entry/{entry_id}
"""

import logging
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .helpers import anonymize_data

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """Returnează date de diagnosticare pentru config entry.

    Datele sunt anonimizate automat: UAN-uri, adrese, nume, contracte
    sunt parțial mascate.
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
        "user_id": anonymize_data({"v": api._user_id}).get("v") if api._user_id else None,
        "accounts_count": len(api.get_utility_accounts()),
    }

    # Coordinator data (per UAN)
    coordinators_data: Dict[str, Any] = {}
    for uan, coordinator in runtime_data.coordinators.items():
        anon_uan = anonymize_data({"v": uan}).get("v", uan)
        coord_info: Dict[str, Any] = {
            "uan": anon_uan,
            "active_meter": coordinator.active_meter,
            "refresh_count": coordinator._refresh_count,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "last_update_success": coordinator.last_update_success,
        }

        if coordinator.data:
            data = coordinator.data
            coord_info["data_keys"] = list(data.keys())
            coord_info["last_update"] = data.get("last_update")
            coord_info["is_heavy_refresh"] = data.get("is_heavy_refresh")

            # Rezumat al fiecărui endpoint
            endpoints_summary: Dict[str, Any] = {}
            for key in (
                "current_bill",
                "meter_details",
                "meter_window",
                "pods",
                "master_data_status",
                "bill_history",
                "payment_history",
                "usage_history",
                "meter_read_history",
                "meter_counter_series",
                "previous_meter_read",
            ):
                value = data.get(key)
                if value is None:
                    endpoints_summary[key] = {"status": "null"}
                elif isinstance(value, dict):
                    # Extragem Table count fără date sensibile
                    result_data = value.get("result", {}).get("Data", {})
                    tables = {}
                    for table_key, table_val in result_data.items():
                        if isinstance(table_val, list):
                            tables[table_key] = {
                                "count": len(table_val),
                                "sample_keys": (
                                    list(table_val[0].keys()) if table_val else []
                                ),
                            }
                    endpoints_summary[key] = {
                        "status": "ok",
                        "tables": tables,
                    }
                else:
                    endpoints_summary[key] = {"status": "unexpected_type"}

            coord_info["endpoints"] = endpoints_summary

            # Anonimizăm datele complete dar includem structura
            coord_info["raw_data"] = anonymize_data(data)
        else:
            coord_info["data_keys"] = []
            coord_info["raw_data"] = None

        coordinators_data[anon_uan] = coord_info

    result["coordinators"] = coordinators_data
    result["coordinators_count"] = len(runtime_data.coordinators)

    return result
