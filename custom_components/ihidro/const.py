"""Constante pentru integrarea iHidro Romania."""

DOMAIN = "ihidro"

# Adresa de bază API
API_BASE_URL = "https://hidroelectrica-svc.smartcmobile.com"

# Endpoint-uri API
API_URL_GET_ID = f"{API_BASE_URL}/API/UserLogin/GetId"
API_URL_VALIDATE_LOGIN = f"{API_BASE_URL}/API/UserLogin/ValidateUserLogin"
API_URL_GET_USER_SETTING = f"{API_BASE_URL}/API/UserLogin/GetUserSetting"
API_GET_MULTI_METER = f"{API_BASE_URL}/Service/Usage/GetMultiMeter"
API_GET_MULTI_METER_READ_DATE = f"{API_BASE_URL}/Service/SelfMeterReading/GetWindowDatesENC"
API_URL_GET_BILL = f"{API_BASE_URL}/Service/Billing/GetBill"
API_URL_GET_BILL_HISTORY = f"{API_BASE_URL}/Service/Billing/GetBillingHistoryList"
API_URL_GET_USAGE_GENERATION = f"{API_BASE_URL}/Service/Usage/GetUsageGeneration"
# Endpoint pentru trimitere index (va fi descoperit prin interceptare)
API_SUBMIT_METER_READING = f"{API_BASE_URL}/Service/SelfMeterReading/SubmitMeterReading"

# Valori implicite
DEFAULT_UPDATE_INTERVAL = 3600  # în secunde (1 oră)
MIN_UPDATE_INTERVAL = 300       # 5 minute
MAX_UPDATE_INTERVAL = 86400     # 24 ore

# Chei de configurare
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TWOCAPTCHA_API_KEY = "twocaptcha_api_key"

# Web Portal
WEB_PORTAL_BASE_URL = "https://ihidro.ro/portal"
RECAPTCHA_SITE_KEY = "6LdWVgYfAAAAAOtv1JCMvOVYagKN_I7Tt8EMCBWx"

# Servicii
SERVICE_SUBMIT_METER_READING = "submit_meter_reading"

# Atribute senzori
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

# Mesaje
ATTRIBUTION = "Date furnizate de Hidroelectrica România"
