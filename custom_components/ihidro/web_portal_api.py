"""
Client API pentru iHidro.ro Web Portal (pentru citire și trimitere index).

Hidroelectrica folosește 2 sisteme API separate:
1. Mobile API (smartcmobile.com) - pentru facturi, balanță, plăți
2. Web Portal API (ihidro.ro/portal) - pentru index contor

Acest modul implementează Web Portal API pentru:
- Obținere listă POD-uri (cu installation, contractAccountID)
- Obținere istoric index (pentru senzor meter reading)
- Trimitere index contor
"""

import logging
import requests
import json
import urllib3
from typing import Dict, Any, List, Optional
from datetime import datetime
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)


class IhidroWebPortalAPI:
    """Client API pentru iHidro.ro Web Portal."""

    def __init__(self, username: str, password: str):
        """Inițializare client Web Portal API."""
        self._username = username
        self._password = password
        
        # Sesiune și autentificare
        self._session = requests.Session()
        self._session.verify = False
        self._csrf_token = None
        self._is_authenticated = False
        
        # Set realistic browser headers
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ro-RO,ro;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        })
        
        # Cache pentru date POD
        self._pods_cache = []
        self._index_history_cache = {}

    def login(self) -> None:
        """
        Autentificare la Web Portal iHidro.
        
        Flow:
        1. GET /portal/Login.aspx - obține pagina de login
        2. POST credentials - autentificare
        3. GET pagină autentificată pentru a obține CSRF token
        4. Extrage csrf token din pagină
        """
        _LOGGER.debug("=== Web Portal: Începem autentificarea pentru '%s' ===", self._username)
        
        try:
            # Pas 1: GET pagina de login pentru a obține cookies inițiale
            login_url = "https://ihidro.ro/portal/Login.aspx"
            response = self._session.get(login_url, timeout=15)
            
            if response.status_code != 200:
                raise Exception(f"Eroare la accesarea paginii de login: {response.status_code}")
            
            # Parsăm HTML pentru a găsi __VIEWSTATE și __EVENTVALIDATION
            soup = BeautifulSoup(response.text, 'html.parser')
            viewstate = soup.find('input', {'name': '__VIEWSTATE'})
            eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})
            viewstate_generator = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})
            
            # Pas 2: POST credentials (ASP.NET form authentication)
            login_data = {
                '__VIEWSTATE': viewstate['value'] if viewstate else '',
                '__VIEWSTATEGENERATOR': viewstate_generator['value'] if viewstate_generator else '',
                '__EVENTVALIDATION': eventvalidation['value'] if eventvalidation else '',
                'ctl00$ContentPlaceHolder1$txtUserName': self._username,
                'ctl00$ContentPlaceHolder1$txtPassword': self._password,
                'ctl00$ContentPlaceHolder1$btnLogin': 'Login',
            }
            
            response = self._session.post(login_url, data=login_data, timeout=15, allow_redirects=True)
            
            # Verificăm dacă am fost redirecționați (sign of success)
            if response.status_code not in [200, 302]:
                raise Exception(f"Eroare la autentificare: {response.status_code}")
            
            # Verificăm dacă am primit eroare de autentificare
            if 'Invalid username or password' in response.text or 'Utilizator sau parolă invalidă' in response.text:
                raise Exception("Credențiale invalide")
            
            # Pas 3: GET o pagină autentificată pentru a obține CSRF token
            # IndexHistory.aspx este o pagină bună pentru asta
            index_url = "https://ihidro.ro/portal/IndexHistory.aspx"
            response = self._session.get(index_url, timeout=15)
            
            if response.status_code != 200:
                _LOGGER.warning("Nu am putut accesa IndexHistory.aspx după autentificare")
            
            # Pas 4: Extragem CSRF token din pagină
            # Token-ul poate fi în JavaScript sau într-un hidden input
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Căutăm în toate scripturile
            csrf_token = None
            for script in soup.find_all('script'):
                if script.string and 'csrftoken' in script.string.lower():
                    # Găsim token-ul cu regex
                    import re
                    matches = re.findall(r'csrftoken["\']?\s*[:=]\s*["\']([A-Za-z0-9+/=]+)["\']', script.string)
                    if matches:
                        csrf_token = matches[0]
                        break
            
            # Sau în input hidden
            if not csrf_token:
                csrf_input = soup.find('input', {'name': 'csrftoken'}) or soup.find('input', {'id': 'csrftoken'})
                if csrf_input:
                    csrf_token = csrf_input.get('value', '')
            
            # Sau în meta tag
            if not csrf_token:
                csrf_meta = soup.find('meta', {'name': 'csrf-token'}) or soup.find('meta', {'name': 'csrftoken'})
                if csrf_meta:
                    csrf_token = csrf_meta.get('content', '')
            
            self._csrf_token = csrf_token or ''
            
            # Pentru ASP.NET, cookie-ul de autentificare este suficient în multe cazuri
            # Verificăm dacă avem cookie de sesiune .ASPXAUTH
            aspx_auth = self._session.cookies.get('.ASPXAUTH') or self._session.cookies.get('ASP.NET_SessionId')
            
            if aspx_auth:
                _LOGGER.debug("Avem cookie de autentificare ASP.NET")
            
            _LOGGER.debug("CSRF Token: %s", self._csrf_token[:20] if self._csrf_token else "None")
            _LOGGER.debug("Cookies: %s", list(self._session.cookies.keys()))
            
            self._is_authenticated = True
            _LOGGER.info("=== Web Portal: Autentificare reușită ===")
            
        except Exception as err:
            _LOGGER.error("Eroare la autentificare Web Portal: %s", err, exc_info=True)
            self._is_authenticated = False
            raise

    def login_if_needed(self) -> None:
        """Face login doar dacă nu suntem deja autentificați."""
        if self._is_authenticated:
            _LOGGER.debug("Web Portal: Deja autentificat, nu mai facem login.")
            return
        self.login()

    def get_all_pods(self) -> List[Dict[str, Any]]:
        """
        Obține lista tuturor POD-urilor utilizatorului.
        
        Endpoint: POST /portal/IndexHistory.aspx/GetAllPODBind
        
        Returns:
            List[Dict] cu format:
            [
                {
                    "accountID": "9900665679",
                    "installation": "4000801506",
                    "contractAccountID": "8001067827",
                    "pod": "EMO4307667"
                }
            ]
        """
        self.login_if_needed()
        
        _LOGGER.debug("Web Portal: Obținem lista POD-urilor...")
        
        try:
            response = self._post_json(
                "/portal/IndexHistory.aspx/GetAllPODBind",
                {}
            )
            
            _LOGGER.debug("Raw response from GetAllPODBind: %s", response)
            
            # Răspunsul vine în format: {"d": "{\"Data\":[...]}"}
            # SAU poate fi direct: {"d": [...]}
            d_value = response.get('d', '{}')
            
            # Verificăm dacă d este string sau deja un dict/list
            if isinstance(d_value, str):
                data = json.loads(d_value)
                if isinstance(data, dict):
                    pods = data.get('Data', [])
                elif isinstance(data, list):
                    pods = data
                else:
                    pods = []
            elif isinstance(d_value, dict):
                pods = d_value.get('Data', [])
            elif isinstance(d_value, list):
                pods = d_value
            else:
                pods = []
            
            self._pods_cache = pods
            _LOGGER.info("Web Portal: Găsite %d POD-uri", len(pods))
            
            return pods
            
        except Exception as err:
            _LOGGER.error("Eroare la obținerea POD-urilor: %s", err, exc_info=True)
            return []

    def get_index_history(self, installation: str, pod: str) -> List[Dict[str, Any]]:
        """
        Obține istoricul indexului pentru un POD.
        
        Endpoint: POST /portal/IndexHistory.aspx/LoadW2UIGridData
        
        Args:
            installation: Număr installation (ex: "4000801506")
            pod: Număr POD (ex: "EMO4307667")
            
        Returns:
            List[Dict] cu istoric index, sortat descrescător după dată:
            [
                {
                    "POD": "EMO4307667",
                    "CounterSeries": "1702233822626815",
                    "RegisterDescription": "Energie Activă",
                    "Registers": "1.8.0",
                    "ReadingType": "Regularizare",
                    "Date": "30/06/2025",
                    "Index": 4132
                }
            ]
        """
        self.login_if_needed()
        
        cache_key = f"{installation}_{pod}"
        _LOGGER.debug("Web Portal: Obținem istoric index pentru POD %s...", pod)
        
        try:
            response = self._post_json(
                "/portal/IndexHistory.aspx/LoadW2UIGridData",
                {
                    "installation": installation,
                    "podvalue": pod
                }
            )
            
            # Răspunsul vine în format: {"d": "[{...}, {...}]"}
            data_str = response.get('d', '[]')
            history = json.loads(data_str)
            
            # Sortăm după dată (descrescător - cel mai recent primul)
            history.sort(key=lambda x: self._parse_date(x.get('Date', '')), reverse=True)
            
            self._index_history_cache[cache_key] = history
            _LOGGER.info("Web Portal: Găsite %d înregistrări istoric pentru POD %s", len(history), pod)
            
            return history
            
        except Exception as err:
            _LOGGER.error("Eroare la obținerea istoric index pentru POD %s: %s", pod, err)
            return []

    def get_latest_meter_reading(self, installation: str, pod: str) -> Optional[Dict[str, Any]]:
        """
        Obține ultimul index înregistrat pentru un POD.
        
        Args:
            installation: Număr installation
            pod: Număr POD
            
        Returns:
            Dict cu ultimul index sau None dacă nu există
        """
        history = self.get_index_history(installation, pod)
        
        if not history:
            return None
        
        # Primul element este cel mai recent (sortare descrescătoare)
        latest = history[0]
        
        return {
            "index": latest.get("Index"),
            "date": latest.get("Date"),
            "type": latest.get("ReadingType"),
            "counter_series": latest.get("CounterSeries"),
            "registers": latest.get("Registers", "1.8.0")
        }

    def submit_meter_reading(
        self,
        pod: str,
        installation: str,
        utility_account_number: str,
        counter_series: str,
        prev_reading: int,
        new_reading: int,
        reading_date: Optional[str] = None,
        additional_data: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Trimite indexul contorului la Hidroelectrica.
        
        Endpoint: POST /portal/SelfMeterReading.aspx/SubmitSelfMeterReading
        
        Args:
            pod: Număr POD (ex: "EMO4307667")
            installation: Număr installation (ex: "4000801506")
            utility_account_number: Contract Account ID (ex: "8001067827")
            counter_series: Seria contorului (ex: "1702233822626815")
            prev_reading: Ultimul index declarat
            new_reading: Noul index (trebuie >= prev_reading)
            reading_date: Data citirii (format DD/MM/YYYY), implicit azi
            additional_data: Date suplimentare (distributor, customer, etc.)
            
        Returns:
            Dict cu rezultat: {"success": bool, "message": str, "data": Any}
        """
        self.login_if_needed()
        
        if reading_date is None:
            reading_date = datetime.now().strftime("%d/%m/%Y")
        
        # Validare
        if new_reading < prev_reading:
            return {
                "success": False,
                "message": f"Indexul nou ({new_reading}) nu poate fi mai mic decât cel anterior ({prev_reading})",
                "data": None
            }
        
        # Date implicite (pot fi suprascrise prin additional_data)
        defaults = {
            "registerCat": "1.8.0",
            "distributor": "DELGAZ GRID",
            "meterInterval": "lunar",
            "supplier": "HE",
            "distCustomer": "",
            "distCustomerId": "",
            "distContract": "",
            "distContractDate": ""
        }
        
        # Merge cu datele furnizate
        if additional_data:
            defaults.update(additional_data)
        
        payload = {
            "objSubmitMeterReadProxy": {
                "UsageSelfMeterReadEntity": [{
                    "POD": pod,
                    "SerialNumber": counter_series,
                    "NewMeterReadDate": reading_date,
                    "registerCat": defaults["registerCat"],
                    "distributor": defaults["distributor"],
                    "meterInterval": defaults["meterInterval"],
                    "supplier": defaults["supplier"],
                    "distCustomer": defaults["distCustomer"],
                    "distCustomerId": defaults["distCustomerId"],
                    "distContract": defaults["distContract"],
                    "distContractDate": defaults["distContractDate"],
                    "UtilityAccountNumber": utility_account_number,
                    "prevMRResult": str(prev_reading),
                    "newmeterread": str(new_reading)
                }]
            },
            "installation_number": installation,
            "pod_value": pod
        }
        
        _LOGGER.info(
            "Web Portal: Trimitem index %d pentru POD %s (anterior: %d)",
            new_reading, pod, prev_reading
        )
        
        try:
            response = self._post_json(
                "/portal/SelfMeterReading.aspx/SubmitSelfMeterReading",
                payload
            )
            
            # Răspunsul vine în format: {"d": "success"} sau mesaj eroare
            result = response.get('d', '')
            
            if result == 'success' or 'success' in result.lower():
                _LOGGER.info("Web Portal: Index trimis cu succes!")
                return {
                    "success": True,
                    "message": "Index trimis cu succes",
                    "data": response
                }
            else:
                _LOGGER.warning("Web Portal: Răspuns neașteptat: %s", result)
                return {
                    "success": False,
                    "message": result or "Eroare necunoscută",
                    "data": response
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

    def _post_json(
        self,
        endpoint: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execută o cerere POST JSON către Web Portal.
        
        Args:
            endpoint: Calea endpoint-ului (ex: "/portal/IndexHistory.aspx/GetAllPODBind")
            payload: Date de trimis (JSON)
            
        Returns:
            Dict cu răspunsul JSON decodat
        """
        url = f"https://ihidro.ro{endpoint}"
        
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "isajax": "1",
            "Origin": "https://ihidro.ro",
            "Referer": f"https://ihidro.ro{endpoint.rsplit('/', 1)[0]}.aspx" if '/' in endpoint else "https://ihidro.ro/portal/",
        }
        
        # Adăugăm CSRF token dacă există
        if self._csrf_token:
            headers["csrftoken"] = self._csrf_token
        
        _LOGGER.debug("=== Web Portal POST: %s ===", endpoint)
        _LOGGER.debug("CSRF Token in request: %s", self._csrf_token[:20] if self._csrf_token else "None")
        
        response = self._session.post(url, json=payload, headers=headers, timeout=15)
        
        # Gestionare 401 - re-autentificare
        if response.status_code == 401:
            _LOGGER.warning("Web Portal: Primim 401, facem re-autentificare...")
            self._is_authenticated = False
            self.login()
            
            # Update headers with new CSRF token
            if self._csrf_token:
                headers["csrftoken"] = self._csrf_token
            
            # Retry cu sesiune nouă
            response = self._session.post(url, json=payload, headers=headers, timeout=15)
        
        if response.status_code != 200:
            _LOGGER.error("Web Portal response error: %s - %s", response.status_code, response.text[:200])
            raise Exception(
                f"Eroare Web Portal {endpoint}: {response.status_code} - {response.text[:200]}"
            )
        
        return response.json()

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """
        Parsează data din format DD/MM/YYYY.
        
        Args:
            date_str: Data în format "DD/MM/YYYY"
            
        Returns:
            datetime object sau datetime.min dacă eroare
        """
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except (ValueError, TypeError):
            return datetime.min

    def close(self) -> None:
        """Închide sesiunea HTTP."""
        self._session.close()
        _LOGGER.debug("Sesiune Web Portal închisă")


# Test local
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python web_portal_api.py <username> <password>")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    
    api = IhidroWebPortalAPI(username, password)
    try:
        api.login()
        
        # Test 1: Get PODs
        pods = api.get_all_pods()
        print(f"\n=== Găsite {len(pods)} POD-uri ===")
        for pod in pods:
            print(json.dumps(pod, indent=2, ensure_ascii=False))
        
        # Test 2: Get index history pentru primul POD
        if pods:
            pod_data = pods[0]
            history = api.get_index_history(
                pod_data["installation"],
                pod_data["pod"]
            )
            print(f"\n=== Istoric index pentru POD {pod_data['pod']} ===")
            for entry in history[:5]:  # Primele 5
                print(json.dumps(entry, indent=2, ensure_ascii=False))
            
            # Test 3: Get latest reading
            latest = api.get_latest_meter_reading(
                pod_data["installation"],
                pod_data["pod"]
            )
            print(f"\n=== Ultimul index ===")
            print(json.dumps(latest, indent=2, ensure_ascii=False))
            
    finally:
        api.close()
