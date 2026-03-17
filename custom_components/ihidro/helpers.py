"""Funcții utilitare pentru integrarea iHidro Romania."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_LOGGER = logging.getLogger(__name__)


def safe_get(
    data: Optional[Dict[str, Any]],
    *keys: str,
    default: Any = None,
) -> Any:
    """Extrage sigur o valoare dintr-un dict imbricat.

    Exemplu:
        safe_get(resp, "result", "Data", "Table", default=[])
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def safe_get_table(
    response: Optional[Dict[str, Any]],
    table_key: str = "Table",
) -> List[Dict[str, Any]]:
    """Extrage o listă Table din răspunsul standard al API-ului SEW.

    ATENȚIE: API-ul Hidroelectrica nu folosește structura result.Data.Table!
    Această funcție este păstrată pentru compatibilitate, dar în practică
    returnează mereu []. Folosiți funcțiile specifice de mai jos.

    Structura așteptată (nu există la Hidroelectrica):
        response["result"]["Data"][table_key] -> list
    """
    table = safe_get(response, "result", "Data", table_key, default=[])
    if isinstance(table, list):
        return table
    return []


# =========================================================================
# Funcții de extragere specifice pentru API-ul Hidroelectrica
# =========================================================================


def get_current_bill_data(
    current_bill: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Extrage datele facturii curente din răspunsul GetBill.

    Structura reală: current_bill["result"] are chei flat:
        billamount, rembalance, duedate, invoicenumber, Table1 (null)

    Returnează un dict normalizat sau None.
    """
    if not current_bill:
        return None
    result = current_bill.get("result")
    if not isinstance(result, dict):
        return None

    # Verificăm că avem cel puțin o cheie utilă
    if not any(
        result.get(k) is not None
        for k in ("billamount", "rembalance", "duedate", "invoicenumber")
    ):
        return None

    return result


def get_bill_history_list(
    bill_history: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extrage lista de facturi din răspunsul GetBillingHistoryList.

    Structura reală: bill_history["result"]["objBillingHistoryEntity"] -> list
    Câmpuri: amount, dueDate, invoiceDate, invoiceType, exbel, invoiceId, etc.
    """
    if not bill_history:
        return []
    result = bill_history.get("result", {})
    if not isinstance(result, dict):
        return []
    bills = result.get("objBillingHistoryEntity")
    if isinstance(bills, list):
        return bills
    return []


def get_data_list(
    response: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extrage result.Data când este o listă.

    Folosit pentru: meter_read_history, meter_counter_series,
    previous_meter_read, pods, master_data_status.

    Structura reală: response["result"]["Data"] -> list
    """
    if not response:
        return []
    data = safe_get(response, "result", "Data", default=None)
    if isinstance(data, list):
        return data
    return []


def get_data_dict(
    response: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Extrage result.Data când este un dict.

    Folosit pentru: meter_window, daily_usage, usage_history, generation_data, net_usage.

    Structura reală: response["result"]["Data"] -> dict
    """
    if not response:
        return None
    data = safe_get(response, "result", "Data", default=None)
    if isinstance(data, dict):
        return data
    return None


def get_meter_window_info(
    meter_window: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Extrage informațiile despre fereastra de autocitire.

    Structura reală: meter_window["result"]["Data"] -> dict cu:
        OpeningDate, ClosingDate, NextMonthOpeningDate,
        NextMonthClosingDate, Is_Window_Open
    """
    return get_data_dict(meter_window)


def get_tentative_data(
    response: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Extrage getTentativeData[0] din daily_usage/net_usage/generation_data.

    Structura reală: response["result"]["Data"]["getTentativeData"] -> list
    Primul element are: SoFar, ExpectedUsage, Average, Highest, UsageCycle, etc.
    """
    data = get_data_dict(response)
    if not data:
        return None
    tentative = data.get("getTentativeData")
    if isinstance(tentative, list) and tentative:
        return tentative[0]
    return None


def get_usage_result_sets(
    response: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extrage seturile de date de utilizare din usage/generation/net responses.

    Structura reală: response["result"]["Data"] -> dict cu:
        objUsageGenerationResultSetOne (location info),
        objUsageGenerationResultSetTwo (monthly data),
        objUsageGenerationResultSetThree (date range),
        listUsageColor, getTentativeData, etc.
    """
    data = get_data_dict(response)
    if not data:
        return {}
    return data


def safe_float(value: Any, default: float = 0.0) -> float:
    """Conversie sigură la float din diverse formate API.

    Gestionează: "1234.56", "1.234,56", "RON 50", None, "".
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        # Eliminăm prefixuri/sufixuri monedă
        for token in ("RON", "EUR", "LEI", "lei", "ron", "eur"):
            cleaned = cleaned.replace(token, "")
        cleaned = cleaned.strip()
        if not cleaned:
            return default
        # Dacă are virgulă ca separator decimal (format european)
        if "," in cleaned and "." in cleaned:
            # 1.234,56 → 1234.56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def format_date_ro(date_str: Optional[str]) -> Optional[str]:
    """Formatează o dată din formatul API (diverse) în DD.MM.YYYY.

    Acceptă: MM/DD/YYYY, YYYY-MM-DD, DD.MM.YYYY (pass-through), YYYYMMDD.
    Dacă data conține o componentă de timp la miezul nopții (00:00), aceasta
    este eliminată automat — nu oferă informație utilă.
    """
    if not date_str:
        return None

    for fmt_in, fmt_out in [
        ("%Y%m%d", "%d.%m.%Y"),
        ("%m/%d/%Y", "%d.%m.%Y"),
        ("%Y-%m-%d", "%d.%m.%Y"),
        ("%m/%d/%Y %H:%M:%S", "%d.%m.%Y %H:%M"),
        ("%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M"),
        ("%Y-%m-%dT%H:%M:%SZ", "%d.%m.%Y %H:%M"),
        ("%d/%m/%Y", "%d.%m.%Y"),
    ]:
        try:
            parsed = datetime.strptime(date_str.strip(), fmt_in)
            result = parsed.strftime(fmt_out)
            # Eliminăm componenta de timp dacă e miezul nopții (00:00)
            if result.endswith(" 00:00"):
                result = result[:-6]
            return result
        except ValueError:
            continue

    # Dacă e deja în format DD.MM.YYYY sau alt format necunoscut, returnăm ca atare
    return date_str


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse o dată din diverse formate API într-un obiect datetime."""
    if not date_str:
        return None
    for fmt in (
        "%Y%m%d",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%d/%m/%Y",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


# =========================================================================
# Formatare românească
# =========================================================================


def format_number_ro(value: float, decimals: int = 2) -> str:
    """Formatează un număr în format românesc: 1.234,56.

    Args:
        value: Valoarea de formatat.
        decimals: Numărul de zecimale.
    """
    if decimals == 0:
        formatted = f"{value:,.0f}"
    else:
        formatted = f"{value:,.{decimals}f}"
    # Python: 1,234.56 → RO: 1.234,56
    # Swap . and , via intermediate
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return formatted


def format_ron(value: float) -> str:
    """Formatează o valoare monetară în format românesc: 1.234,56 lei."""
    return f"{format_number_ro(value, 2)} lei"


# =========================================================================
# Detecție prosumator
# =========================================================================


def is_prosumer(meter_read_history: Optional[Dict[str, Any]]) -> bool:
    """Detectează dacă un POD este prosumator.

    Un prosumator are registrul cu _P (ex: 1.8.0_P) în istoricul de citiri
    (GetMeterReadHistory).

    Structura reală: meter_read_history["result"]["Data"] -> list
    Câmpuri: Registers (nu Register!), CounterSeries, Index, Date, etc.
    """
    entries = get_data_list(meter_read_history)
    for entry in entries:
        registers = entry.get("Registers", "") or entry.get("Register", "")
        if "_P" in str(registers).upper():
            return True
    return False


# =========================================================================
# Active counter series detection
# =========================================================================


def get_active_counter_series(
    meter_counter_series: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Determină seria activă de contorizare prin compararea datelor MrDate.

    Utilizatorii pot avea mai multe serii de contorizare (contor vechi + nou).
    Seria activă este cea cu cea mai recentă dată MrDate.

    Structura reală: meter_counter_series["result"]["Data"] -> list
    Câmpuri: CounterSeries (nu MeterNumber!), Index (comma-separated string), MrDate
    Returnează CounterSeries-ul seriei active.
    """
    entries = get_data_list(meter_counter_series)
    if not entries:
        return None

    best_meter: Optional[str] = None
    best_date: Optional[datetime] = None

    for entry in entries:
        meter_num = entry.get("CounterSeries") or entry.get("MeterNumber")
        mr_date_str = entry.get("MrDate")
        if not meter_num or not mr_date_str:
            continue

        mr_date = parse_date(mr_date_str)
        if mr_date is None:
            continue

        if best_date is None or mr_date > best_date:
            best_date = mr_date
            best_meter = meter_num

    return best_meter



# =========================================================================
# Cascading fallback for meter index
# =========================================================================


def get_meter_index_cascading(
    data: Dict[str, Any],
    register: str = "1.8.0",
    active_meter: Optional[str] = None,
) -> Tuple[Optional[float], str]:
    """Obține indexul contorului cu fallback pe 3 surse de date.

    Ordinea:
    1. GetMeterReadHistory (filtrat pe seria activă + registrul specificat)
    2. GetPreviousMeterRead (prevMRResult)
    3. GetMeterCounterSeries (ultimul index din seria activă)

    Structuri reale din API:
    - meter_read_history: result.Data -> list, chei: Index, Registers, CounterSeries, Date
    - previous_meter_read: result.Data -> list, chei: prevMRResult, serialNumber, registerCat
    - meter_counter_series: result.Data -> list, chei: CounterSeries, Index (comma-separated!), MrDate

    Returns:
        Tuple (valoare_index, sursa) unde sursa este unul din:
        "meter_read_history", "previous_meter_read", "meter_counter_series", "none"
    """
    # Sursa 1: GetMeterReadHistory
    # IMPORTANT: API returnează lista sortată ASCENDENT (cele mai vechi primele).
    # Iterăm în ordine inversă (reversed) pentru a obține cea mai recentă citire.
    history_entries = get_data_list(data.get("meter_read_history"))
    if history_entries:
        for entry in reversed(history_entries):
            entry_register = entry.get("Registers", "") or entry.get("Register", "")
            entry_meter = entry.get("CounterSeries", "") or entry.get("MeterNumber", "")
            if entry_register == register:
                if active_meter and str(entry_meter) != str(active_meter):
                    continue
                reading = safe_float(entry.get("Index") or entry.get("MeterReading"))
                if reading > 0:
                    return reading, "meter_read_history"

    # Sursa 2: GetPreviousMeterRead
    prev_entries = get_data_list(data.get("previous_meter_read"))
    if prev_entries:
        for entry in prev_entries:
            # Filtrăm pe registerCat dacă avem register specificat
            entry_register = entry.get("registerCat", "")
            if entry_register and entry_register != register:
                continue
            # Filtrăm pe serialNumber (echivalent CounterSeries)
            entry_meter = entry.get("serialNumber", "")
            if active_meter and entry_meter and str(entry_meter) != str(active_meter):
                continue
            reading = safe_float(
                entry.get("prevMRResult") or entry.get("MeterReading")
            )
            if reading > 0:
                return reading, "previous_meter_read"

    # Sursa 3: GetMeterCounterSeries
    # Index este un string comma-separated: "4132,4317,4780,5406,5396"
    # Ultimul element este cel mai recent
    series_entries = get_data_list(data.get("meter_counter_series"))
    if series_entries:
        for entry in series_entries:
            entry_meter = entry.get("CounterSeries", "") or entry.get("MeterNumber", "")
            if active_meter and str(entry_meter) != str(active_meter):
                continue
            index_str = entry.get("Index", "")
            if isinstance(index_str, str) and "," in index_str:
                # Comma-separated string — last value is most recent
                parts = [p.strip() for p in index_str.split(",") if p.strip()]
                if parts:
                    reading = safe_float(parts[-1])
                    if reading > 0:
                        return reading, "meter_counter_series"
            else:
                # Numeric or single value
                reading = safe_float(index_str or entry.get("LastIndex") or entry.get("MeterReading"))
                if reading > 0:
                    return reading, "meter_counter_series"

    return None, "none"


# =========================================================================
# Extragere plăți din bill_history (GetBillingHistoryList)
# =========================================================================


def get_payment_list_from_bill_history(
    bill_history: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extrage lista de plăți din răspunsul GetBillingHistoryList.

    Plățile se află la result.objBillingPaymentHistoryEntity, nu într-un
    endpoint separat (GetPaymentHistory nu există).

    Câmpurile din API (lowercase): amount, paymentDate, channel, type, status.
    """
    if not bill_history:
        return []
    result = bill_history.get("result", {})
    if not isinstance(result, dict):
        return []
    payments = result.get("objBillingPaymentHistoryEntity")
    if isinstance(payments, list):
        return payments
    return []


# =========================================================================
# Separare plăți normale vs. compensări ANRE
# =========================================================================


def split_payments_by_channel(
    payments: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Separă plățile în plăți normale și compensări ANRE.

    cnecrea pattern: prefixul canalului de plată determină tipul:
    - "Incasari-*" → plăți normale
    - "Comp ANRE-*" → compensări ANRE (credite prosumator)

    Args:
        payments: Lista de plăți extrasă cu get_payment_list_from_bill_history().

    Returns:
        Tuple (plati_normale, compensari_anre)
    """
    normal: List[Dict[str, Any]] = []
    anre: List[Dict[str, Any]] = []

    for payment in payments:
        channel = payment.get("channel", "") or payment.get("PaymentChannel", "") or ""
        if channel.startswith("Comp ANRE"):
            anre.append(payment)
        else:
            normal.append(payment)

    return normal, anre


# =========================================================================
# Fereastră autocitire
# =========================================================================


def is_reading_window_open(
    window_dates_response: Optional[Dict[str, Any]],
) -> bool:
    """Verifică dacă fereastra de autocitire este deschisă acum.

    Structura reală: window_dates_response["result"]["Data"] -> dict cu:
        Is_Window_Open ("0" sau "1"),
        OpeningDate, ClosingDate, NextMonthOpeningDate, NextMonthClosingDate

    Strategia:
    1. Folosim Is_Window_Open dacă disponibil ("1" = deschis)
    2. Fallback: comparăm datele de deschidere/închidere cu data curentă
    """
    window = get_meter_window_info(window_dates_response)
    if not window:
        return False

    # Metoda principală: flag direct de la API
    is_open = window.get("Is_Window_Open")
    if is_open is not None:
        return str(is_open).strip() == "1"

    # Fallback: comparăm datele (NextMonthOpeningDate / NextMonthClosingDate)
    # Format: "22/03/2026" sau "22" (doar ziua)
    start_str = (
        window.get("NextMonthOpeningDate")
        or window.get("OpeningDate")
        or window.get("WindowStartDate")
        or window.get("StartDate")
    )
    end_str = (
        window.get("NextMonthClosingDate")
        or window.get("ClosingDate")
        or window.get("WindowEndDate")
        or window.get("EndDate")
    )

    if not start_str or not end_str:
        return False

    now = datetime.now()

    # Dacă sunt doar numere (zile), construim datele din luna curentă
    if start_str.isdigit() and end_str.isdigit():
        try:
            start_day = int(start_str)
            end_day = int(end_str)
            start = now.replace(day=start_day, hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(day=end_day, hour=23, minute=59, second=59, microsecond=0)
            return start <= now <= end
        except ValueError:
            return False

    # Încearcă parse complet
    start_dt = parse_date(start_str)
    end_dt = parse_date(end_str)
    if start_dt and end_dt:
        return start_dt <= now <= end_dt

    return False


# =========================================================================
# Anonymizare date pentru diagnostics
# =========================================================================


def anonymize_string(value: Optional[str], keep_last: int = 4) -> Optional[str]:
    """Anonimizează un string, păstrând ultimele N caractere."""
    if not value:
        return value
    if len(value) <= keep_last:
        return "***"
    return "*" * (len(value) - keep_last) + value[-keep_last:]


def anonymize_data(data: Any, sensitive_keys: Optional[set] = None) -> Any:
    """Anonimizează recursiv datele sensibile dintr-un dict/list.

    Args:
        data: Datele de anonimizat.
        sensitive_keys: Set de chei considerate sensibile.
    """
    if sensitive_keys is None:
        sensitive_keys = {
            # Original keys
            "AccountNumber",
            "UtilityAccountNumber",
            "UserID",
            "SessionToken",
            "CustomerName",
            "Address",
            "Installation",
            "ContractAccount",
            "Contract",
            "password",
            "UserId",
            "Authorization",
            # Keys found in API responses (previously leaked)
            "contractAccountID",
            "accountID",
            "pod",
            "POD",
            "distCustomer",
            "distCustomerId",
            "distContract",
            "installationNumber",
            "installation",
            "Zipcode",
            "serialNumber",
            "CounterSeries",
            "equipmentNo",
            "invoiceId",
            "invoicenumber",
            "exbel",
            "CityName",
            "username",
        }

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in sensitive_keys and isinstance(value, str):
                result[key] = anonymize_string(value)
            else:
                result[key] = anonymize_data(value, sensitive_keys)
        return result
    elif isinstance(data, list):
        return [anonymize_data(item, sensitive_keys) for item in data]
    return data
