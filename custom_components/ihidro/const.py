"""Constante pentru integrarea iHidro Romania."""

DOMAIN = "ihidro"

# Versiunea config entry (pentru migrare)
CONFIG_VERSION = 3

# Adresa de bază API
API_BASE_URL = "https://hidroelectrica-svc.smartcmobile.com"

# =========================================================================
# Endpoint-uri API — autentificare
# =========================================================================
API_PATH_GET_ID = "/API/UserLogin/GetId"
API_PATH_VALIDATE_LOGIN = "/API/UserLogin/ValidateUserLogin"
API_PATH_GET_USER_SETTING = "/API/UserLogin/GetUserSetting"

# =========================================================================
# Endpoint-uri API — facturi și plăți
# =========================================================================
API_PATH_GET_BILL = "/Service/Billing/GetBill"
API_PATH_GET_BILL_HISTORY = "/Service/Billing/GetBillingHistoryList"
# Notă: GetPaymentHistory NU există ca endpoint separat.
# Datele de plată sunt incluse în răspunsul GetBillingHistoryList.

# =========================================================================
# Endpoint-uri API — consum
# =========================================================================
API_PATH_GET_USAGE_GENERATION = "/Service/Usage/GetUsageGeneration"
API_PATH_GET_MULTI_METER = "/Service/Usage/GetMultiMeter"

# =========================================================================
# Endpoint-uri API — contor / autocitire
# =========================================================================
API_PATH_GET_WINDOW_DATES = "/Service/SelfMeterReading/GetWindowDates"
API_PATH_GET_METER_VALUE = "/Service/SelfMeterReading/GetMeterValue"
API_PATH_SUBMIT_SELF_METER_READ = "/Service/SelfMeterReading/SubmitSelfMeterRead"

# =========================================================================
# Endpoint-uri API — POD-uri și date contor avansate
# =========================================================================
API_PATH_GET_PODS = "/Service/SelfMeterReading/GetPods"
API_PATH_GET_PREVIOUS_METER_READ = "/Service/SelfMeterReading/GetPreviousMeterRead"
API_PATH_GET_MASTER_DATA_STATUS = "/API/UserLogin/GetMasterDataStatus"

# =========================================================================
# Endpoint-uri API — Istoric citiri și contoare (IndexHistory)
# =========================================================================
API_PATH_GET_METER_COUNTER_SERIES = "/Service/IndexHistory/GetMeterCounterSeries"
API_PATH_GET_METER_READ_HISTORY = "/Service/IndexHistory/GetMeterReadHistory"

# =========================================================================
# Header-e HTTP
# =========================================================================
HEADERS_PRE_AUTH = {
    "SourceType": "0",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.1",
}

HEADERS_POST_AUTH_BASE = {
    "SourceType": "1",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.1",
}

# =========================================================================
# Valori implicite
# =========================================================================
DEFAULT_UPDATE_INTERVAL = 3600  # în secunde (1 oră)
MIN_UPDATE_INTERVAL = 300       # 5 minute
MAX_UPDATE_INTERVAL = 86400     # 24 ore
HEAVY_REFRESH_EVERY = 4         # heavy refresh la fiecare a 4-a actualizare

# =========================================================================
# Chei de configurare
# =========================================================================
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SELECTED_ACCOUNTS = "selected_accounts"
CONF_ENERGY_SENSOR = "energy_sensor"

# Token persistence keys (stocate în config_entry.data)
CONF_TOKEN_USER_ID = "token_user_id"
CONF_TOKEN_SESSION = "token_session"

# =========================================================================
# Servicii
# =========================================================================
SERVICE_SUBMIT_METER_READING = "submit_meter_reading"

# =========================================================================
# Evenimente — permite utilizatorilor să creeze automatizări pe baza lor
# =========================================================================
EVENT_READING_WINDOW_OPENED = f"{DOMAIN}_reading_window_opened"
EVENT_READING_WINDOW_CLOSED = f"{DOMAIN}_reading_window_closed"
EVENT_NEW_BILL = f"{DOMAIN}_new_bill"
EVENT_OVERDUE_BILL = f"{DOMAIN}_overdue_bill"

# =========================================================================
# Atribute senzori
# =========================================================================
ATTR_ACCOUNT_NUMBER = "account_number"
ATTR_UTILITY_ACCOUNT_NUMBER = "utility_account_number"
ATTR_ADDRESS = "address"
ATTR_METER_NUMBER = "meter_number"
ATTR_LAST_READING = "last_reading"
ATTR_LAST_READING_DATE = "last_reading_date"
ATTR_CONSUMPTION = "consumption"
ATTR_AMOUNT = "amount"
ATTR_DUE_DATE = "due_date"
ATTR_STATUS = "status"

# =========================================================================
# Mesaje
# =========================================================================
ATTRIBUTION = "Date furnizate de Hidroelectrica România"
