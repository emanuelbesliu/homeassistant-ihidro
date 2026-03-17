"""Data Update Coordinator pentru iHidro.

Implementează:
- Un coordinator per cont (UAN) — nu un singur coordinator global
- Refresh în 3 faze:
  - Faza 1 (paralel): endpoint-uri independente (bill, meter, window, pods, master_data)
  - Faza 2 (secvențial): endpoint-uri dependente de pods (previous_meter_read)
  - Heavy refresh (la fiecare al 4-lea ciclu): billing history, usage, counter series,
    meter read history (cele din urmă 2 necesită InstallationNumber + podValue din GetPods)
- Paralelism cu asyncio.gather() pentru apeluri API independente
- Token persistence (export/import la fiecare refresh)
- Detectare evenimente (fereastră citire, facturi noi, restanțe) cu bus events
- Active counter series detection

Notă: GetPaymentHistory NU există ca endpoint separat.
Datele de plată sunt incluse în răspunsul GetBillingHistoryList
(câmpul objBillingPaymentHistoryEntity).
"""

import asyncio
import logging
from datetime import timedelta, datetime
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import IhidroAPI, IhidroApiError, IhidroAuthError
from .const import (
    DOMAIN,
    CONF_UPDATE_INTERVAL,
    CONF_TOKEN_USER_ID,
    CONF_TOKEN_SESSION,
    DEFAULT_UPDATE_INTERVAL,
    HEAVY_REFRESH_EVERY,
    EVENT_READING_WINDOW_OPENED,
    EVENT_READING_WINDOW_CLOSED,
    EVENT_NEW_BILL,
    EVENT_OVERDUE_BILL,
)
from .helpers import (
    safe_float,
    get_active_counter_series,
    is_reading_window_open,
    parse_date,
    get_meter_window_info,
    get_current_bill_data,
)

_LOGGER = logging.getLogger(__name__)


