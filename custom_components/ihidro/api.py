"""
Client API pentru iHidro.ro (Hidroelectrica România).

Implementează toate endpoint-urile API pentru:
- Autentificare
- Facturi (curente și istorice)
- Consum electric (istoric)
- Index contor (citire și trimitere)
"""

import logging
import requests
import base64
import urllib3
from datetime import datetime
from typing import Dict, Any, List, Optional

from .const import (
    API_URL_GET_ID,
    API_URL_VALIDATE_LOGIN,
    API_URL_GET_USER_SETTING,
    API_GET_MULTI_METER,
    API_GET_MULTI_METER_READ_DATE,
    API_URL_GET_BILL,
    API_URL_GET_BILL_HISTORY,
    API_URL_GET_USAGE_GENERATION,
    API_SUBMIT_METER_READING,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)


class IhidroAPI:
    """Client API pentru iHidro.ro."""

    def __init__(self, username: str, password: str):
        """Inițializare client API."""
        self._username = username
        self._password = password

        # Date de autentificare
        self._user_id = None
        self._session_token = None
        self._auth_header = None
        self._token_id = None
        self._key = None

        # Date utilizator
        self._utility_accounts = []
        self._validate_user_login_data = []
        self._raw_user_setting_data = {}

        # Sesiune HTTP
        self._session = requests.Session()
        self._session.verify = False

    def login_if_needed(self) -> None:
        """Face login doar dacă session_token este None."""
        if self._session_token:
            _LOGGER.debug("Avem deja session_token valid, nu mai facem login.")
            return
        self.login()

    def login(self) -> None:
        """
        Autentificare la API iHidro.
        
        Secvența de autentificare:
        1. GetId - obține key și token_id
        2. ValidateUserLogin - autentificare cu username/password
        3. GetUserSetting - obține conturile utilizatorului
        """
        _LOGGER.debug("=== iHidro: Începem autentificarea pentru '%s' ===", self._username)

        # Pasul 1: GetId
        resp_get_id = self._post_request(
            API_URL_GET_ID,
            payload={},
            headers={
                "SourceType": "0",
                "Content-Type": "application/json",
                "Host": "hidroelectrica-svc.smartcmobile.com",
                "User-Agent": "okhttp/4.9.1",
            },
            descriere="GetId - Obținere credențiale inițiale"
        )
        self._key = resp_get_id["result"]["Data"]["key"]
        self._token_id = resp_get_id["result"]["Data"]["tokenId"]

        _LOGGER.debug("Am obținut key și token_id pentru autentificare")

        # Pasul 2: ValidateUserLogin
        auth = base64.b64encode(f"{self._key}:{self._token_id}".encode()).decode()
        login_headers = {
            "SourceType": "0",
            "Content-Type": "application/json",
            "Host": "hidroelectrica-svc.smartcmobile.com",
            "User-Agent": "okhttp/4.9.1",
            "Authorization": f"Basic {auth}"
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
            "Browser": "HomeAssistant"
        }
        resp_login = self._post_request(
            API_URL_VALIDATE_LOGIN,
            payload=login_payload,
            headers=login_headers,
            descriere="ValidateUserLogin - Autentificare"
        )

        # Extragem datele din răspuns
        response_data = resp_login.get("result", {}).get("Data", {})
        _LOGGER.debug("ValidateUserLogin response Data: %s", response_data)
        
        self._validate_user_login_data = response_data.get("Table", [])
        if not self._validate_user_login_data:
            # Log full response for debugging
            _LOGGER.error("Login response structure: %s", json.dumps(resp_login, indent=2))
            raise Exception(
                f"Eroare autentificare: Lipsește 'Table' din răspuns. "
                f"Response keys: {list(response_data.keys())}"
            )

        first_user_entry = self._validate_user_login_data[0]
        self._user_id = first_user_entry["UserID"]
        self._session_token = first_user_entry["SessionToken"]

        _LOGGER.debug("Autentificare reușită - UserID: %s", self._user_id)

        # Setăm header-ul de autentificare pentru toate cererile ulterioare
        encoded_auth = base64.b64encode(
            f"{self._user_id}:{self._session_token}".encode()
        ).decode()
        self._auth_header = {
            "SourceType": "1",
            "Content-Type": "application/json",
            "Host": "hidroelectrica-svc.smartcmobile.com",
            "User-Agent": "okhttp/4.9.1",
            "Authorization": f"Basic {encoded_auth}"
        }

        # Pasul 3: GetUserSetting - obținem conturile
        resp_userset = self._get_utility_accounts()
        self._raw_user_setting_data = resp_userset

        _LOGGER.info(
            "=== iHidro: Autentificare finalizată - Găsite %d POD-uri ===",
            len(self._utility_accounts)
        )

    def _get_utility_accounts(self) -> Dict[str, Any]:
        """
        Obține lista de conturi (POD-uri) ale utilizatorului.
        
        Returns:
            Dict cu toate datele brute din GetUserSetting
        """
        payload = {"UserID": self._user_id}
        resp = self._post_request(
            API_URL_GET_USER_SETTING,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUserSetting - Lista POD-uri"
        )

        data = resp["result"]["Data"]
        accounts = []
        
        # Combinăm datele din Table1 și Table2
        if "Table1" in data and data["Table1"]:
            accounts.extend(data["Table1"])
        if "Table2" in data and data["Table2"]:
            for entry in data["Table2"]:
                if entry not in accounts:
                    accounts.append(entry)

        # Filtrăm și structurăm conturile
        filtered = []
        for acc in accounts:
            if acc.get("UtilityAccountNumber"):
                filtered.append({
                    "AccountNumber": acc.get("AccountNumber"),
                    "UtilityAccountNumber": acc.get("UtilityAccountNumber"),
                    "Address": acc.get("Address"),
                    "IsDefaultAccount": acc.get("IsDefaultAccount"),
                    "CustomerName": acc.get("CustomerName"),
                })
        
        self._utility_accounts = filtered
        return resp

    # =========================================================================
    # Metode publice pentru accesarea datelor
    # =========================================================================

    def get_utility_accounts(self) -> List[Dict[str, Any]]:
        """Returnează lista de POD-uri (conturi)."""
        return self._utility_accounts

    def get_validate_user_login_data(self) -> List[Dict[str, Any]]:
        """Returnează datele brute din ValidateUserLogin."""
        return self._validate_user_login_data

    def get_raw_user_setting_data(self) -> Dict[str, Any]:
        """Returnează datele brute din GetUserSetting."""
        return self._raw_user_setting_data

    # =========================================================================
    # Endpoint-uri pentru facturi
    # =========================================================================

    def get_current_bill(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """
        Obține factura curentă pentru un POD.
        
        Args:
            utility_account_number: Număr cont utilitate (UAN)
            account_number: Număr cont (AN)
            
        Returns:
            Dict cu datele facturii curente
        """
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "IsBillPDF": "0",
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_URL_GET_BILL,
            payload=payload,
            headers=self._auth_header,
            descriere="GetBill - Factură curentă"
        )

    def get_bill_history(
        self,
        utility_account_number: str,
        account_number: str,
        from_date: str,
        to_date: str
    ) -> Dict[str, Any]:
        """
        Obține istoricul facturilor pentru un POD.
        
        Args:
            utility_account_number: Număr cont utilitate (UAN)
            account_number: Număr cont (AN)
            from_date: Data de început (format MM/DD/YYYY)
            to_date: Data de final (format MM/DD/YYYY)
            
        Returns:
            Dict cu istoricul facturilor
        """
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "FromDate": from_date,
            "ToDate": to_date
        }
        return self._post_request(
            API_URL_GET_BILL_HISTORY,
            payload=payload,
            headers=self._auth_header,
            descriere="GetBillingHistoryList - Istoric facturi"
        )

    # =========================================================================
    # Endpoint-uri pentru consum
    # =========================================================================

    def get_usage_generation(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """
        Obține istoricul de consum electric pentru un POD.
        
        Args:
            utility_account_number: Număr cont utilitate (UAN)
            account_number: Număr cont (AN)
            
        Returns:
            Dict cu istoricul de consum
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
            "IsNetUsage": False,
            "TimeOffset": "120",
            "UserType": "Residential",
            "DateToDaily": "",
            "UtilityId": 0,
            "IsLastTendays": False,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_URL_GET_USAGE_GENERATION,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUsageGeneration - Istoric consum"
        )

    # =========================================================================
    # Endpoint-uri pentru contor (index)
    # =========================================================================

    def get_multi_meter_details(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """
        Obține detalii despre contorul electric (meter) pentru un POD.
        
        Args:
            utility_account_number: Număr cont utilitate (UAN)
            account_number: Număr cont (AN)
            
        Returns:
            Dict cu detaliile contorului
        """
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_GET_MULTI_METER,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMultiMeter - Detalii contor"
        )

    def get_window_dates_enc(
        self, utility_account_number: str, account_number: str
    ) -> Dict[str, Any]:
        """
        Obține fereastra de date pentru citirea indexului.
        
        Args:
            utility_account_number: Număr cont utilitate (UAN)
            account_number: Număr cont (AN)
            
        Returns:
            Dict cu perioada în care se poate transmite indexul
        """
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_GET_MULTI_METER_READ_DATE,
            payload=payload,
            headers=self._auth_header,
            descriere="GetWindowDatesENC - Perioadă citire index"
        )

    def submit_meter_reading(
        self,
        utility_account_number: str,
        account_number: str,
        meter_number: str,
        meter_reading: float,
        reading_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trimite indexul contorului la Hidroelectrica.
        
        NOTĂ: Endpoint-ul exact trebuie confirmat prin interceptare.
        Acesta este un payload estimat bazat pe alte endpoint-uri.
        
        Args:
            utility_account_number: Număr cont utilitate (UAN)
            account_number: Număr cont (AN)
            meter_number: Număr contor
            meter_reading: Valoarea indexului de transmis
            reading_date: Data citirii (format MM/DD/YYYY), implicit azi
            
        Returns:
            Dict cu rezultatul operației (success/error + message)
        """
        if reading_date is None:
            reading_date = datetime.now().strftime("%m/%d/%Y")
        
        # ATENȚIE: Acest payload poate fi incomplet sau incorect
        # Trebuie verificat prin interceptarea aplicației mobile/web
        payload = {
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "MeterNumber": meter_number,
            "MeterReading": meter_reading,
            "ReadingDate": reading_date,
            "MeterType": "E",
            "LanguageCode": "RO",
        }
        
        try:
            resp = self._post_request(
                API_SUBMIT_METER_READING,
                payload=payload,
                headers=self._auth_header,
                descriere="SubmitMeterReading - Trimitere index"
            )
            
            # Verificăm dacă răspunsul indică succes
            if resp.get("result", {}).get("Status") == "Success":
                return {
                    "success": True,
                    "message": "Index trimis cu succes",
                    "data": resp
                }
            else:
                return {
                    "success": False,
                    "message": resp.get("result", {}).get("Message", "Eroare necunoscută"),
                    "data": resp
                }
                
        except Exception as err:
            _LOGGER.error("Eroare la trimiterea indexului: %s", err)
            return {
                "success": False,
                "message": str(err),
                "data": None
            }

    # =========================================================================
    # Metode interne
    # =========================================================================

    def _post_request(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        descriere: str = "Cerere nedefinită"
    ) -> Dict[str, Any]:
        """
        Execută o cerere POST către API.
        
        Gestionează automat retry în caz de 401 (session expirat).
        
        Args:
            url: URL-ul endpoint-ului
            payload: Date de trimis (JSON)
            headers: Header-e HTTP
            descriere: Descriere pentru logging
            
        Returns:
            Dict cu răspunsul JSON decodat
            
        Raises:
            Exception: Dacă răspunsul nu este 200 OK după retry
        """
        _LOGGER.debug("=== Cerere POST: %s (%s) ===", url, descriere)

        # Prima încercare
        response = self._session.post(url, json=payload, headers=headers, timeout=15)
        
        # Dacă primim 401, facem re-autentificare și reîncercăm
        if response.status_code == 401:
            _LOGGER.warning(
                "Primim 401 la %s, facem re-autentificare...", descriere
            )
            # Invalidăm session-ul curent
            self._session_token = None
            # Re-autentificare
            self.login_if_needed()

            # Verificăm dacă utilizatorul mai are acces la acest POD
            new_uan = payload.get("UtilityAccountNumber")
            if new_uan:
                has_uan = any(
                    a["UtilityAccountNumber"] == new_uan
                    for a in self._utility_accounts
                )
                if not has_uan:
                    raise Exception(
                        f"Utilizatorul nu mai are acces la POD-ul {new_uan}"
                    )

            # A doua încercare (retry)
            response = self._session.post(
                url, json=payload, headers=self._auth_header, timeout=15
            )

        # Verificăm status code-ul final
        if response.status_code != 200:
            _LOGGER.error(
                "Eroare la %s: Status %d - %s",
                descriere, response.status_code, response.text
            )
            raise Exception(
                f"Eroare la {descriere}: {response.status_code} - {response.text}"
            )

        return response.json()

    def close(self) -> None:
        """Închide sesiunea HTTP."""
        self._session.close()
        _LOGGER.debug("Sesiune iHidro închisă")


# Test local
if __name__ == "__main__":
    import json
    
    api = IhidroAPI("username", "password")
    try:
        api.login_if_needed()
        
        accounts = api.get_utility_accounts()
        print(f"\n=== Găsite {len(accounts)} POD-uri ===")
        for acc in accounts:
            print(json.dumps(acc, indent=2, ensure_ascii=False))
        
        # Test factură curentă pentru primul POD
        if accounts:
            pod = accounts[0]
            bill = api.get_current_bill(
                pod["UtilityAccountNumber"],
                pod["AccountNumber"]
            )
            print("\n=== Factură curentă ===")
            print(json.dumps(bill, indent=2, ensure_ascii=False))
            
    finally:
        api.close()
