"""
Client API async pentru iHidro.ro (Hidroelectrica România).

Implementează toate endpoint-urile API disponibile pentru:
- Autentificare (GetId, ValidateUserLogin, GetUserSetting)
- Facturi (GetBill, GetBillingHistoryList)
- Consum (GetUsageGeneration, GetMultiMeter)
- Contor / Autocitire (GetWindowDatesENC, GetWindowDates, GetMeterValue,
  SubmitSelfMeterRead, GetPods, GetPreviousMeterRead, GetMeterCounterSeries,
  GetMeterReadHistory, GetMasterDataStatus)

Notă: GetPaymentHistory NU există ca endpoint separat.
Datele de plată sunt incluse în răspunsul GetBillingHistoryList
(câmpul objBillingPaymentHistoryEntity).

Folosește aiohttp (via HA async_get_clientsession) în loc de requests sincron.
"""

import asyncio
import base64
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from .const import (
    API_BASE_URL,
    API_PATH_GET_ID,
    API_PATH_VALIDATE_LOGIN,
    API_PATH_GET_USER_SETTING,
    API_PATH_GET_BILL,
    API_PATH_GET_BILL_HISTORY,
    API_PATH_GET_USAGE_GENERATION,
    API_PATH_GET_MULTI_METER,
    API_PATH_GET_WINDOW_DATES,
    API_PATH_GET_METER_VALUE,
    API_PATH_SUBMIT_SELF_METER_READ,
    API_PATH_GET_PODS,
    API_PATH_GET_PREVIOUS_METER_READ,
    API_PATH_GET_METER_COUNTER_SERIES,
    API_PATH_GET_METER_READ_HISTORY,
    API_PATH_GET_MASTER_DATA_STATUS,
    HEADERS_PRE_AUTH,
    HEADERS_POST_AUTH_BASE,
)

_LOGGER = logging.getLogger(__name__)


class IhidroApiError(Exception):
    """Eroare generală API iHidro."""


class IhidroAuthError(IhidroApiError):
    """Eroare de autentificare API iHidro."""