class IhidroAccountCoordinator(DataUpdateCoordinator):
    """Coordinator per cont (UAN) pentru actualizarea datelor iHidro.

    Fiecare instanță gestionează un singur POD/UAN.
    Faza 1 (paralel): factura curentă, detalii contor, fereastră citire, pods, master data.
    Faza 2 (secvențial): previous_meter_read (necesită pods).
    Heavy refresh (la fiecare al N-lea ciclu): istoric facturi, consum,
    meter read history, counter series (cele din urmă necesită pods).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: IhidroAPI,
        entry: ConfigEntry,
        account_info: Dict[str, Any],
    ) -> None:
        """Inițializare coordinator per cont."""
        self.entry = entry
        self.api = api
        self.account_info = account_info
        self.uan = account_info["UtilityAccountNumber"]
        self.an = account_info["AccountNumber"]

        # Contor pentru heavy refresh
        self._refresh_count = 0

        # Stare anterioară pentru detectarea evenimentelor
        self._prev_window_open: Optional[bool] = None
        self._prev_bill_number: Optional[str] = None
        self._prev_overdue: Optional[bool] = None

        # Seria activă de contorizare (detectată automat)
        self.active_meter: Optional[str] = None

        # Intervalul de actualizare
        update_interval = entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.uan}",
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Actualizează datele de la API pentru acest cont.

        Strategia de refresh în 2 faze:
        - Faza 1 (paralel, fără dependențe): current_bill, meter_details,
          meter_window, pods, master_data_status
        - Faza 2 (depinde de pods): get_previous_meter_read (necesită
          InstallationNumber, podValue, customerNumber din GetPods)
        - Heavy refresh (la fiecare al N-lea ciclu): bill_history, usage,
          meter_read_history, meter_counter_series (cele din urmă 2
          necesită InstallationNumber + podValue din GetPods)

        Notă: GetPaymentHistory NU există ca endpoint separat.
        Datele de plată sunt incluse în răspunsul GetBillingHistoryList.
        """
        try:
            # Asigurăm autentificarea
            await self.api.login_if_needed()

            self._refresh_count += 1
            is_heavy = (self._refresh_count % HEAVY_REFRESH_EVERY) == 1

            _LOGGER.debug(
                "iHidro Coordinator [%s]: Refresh #%d (%s)",
                self.uan,
                self._refresh_count,
                "HEAVY" if is_heavy else "light",
            )

            # Structura de date
            data: Dict[str, Any] = {
                "account_info": self.account_info,
                "current_bill": None,
                "meter_details": None,
                "meter_window": None,
                "pods": None,
                "master_data_status": None,
                # Heavy refresh only
                "bill_history": None,
                "usage_history": None,
                "daily_usage": None,
                "generation_data": None,
                "net_usage": None,
                "meter_read_history": None,
                "meter_counter_series": None,
                "previous_meter_read": None,
                # Meta
                "last_update": datetime.now().isoformat(),
                "is_heavy_refresh": is_heavy,
                "active_meter": self.active_meter,
            }

            # Păstrăm datele heavy din ciclul anterior dacă nu facem heavy refresh
            if not is_heavy and self.data:
                for key in (
                    "bill_history",
                    "usage_history",
                    "daily_usage",
                    "generation_data",
                    "net_usage",
                    "meter_read_history",
                    "meter_counter_series",
                    "previous_meter_read",
                ):
                    data[key] = self.data.get(key)

            # =============================================================
            # Faza 1: Endpoint-uri independente (paralel)
            # =============================================================
            phase1_tasks = {
                "current_bill": self.api.get_current_bill(self.uan, self.an),
                "meter_details": self.api.get_multi_meter_details(self.uan, self.an),
                "meter_window": self.api.get_window_dates(self.uan, self.an),
                "pods": self.api.get_pods(self.uan, self.an),
                "master_data_status": self.api.get_master_data_status(),
            }

            keys1 = list(phase1_tasks.keys())
            results1 = await asyncio.gather(
                *phase1_tasks.values(), return_exceptions=True
            )

            for key, result in zip(keys1, results1):
                if isinstance(result, Exception):
                    _LOGGER.warning(
                        "Eroare la %s pentru POD %s: %s", key, self.uan, result
                    )
                    if self.data and key in self.data:
                        data[key] = self.data[key]
                else:
                    data[key] = result

            # =============================================================
            # Extragere InstallationNumber / podValue / customerNumber
            # din GetPods (necesare pentru faza 2 și heavy refresh)
            # =============================================================
            installation_number = ""
            pod_value = ""
            customer_number = ""

            pods_resp = data.get("pods")
            if pods_resp and isinstance(pods_resp, dict):
                pods_data = pods_resp.get("result", {})
                if isinstance(pods_data, dict):
                    pods_data = pods_data.get("Data", [])
                if isinstance(pods_data, list) and pods_data:
                    first_pod = pods_data[0]
                    installation_number = str(
                        first_pod.get("installation",
                                      first_pod.get("InstallationNumber", ""))
                    )
                    pod_value = str(
                        first_pod.get("pod",
                                      first_pod.get("podValue", ""))
                    )
                    customer_number = str(
                        first_pod.get("accountID", "")
                    )

            _LOGGER.debug(
                "iHidro [%s]: Pods extras: installation='%s', pod='%s', "
                "customerNumber='%s'.",
                self.uan, installation_number, pod_value, customer_number,
            )

            # =============================================================
            # Faza 2: GetPreviousMeterRead (depinde de pods)
            # Returnează None dacă fereastra este închisă (HTTP 400)
            # =============================================================
            try:
                prev_read = await self.api.get_previous_meter_read(
                    utility_account_number=self.uan,
                    installation_number=installation_number,
                    pod_value=pod_value,
                    customer_number=customer_number,
                )
                data["previous_meter_read"] = prev_read
            except Exception as err:
                _LOGGER.warning(
                    "Eroare la previous_meter_read pentru POD %s: %s",
                    self.uan, err,
                )
                if self.data and "previous_meter_read" in self.data:
                    data["previous_meter_read"] = self.data["previous_meter_read"]

            # =============================================================
            # Heavy refresh (la fiecare al N-lea ciclu)
            # =============================================================
            if is_heavy:
                to_date = datetime.now()
                from_date = to_date.replace(year=to_date.year - 1)
                from_str = from_date.strftime("%m/%d/%Y")
                to_str = to_date.strftime("%m/%d/%Y")

                if not installation_number or not pod_value:
                    _LOGGER.warning(
                        "iHidro [%s]: InstallationNumber/podValue GOALE! "
                        "GetMeterCounterSeries și GetMeterReadHistory "
                        "vor probabil eșua.",
                        self.uan,
                    )

                heavy_tasks = {
                    "bill_history": self.api.get_bill_history(
                        self.uan, self.an, from_str, to_str
                    ),
                    "usage_history": self.api.get_usage_generation(self.uan, self.an),
                    "daily_usage": self.api.get_daily_usage(self.uan, self.an),
                    "generation_data": self.api.get_generation_data(self.uan, self.an),
                    "net_usage": self.api.get_net_usage(self.uan, self.an),
                    "meter_counter_series": self.api.get_meter_counter_series(
                        self.uan, installation_number, pod_value
                    ),
                    "meter_read_history": self.api.get_meter_read_history(
                        self.uan, installation_number, pod_value
                    ),
                }

                keys_h = list(heavy_tasks.keys())
                results_h = await asyncio.gather(
                    *heavy_tasks.values(), return_exceptions=True
                )

                for key, result in zip(keys_h, results_h):
                    if isinstance(result, Exception):
                        _LOGGER.warning(
                            "Eroare la %s pentru POD %s: %s", key, self.uan, result
                        )
                        if self.data and key in self.data:
                            data[key] = self.data[key]
                    else:
                        data[key] = result

            # Detectăm seria activă de contorizare (din heavy data)
            if data.get("meter_counter_series"):
                active = get_active_counter_series(data["meter_counter_series"])
                if active:
                    self.active_meter = active
                    data["active_meter"] = active

            # Detectăm și emitem evenimente
            self._detect_and_fire_events(data)

            # Persistăm token-urile după un refresh reușit
            await self._persist_tokens()

            _LOGGER.debug(
                "iHidro Coordinator [%s]: Refresh completat cu succes", self.uan
            )
            return data

        except IhidroAuthError as err:
            _LOGGER.error("Eroare autentificare iHidro [%s]: %s", self.uan, err)
            # Trigger reauth flow
            self.entry.async_start_reauth(self.hass)
            raise UpdateFailed(f"Eroare autentificare: {err}") from err
        except IhidroApiError as err:
            _LOGGER.error("Eroare API iHidro [%s]: %s", self.uan, err)
            raise UpdateFailed(f"Eroare API: {err}") from err
        except Exception as err:
            _LOGGER.error(
                "Eroare neașteptată la actualizarea datelor iHidro [%s]: %s",
                self.uan,
                err,
            )
            raise UpdateFailed(f"Eroare la actualizarea datelor: {err}") from err

    def _detect_and_fire_events(self, data: Dict[str, Any]) -> None:
        """Detectează schimbări de stare și emite evenimente pe bus-ul HA.

        Pe lângă evenimentele de bus (pentru automatizări), creează și
        notificări persistente (Phase L) pentru vizibilitate imediată.
        """
        event_data_base = {
            "utility_account_number": self.uan,
            "account_number": self.an,
        }

        # 1. Fereastră autocitire: deschisă / închisă
        window_data = data.get("meter_window")
        current_window_open = is_reading_window_open(window_data)

        if self._prev_window_open is not None:
            if current_window_open and not self._prev_window_open:
                # Fereastra tocmai s-a deschis
                window = get_meter_window_info(window_data)
                ev_data = {**event_data_base}
                window_end_str = ""
                if window:
                    ev_data["window_start"] = window.get("NextMonthOpeningDate") or window.get("OpeningDate")
                    ev_data["window_end"] = window.get("NextMonthClosingDate") or window.get("ClosingDate")
                    window_end_str = ev_data.get("window_end", "")
                self.hass.bus.async_fire(EVENT_READING_WINDOW_OPENED, ev_data)
                # Persistent notification
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": f"iHidro: Fereastră autocitire deschisă ({self.uan})",
                            "message": (
                                f"Fereastra de autocitire pentru POD {self.uan} "
                                f"este acum deschisă."
                                + (f" Termen limită: {window_end_str}." if window_end_str else "")
                                + " Introduceți indexul și apăsați butonul Trimite Index."
                            ),
                            "notification_id": f"ihidro_window_{self.uan}",
                        },
                    )
                )
                _LOGGER.info(
                    "iHidro [%s]: Fereastra de autocitire s-a deschis", self.uan
                )
            elif not current_window_open and self._prev_window_open:
                # Fereastra tocmai s-a închis — ștergem notificarea
                self.hass.bus.async_fire(
                    EVENT_READING_WINDOW_CLOSED, {**event_data_base}
                )
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "persistent_notification",
                        "dismiss",
                        {"notification_id": f"ihidro_window_{self.uan}"},
                    )
                )
                _LOGGER.info(
                    "iHidro [%s]: Fereastra de autocitire s-a închis", self.uan
                )
        self._prev_window_open = current_window_open

        # 2. Factură nouă detectată
        bill = get_current_bill_data(data.get("current_bill"))
        current_bill_number = None
        if bill:
            current_bill_number = bill.get("invoicenumber")

        if (
            self._prev_bill_number is not None
            and current_bill_number
            and current_bill_number != self._prev_bill_number
        ):
            bill_amount = bill.get("billamount") if bill else None
            bill_due_date = bill.get("duedate") if bill else None
            ev_data = {
                **event_data_base,
                "bill_number": current_bill_number,
                "amount": bill_amount,
                "due_date": bill_due_date,
            }
            self.hass.bus.async_fire(EVENT_NEW_BILL, ev_data)
            # Persistent notification
            msg_parts = [f"Factură nouă detectată pentru POD {self.uan}."]
            if bill_amount:
                msg_parts.append(f"Sumă: {bill_amount} lei.")
            if bill_due_date:
                msg_parts.append(f"Scadență: {bill_due_date}.")
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"iHidro: Factură nouă ({self.uan})",
                        "message": " ".join(msg_parts),
                        "notification_id": f"ihidro_new_bill_{self.uan}",
                    },
                )
            )
            _LOGGER.info(
                "iHidro [%s]: Factură nouă detectată: %s",
                self.uan,
                current_bill_number,
            )
        self._prev_bill_number = current_bill_number

        # 3. Factură restantă (overdue)
        current_overdue = False
        if bill:
            amount = safe_float(bill.get("rembalance") or bill.get("billamount"))
            due_date_str = bill.get("duedate")
            if amount > 0 and due_date_str:
                due_dt = parse_date(due_date_str)
                if due_dt and datetime.now() > due_dt:
                    current_overdue = True

        if (
            self._prev_overdue is not None
            and current_overdue
            and not self._prev_overdue
        ):
            overdue_amount = bill.get("billamount") if bill else None
            overdue_due_date = bill.get("duedate") if bill else None
            ev_data = {
                **event_data_base,
                "amount": overdue_amount,
                "due_date": overdue_due_date,
            }
            self.hass.bus.async_fire(EVENT_OVERDUE_BILL, ev_data)
            # Persistent notification
            msg_parts = [f"Factură restantă detectată pentru POD {self.uan}!"]
            if overdue_amount:
                msg_parts.append(f"Sumă: {overdue_amount} lei.")
            if overdue_due_date:
                msg_parts.append(f"Scadentă la: {overdue_due_date}.")
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"iHidro: Factură restantă! ({self.uan})",
                        "message": " ".join(msg_parts),
                        "notification_id": f"ihidro_overdue_{self.uan}",
                    },
                )
            )
            _LOGGER.info(
                "iHidro [%s]: Factură restantă detectată!", self.uan
            )
        elif self._prev_overdue and not current_overdue:
            # Restanța a fost rezolvată — ștergem notificarea
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": f"ihidro_overdue_{self.uan}"},
                )
            )
        self._prev_overdue = current_overdue

    async def _persist_tokens(self) -> None:
        """Salvează token-urile curente în config_entry.data pentru persistență."""
        tokens = self.api.export_tokens()
        user_id = tokens.get("user_id")
        session_token = tokens.get("session_token")

        if not user_id or not session_token:
            return

        current_data = dict(self.entry.data)
        if (
            current_data.get(CONF_TOKEN_USER_ID) != user_id
            or current_data.get(CONF_TOKEN_SESSION) != session_token
        ):
            current_data[CONF_TOKEN_USER_ID] = user_id
            current_data[CONF_TOKEN_SESSION] = session_token
            self.hass.config_entries.async_update_entry(
                self.entry, data=current_data
            )
            _LOGGER.debug("Token-uri persistate pentru POD %s", self.uan)
