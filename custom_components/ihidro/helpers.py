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

    Structura așteptată: response["result"]["Data"][table_key] -> list
    """
    table = safe_get(response, "result", "Data", table_key, default=[])
    if isinstance(table, list):
        return table
    return []


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

    Acceptă: MM/DD/YYYY, YYYY-MM-DD, DD.MM.YYYY (pass-through).
    """
    if not date_str:
        return None

    for fmt_in, fmt_out in [
        ("%m/%d/%Y", "%d.%m.%Y"),
        ("%Y-%m-%d", "%d.%m.%Y"),
        ("%m/%d/%Y %H:%M:%S", "%d.%m.%Y %H:%M"),
        ("%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M"),
        ("%d/%m/%Y", "%d.%m.%Y"),
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt_in).strftime(fmt_out)
        except ValueError:
            continue

    # Dacă e deja în format DD.MM.YYYY sau alt format necunoscut, returnăm ca atare
    return date_str


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse o dată din diverse formate API într-un obiect datetime."""
    if not date_str:
        return None
    for fmt in (
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
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

    Un prosumator are registrul 1.8.0_P în istoricul de citiri
    (GetMeterReadHistory).
    """
    table = safe_get_table(meter_read_history)
    for entry in table:
        register = entry.get("Register", "")
        if "_P" in register.upper():
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
    Returnează MeterNumber-ul seriei active.
    """
    table = safe_get_table(meter_counter_series)
    if not table:
        return None

    best_meter: Optional[str] = None
    best_date: Optional[datetime] = None

    for entry in table:
        meter_num = entry.get("MeterNumber")
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

    Returns:
        Tuple (valoare_index, sursa) unde sursa este unul din:
        "meter_read_history", "previous_meter_read", "meter_counter_series", "none"
    """
    # Sursa 1: GetMeterReadHistory
    history_table = safe_get_table(data.get("meter_read_history"))
    if history_table:
        for entry in history_table:
            entry_register = entry.get("Register", "")
            entry_meter = entry.get("MeterNumber", "")
            if entry_register == register:
                if active_meter and entry_meter != active_meter:
                    continue
                reading = safe_float(entry.get("MeterReading"))
                if reading > 0:
                    return reading, "meter_read_history"

    # Sursa 2: GetPreviousMeterRead
    prev_table = safe_get_table(data.get("previous_meter_read"))
    if prev_table:
        for entry in prev_table:
            reading = safe_float(
                entry.get("prevMRResult") or entry.get("MeterReading")
            )
            if reading > 0:
                return reading, "previous_meter_read"

    # Sursa 3: GetMeterCounterSeries
    series_table = safe_get_table(data.get("meter_counter_series"))
    if series_table:
        for entry in series_table:
            entry_meter = entry.get("MeterNumber", "")
            if active_meter and entry_meter != active_meter:
                continue
            reading = safe_float(entry.get("LastIndex") or entry.get("MeterReading"))
            if reading > 0:
                return reading, "meter_counter_series"

    return None, "none"


# =========================================================================
# Separare plăți normale vs. compensări ANRE
# =========================================================================


def split_payments_by_channel(
    payment_history: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Separă plățile în plăți normale și compensări ANRE.

    cnecrea pattern: prefixul canalului de plată determină tipul:
    - "Incasari-*" → plăți normale
    - "Comp ANRE-*" → compensări ANRE (credite prosumator)

    Returns:
        Tuple (plati_normale, compensari_anre)
    """
    table = safe_get_table(payment_history)
    normal: List[Dict[str, Any]] = []
    anre: List[Dict[str, Any]] = []

    for payment in table:
        channel = payment.get("PaymentChannel", "") or ""
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
    """Verifică dacă fereastra de autocitire este deschisă acum."""
    table = safe_get_table(window_dates_response)
    if not table:
        return False

    window = table[0]
    start_str = window.get("WindowStartDate") or window.get("StartDate")
    end_str = window.get("WindowEndDate") or window.get("EndDate")

    if not start_str or not end_str:
        return False

    now = datetime.now()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
        try:
            start = datetime.strptime(start_str.strip(), fmt)
            end = datetime.strptime(end_str.strip(), fmt)
            return start <= now <= end
        except ValueError:
            continue

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