class IhidroAPI:
    """Client API async pentru iHidro.ro."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        """Inițializare client API.

        Args:
            session: Sesiunea aiohttp (de obicei din async_get_clientsession).
            username: Email sau cod client iHidro.
            password: Parola contului.
        """
        self._session = session
        self._username = username
        self._password = password

        # Date de autentificare
        self._user_id: Optional[str] = None
        self._session_token: Optional[str] = None
        self._auth_header: Optional[Dict[str, str]] = None
        self._token_id: Optional[str] = None
        self._key: Optional[str] = None

        # Date utilizator
        self._utility_accounts: List[Dict[str, Any]] = []
        self._validate_user_login_data: List[Dict[str, Any]] = []
        self._raw_user_setting_data: Dict[str, Any] = {}

        # Lock pentru serializarea autentificării
        self._auth_lock = asyncio.Lock()

    # =========================================================================
    # Token persistence — export / import
    # =========================================================================

    def export_tokens(self) -> Dict[str, Optional[str]]:
        """Exportă token-urile curente pentru persistență."""
        return {
            "user_id": self._user_id,
            "session_token": self._session_token,
        }

    def inject_tokens(
        self, user_id: Optional[str], session_token: Optional[str]
    ) -> None:
        """Injectează token-uri salvate anterior (supraviețuiesc restartului HA).

        Reconstruiește și auth_header dacă ambele valori sunt prezente.
        """
        if user_id and session_token:
            self._user_id = user_id
            self._session_token = session_token
            encoded = base64.b64encode(
                f"{user_id}:{session_token}".encode()
            ).decode()
            self._auth_header = {
                **HEADERS_POST_AUTH_BASE,
                "Authorization": f"Basic {encoded}",
            }
            _LOGGER.debug("Token-uri injectate cu succes pentru UserID %s", user_id)

    # =========================================================================
    # Autentificare
    # =========================================================================

    async def login_if_needed(self) -> None:
        """Face login doar dacă session_token este None.

        Dacă avem token dar nu avem conturi încărcate, le obținem separat
        (se întâmplă după restart HA cu token-uri injectate).
        """
        if self._session_token:
            if not self._utility_accounts:
                _LOGGER.debug(
                    "Avem session_token dar nu avem conturi — obținem GetUserSetting."
                )
                await self._get_utility_accounts()
            return
        await self.login()

    async def login(self) -> None:
        """Autentificare la API iHidro.

        Secvența:
        1. GetId — obține key și token_id
        2. ValidateUserLogin — autentificare cu username/password
        3. GetUserSetting — obține conturile utilizatorului
        """
        async with self._auth_lock:
            # Verificăm din nou după ce am obținut lock-ul (alt apel a putut
            # finaliza autentificarea între timp)
            if self._session_token:
                return

            _LOGGER.debug(
                "=== iHidro: Începem autentificarea pentru '%s' ===",
                self._username,
            )

            # Pasul 1: GetId
            resp_get_id = await self._post_request(
                API_PATH_GET_ID,
                payload={},
                headers=HEADERS_PRE_AUTH,
                descriere="GetId - Obținere credențiale inițiale",
            )
            self._key = resp_get_id["result"]["Data"]["key"]
            self._token_id = resp_get_id["result"]["Data"]["tokenId"]

            _LOGGER.debug("Am obținut key și token_id pentru autentificare")

            # Pasul 2: ValidateUserLogin
            auth = base64.b64encode(
                f"{self._key}:{self._token_id}".encode()
            ).decode()
            login_headers = {
                **HEADERS_PRE_AUTH,
                "Authorization": f"Basic {auth}",
            }
            login_payload = {
                "deviceType": "HomeAssistant",
                "OperatingSystem": "Linux",
                "UpdatedDate": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
                "Deviceid": "",
                "SessionCode": "",
                "LanguageCode": "RO",
                "password": self._password,
                "UserId": self._username,
                "TFADeviceid": "",
                "OSVersion": 14,
                "TimeOffSet": "120",
                "LUpdHideShow": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
                "Browser": "HomeAssistant",
            }
            resp_login = await self._post_request(
                API_PATH_VALIDATE_LOGIN,
                payload=login_payload,
                headers=login_headers,
                descriere="ValidateUserLogin - Autentificare",
            )

            # Extragem datele din răspuns
            self._validate_user_login_data = resp_login["result"]["Data"].get(
                "Table", []
            )
            if not self._validate_user_login_data:
                raise IhidroAuthError(
                    "Eroare autentificare: Lipsește 'Table' din răspuns"
                )

            first_entry = self._validate_user_login_data[0]
            self._user_id = first_entry["UserID"]
            self._session_token = first_entry["SessionToken"]

            _LOGGER.debug("Autentificare reușită — UserID: %s", self._user_id)

            # Setăm header-ul de autentificare post-login
            encoded_auth = base64.b64encode(
                f"{self._user_id}:{self._session_token}".encode()
            ).decode()
            self._auth_header = {
                **HEADERS_POST_AUTH_BASE,
                "Authorization": f"Basic {encoded_auth}",
            }

            # Pasul 3: GetUserSetting — obținem conturile
            self._raw_user_setting_data = await self._get_utility_accounts()

            _LOGGER.info(
                "=== iHidro: Autentificare finalizată — Găsite %d POD-uri ===",
                len(self._utility_accounts),
            )

    async def _get_utility_accounts(self) -> Dict[str, Any]:
        """Obține lista de conturi (POD-uri) ale utilizatorului."""
        payload = {"UserID": self._user_id}
        resp = await self._post_request(
            API_PATH_GET_USER_SETTING,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUserSetting - Lista POD-uri",
        )

        data = resp["result"]["Data"]
        accounts: List[Dict[str, Any]] = []

        # Combinăm datele din Table1 și Table2
        if "Table1" in data and data["Table1"]:
            accounts.extend(data["Table1"])
        if "Table2" in data and data["Table2"]:
            for entry in data["Table2"]:
                if entry not in accounts:
                    accounts.append(entry)

        # Filtrăm și structurăm conturile
        filtered: List[Dict[str, Any]] = []
        for acc in accounts:
            if acc.get("UtilityAccountNumber"):
                filtered.append(
                    {
                        "AccountNumber": acc.get("AccountNumber"),
                        "UtilityAccountNumber": acc.get("UtilityAccountNumber"),
                        "Address": acc.get("Address"),
                        "IsDefaultAccount": acc.get("IsDefaultAccount"),
                        "CustomerName": acc.get("CustomerName"),
                    }
                )

        self._utility_accounts = filtered
        return resp

    # =========================================================================
    # Metode publice pentru accesarea datelor
    # =========================================================================

    def get_utility_accounts(self) -> List[Dict[str, Any]]:
        """Returnează lista de POD-uri (conturi)."""
        return self._utility_accounts

    @property
    def user_id(self) -> Optional[str]:
        """UserID curent."""
        return self._user_id

    # =========================================================================
    # Endpoint-uri pentru facturi
    # =========================================================================

    async def get_current_bill(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține factura curentă pentru un POD."""
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "IsBillPDF": "0",
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_BILL,
            payload=payload,
            headers=self._auth_header,
            descriere="GetBill - Factură curentă",
        )

    async def get_bill_history(
        self,
        utility_account_number: str,
        account_number: str,
        from_date: str,
        to_date: str,
    ) -> Dict[str, Any]:
        """Obține istoricul facturilor pentru un POD.

        Args:
            from_date: Format MM/DD/YYYY
            to_date: Format MM/DD/YYYY
        """
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "FromDate": from_date,
            "ToDate": to_date,
        }
        return await self._post_request(
            API_PATH_GET_BILL_HISTORY,
            payload=payload,
            headers=self._auth_header,
            descriere="GetBillingHistoryList - Istoric facturi",
        )

    # =========================================================================
    # Endpoint-uri pentru consum
    # =========================================================================

    async def get_usage_generation(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține istoricul de consum electric pentru un POD."""
        payload = {
            "date": "",
            "IsCSR": False,
            "IsUSD": False,
            "Mode": "M",
            "HourlyType": "H",
            "UsageType": "e",
            "UsageOrGeneration": False,
            "GroupId": 0,
            "LanguageCode": "RO",
            "Type": "D",
            "MeterNumber": "",
            "IsEnterpriseUser": False,
            "SeasonType": 0,
            "DateFromDaily": "",
            "IsNetUsage": False,
            "TimeOffset": "120",
            "UserType": "Residential",
            "DateToDaily": "",
            "UtilityId": 0,
            "IsLastTendays": False,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_USAGE_GENERATION,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUsageGeneration - Istoric consum (lunar)",
        )

    async def get_daily_usage(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține consumul zilnic pentru un POD (Mode=D).

        Returnează date zilnice de consum — granularitate mai bună
        decât consumul lunar, ideală pentru Energy Dashboard.
        """
        payload = {
            "date": "",
            "IsCSR": False,
            "IsUSD": False,
            "Mode": "D",
            "HourlyType": "H",
            "UsageType": "e",
            "UsageOrGeneration": False,
            "GroupId": 0,
            "LanguageCode": "RO",
            "Type": "D",
            "MeterNumber": "",
            "IsEnterpriseUser": False,
            "SeasonType": 0,
            "DateFromDaily": "",
            "IsNetUsage": False,
            "TimeOffset": "120",
            "UserType": "Residential",
            "DateToDaily": "",
            "UtilityId": 0,
            "IsLastTendays": False,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_USAGE_GENERATION,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUsageGeneration - Consum zilnic",
        )

    async def get_generation_data(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține datele de generare/producție pentru un POD prosumator.

        UsageOrGeneration=True solicită date de producție (export energie)
        în loc de consum (import energie).
        """
        payload = {
            "date": "",
            "IsCSR": False,
            "IsUSD": False,
            "Mode": "M",
            "HourlyType": "H",
            "UsageType": "e",
            "UsageOrGeneration": True,
            "GroupId": 0,
            "LanguageCode": "RO",
            "Type": "D",
            "MeterNumber": "",
            "IsEnterpriseUser": False,
            "SeasonType": 0,
            "DateFromDaily": "",
            "IsNetUsage": False,
            "TimeOffset": "120",
            "UserType": "Residential",
            "DateToDaily": "",
            "UtilityId": 0,
            "IsLastTendays": False,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_USAGE_GENERATION,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUsageGeneration - Producție prosumator",
        )

    async def get_net_usage(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține consumul net pentru un POD prosumator.

        IsNetUsage=True returnează consumul net (import - export).
        Valori negative indică surplus de producție.
        """
        payload = {
            "date": "",
            "IsCSR": False,
            "IsUSD": False,
            "Mode": "M",
            "HourlyType": "H",
            "UsageType": "e",
            "UsageOrGeneration": False,
            "GroupId": 0,
            "LanguageCode": "RO",
            "Type": "D",
            "MeterNumber": "",
            "IsEnterpriseUser": False,
            "SeasonType": 0,
            "DateFromDaily": "",
            "IsNetUsage": True,
            "TimeOffset": "120",
            "UserType": "Residential",
            "DateToDaily": "",
            "UtilityId": 0,
            "IsLastTendays": False,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_USAGE_GENERATION,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUsageGeneration - Consum net (prosumator)",
        )

    async def get_multi_meter_details(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține detalii despre contorul electric (meter) pentru un POD."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_MULTI_METER,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMultiMeter - Detalii contor",
        )

    # =========================================================================
    # Endpoint-uri pentru contor / autocitire
    # =========================================================================

    async def get_window_dates(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține fereastra de date pentru citirea indexului."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_WINDOW_DATES,
            payload=payload,
            headers=self._auth_header,
            descriere="GetWindowDates - Perioadă citire index (plain)",
        )

    async def get_pods(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """Obține datele POD / instalație pentru un cont."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_request(
            API_PATH_GET_PODS,
            payload=payload,
            headers=self._auth_header,
            descriere="GetPods - Date POD/instalație",
        )

    async def get_previous_meter_read(
        self,
        utility_account_number: str,
        installation_number: str = "",
        pod_value: str = "",
        customer_number: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Obține citirea anterioară a contorului cu metadate distribuitor/contract.

        Payload corect (din APK y0.java):
        {UtilityAccountNumber, InstallationNumber, podValue, LanguageCode,
         UserID, BasicValue, CustomerNumber, Distributor}

        NECESITĂ: InstallationNumber și podValue din GetPods!
        CustomerNumber = accountID (BPNumber) din GetPods.

        ATENȚIE: Returnează HTTP 400 când fereastra de autocitire este ÎNCHISĂ.
        Aceasta este comportament normal — funcția returnează None în acest caz.
        """
        payload = {
            "UtilityAccountNumber": utility_account_number,
            "InstallationNumber": installation_number,
            "podValue": pod_value,
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "BasicValue": "",
            "CustomerNumber": customer_number,
            "Distributor": "",
        }
        try:
            return await self._post_request(
                API_PATH_GET_PREVIOUS_METER_READ,
                payload=payload,
                headers=self._auth_header,
                descriere="GetPreviousMeterRead - Citire anterioară contor",
            )
        except IhidroApiError as err:
            # HTTP 400 = fereastra de autocitire închisă (comportament normal)
            if "400" in str(err):
                _LOGGER.debug(
                    "GetPreviousMeterRead: Fereastra de autocitire este închisă "
                    "(HTTP 400 — comportament normal)."
                )
                return None
            raise

    async def get_meter_counter_series(
        self,
        utility_account_number: str,
        installation_number: str,
        pod_value: str,
    ) -> Dict[str, Any]:
        """Obține seriile de contorizare cu detecția seriei active.

        Payload corect (din APK j0.java):
        {utilityAccountNumber, InstallationNumber, podValue, LanguageCode}

        NECESITĂ: InstallationNumber și podValue din GetPods!
        """
        payload = {
            "utilityAccountNumber": utility_account_number,
            "InstallationNumber": installation_number,
            "podValue": pod_value,
            "LanguageCode": "RO",
        }
        return await self._post_request(
            API_PATH_GET_METER_COUNTER_SERIES,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMeterCounterSeries - Serii contorizare",
        )

    async def get_meter_read_history(
        self,
        utility_account_number: str,
        installation_number: str,
        pod_value: str,
        serial_numbers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Obține istoricul complet al citirilor contorului.

        Payload corect (din APK h0.java):
        {utilityAccountNumber, podValue, LanguageCode, InstallationNumber,
         SerialNumber: JSONArray}

        NECESITĂ: InstallationNumber și podValue din GetPods!
        SerialNumber opțional (din GetMeterCounterSeries).

        Rezultatul include registre (1.8.0, 1.8.0_P etc.) ce permit
        detectarea automată a statusului de prosumator.
        """
        payload = {
            "utilityAccountNumber": utility_account_number,
            "podValue": pod_value,
            "LanguageCode": "RO",
            "InstallationNumber": installation_number,
            "SerialNumber": serial_numbers or [],
        }
        return await self._post_request(
            API_PATH_GET_METER_READ_HISTORY,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMeterReadHistory - Istoric citiri contor",
        )

    async def get_master_data_status(self) -> Dict[str, Any]:
        """Obține statusul datelor master (global, nu per POD).

        Payload corect (din APK decompilare): doar UserID.
        """
        payload = {"UserID": self._user_id}
        return await self._post_request(
            API_PATH_GET_MASTER_DATA_STATUS,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMasterDataStatus - Status date master",
        )

    async def get_meter_value(
        self,
        utility_account_number: str,
        account_number: str,
        meter_number: str,
        meter_reading: float,
        register: str = "1.8.0",
    ) -> Dict[str, Any]:
        """Pre-validare valoare index înainte de trimitere (GetMeterValue).

        Args:
            register: Registrul contorului (implicit 1.8.0 consum; 1.8.0_P producție prosumator).
        """
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "MeterNumber": meter_number,
            "MeterReading": str(meter_reading),
            "Register": register,
            "LanguageCode": "RO",
        }
        return await self._post_request(
            API_PATH_GET_METER_VALUE,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMeterValue - Pre-validare index",
        )

    async def submit_self_meter_read(
        self,
        utility_account_number: str,
        account_number: str,
        meter_number: str,
        meter_reading: float,
        register: str = "1.8.0",
        reading_date: Optional[str] = None,
        previous_meter_read_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Trimite indexul contorului la Hidroelectrica (SubmitSelfMeterRead).

        Construiește payload-ul corect UsageSelfMeterReadEntity pe baza
        datelor din GetPreviousMeterRead (dacă sunt furnizate).

        Args:
            register: Registrul contorului (1.8.0 sau 1.8.0_P).
            reading_date: Format MM/DD/YYYY, implicit data curentă.
            previous_meter_read_data: Răspunsul de la get_previous_meter_read
                (pentru metadate complete). Dacă lipsește, trimitem minimal.
        """
        if reading_date is None:
            reading_date = datetime.now().strftime("%m/%d/%Y")

        # Construim entitatea de citire
        read_entity: Dict[str, Any] = {
            "MeterNumber": meter_number,
            "MeterReading": str(meter_reading),
            "Register": register,
            "ReadingDate": reading_date,
            "MeterType": "E",
        }

        # Îmbogățim cu metadate din GetPreviousMeterRead dacă disponibile
        if previous_meter_read_data:
            try:
                prev_data = previous_meter_read_data.get("result", {}).get("Data", {})
                prev_table = prev_data.get("Table", [])
                if prev_table:
                    prev = prev_table[0]
                    read_entity.update(
                        {
                            "Installation": prev.get("Installation", ""),
                            "Division": prev.get("Division", ""),
                            "DeviceLoc": prev.get("DeviceLoc", ""),
                            "Device": prev.get("Device", ""),
                            "ContractAccount": prev.get("ContractAccount", ""),
                            "Contract": prev.get("Contract", ""),
                        }
                    )
            except (TypeError, KeyError) as err:
                _LOGGER.warning(
                    "Nu s-au putut extrage metadate din GetPreviousMeterRead: %s", err
                )

        payload = {
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "LanguageCode": "RO",
            "UsageSelfMeterReadEntity": [read_entity],
        }

        try:
            resp = await self._post_request(
                API_PATH_SUBMIT_SELF_METER_READ,
                payload=payload,
                headers=self._auth_header,
                descriere="SubmitSelfMeterRead - Trimitere index",
            )

            status = resp.get("result", {}).get("Status", "")
            if status == "Success":
                return {
                    "success": True,
                    "message": "Index trimis cu succes",
                    "data": resp,
                }
            return {
                "success": False,
                "message": resp.get("result", {}).get(
                    "Message", "Eroare necunoscută"
                ),
                "data": resp,
            }

        except Exception as err:
            _LOGGER.error("Eroare la trimiterea indexului: %s", err)
            return {
                "success": False,
                "message": str(err),
                "data": None,
            }

    # =========================================================================
    # Metodă legacy — compatibilitate inversă
    # =========================================================================

    async def submit_meter_reading(
        self,
        utility_account_number: str,
        account_number: str,
        meter_number: str,
        meter_reading: float,
        reading_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Alias pentru submit_self_meter_read (compatibilitate)."""
        return await self.submit_self_meter_read(
            utility_account_number=utility_account_number,
            account_number=account_number,
            meter_number=meter_number,
            meter_reading=meter_reading,
            reading_date=reading_date,
        )

    # =========================================================================
    # Metode interne
    # =========================================================================

    async def _post_request(
        self,
        path: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        descriere: str = "Cerere nedefinită",
    ) -> Dict[str, Any]:
        """Execută o cerere POST către API.

        Gestionează automat retry în caz de 401 (session expirat).

        Args:
            path: Calea relativă a endpoint-ului (fără baza URL).
            payload: Date de trimis (JSON).
            headers: Header-e HTTP. Dacă None, folosește _auth_header.
            descriere: Descriere pentru logging.

        Returns:
            Dict cu răspunsul JSON decodat.

        Raises:
            IhidroAuthError: Dacă autentificarea eșuează.
            IhidroApiError: Dacă API-ul răspunde cu eroare.
        """
        url = f"{API_BASE_URL}{path}"
        req_headers = headers if headers is not None else self._auth_header

        if req_headers is None:
            raise IhidroAuthError(
                "Nu există header de autentificare. Apelați login() mai întâi."
            )

        _LOGGER.debug("=== Cerere POST: %s (%s) ===", path, descriere)

        try:
            # Prima încercare
            async with self._session.post(
                url, json=payload, headers=req_headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 401:
                    _LOGGER.warning(
                        "Primim 401 la %s, facem re-autentificare...", descriere
                    )
                    # Invalidăm session-ul curent
                    self._session_token = None
                    self._auth_header = None
                    # Re-autentificare
                    await self.login()

                    # Verificăm dacă utilizatorul mai are acces la acest POD
                    req_uan = payload.get("UtilityAccountNumber")
                    if req_uan:
                        has_uan = any(
                            a["UtilityAccountNumber"] == req_uan
                            for a in self._utility_accounts
                        )
                        if not has_uan:
                            raise IhidroApiError(
                                f"Utilizatorul nu mai are acces la POD-ul {req_uan}"
                            )

                    # A doua încercare (retry)
                    async with self._session.post(
                        url,
                        json=payload,
                        headers=self._auth_header,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as retry_resp:
                        if retry_resp.status != 200:
                            text = await retry_resp.text()
                            raise IhidroApiError(
                                f"Eroare la {descriere}: {retry_resp.status} - {text}"
                            )
                        return await retry_resp.json()

                if response.status != 200:
                    text = await response.text()
                    raise IhidroApiError(
                        f"Eroare la {descriere}: {response.status} - {text}"
                    )

                return await response.json()

        except aiohttp.ClientError as err:
            raise IhidroApiError(
                f"Eroare de conexiune la {descriere}: {err}"
            ) from err

    def invalidate_session(self) -> None:
        """Invalidează sesiunea curentă (forțează re-autentificare la următorul apel)."""
        self._session_token = None
        self._auth_header = None
        _LOGGER.debug("Sesiune iHidro invalidată")
