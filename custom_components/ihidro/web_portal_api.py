"""
Client API pentru iHidro.ro Web Portal (pentru citire si trimitere index).

Hidroelectrica foloseste 2 sisteme API separate:
1. Mobile API (smartcmobile.com) - pentru facturi, balanta, plati
2. Web Portal API (ihidro.ro/portal) - pentru index contor

Acest modul implementeaza Web Portal API cu autentificare prin reCAPTCHA v3
rezolvat via 2captcha.com.

Fluxul de autentificare (din analiza JS default.js + CaptchaV3.js):
1. GET /portal/default.aspx → extrage CSRF token + session cookies
2. POST /portal/default.aspx/updateState → pregateste server-ul pentru login
3. Rezolva reCAPTCHA v3 via 2captcha (action='login', sitekey din pagina)
4. POST /portal/default.aspx/validateLogin → login cu token captcha
5. GET /portal/Dashboard.aspx → extrage CSRF token post-login
6. Foloseste CSRF token pentru API calls (GetAllPODBind, LoadW2UIGridData, etc.)
"""

import logging
import requests
import json
import time
import urllib3
from typing import Dict, Any, List, Optional
from datetime import datetime
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)

# reCAPTCHA constants
RECAPTCHA_SITE_KEY = "6LdWVgYfAAAAAOtv1JCMvOVYagKN_I7Tt8EMCBWx"
RECAPTCHA_ACTION = "login"
RECAPTCHA_MIN_SCORE = 0.9

# 2captcha polling
TWOCAPTCHA_SUBMIT_URL = "https://2captcha.com/in.php"
TWOCAPTCHA_RESULT_URL = "https://2captcha.com/res.php"
TWOCAPTCHA_POLL_INTERVAL = 5  # seconds
TWOCAPTCHA_MAX_ATTEMPTS = 36  # 36 * 5 = 180 seconds max


class TwoCaptchaError(Exception):
    """Error from 2captcha service."""
    pass


class WebPortalLoginError(Exception):
    """Error during web portal login."""
    pass


class IhidroWebPortalAPI:
    """Client API pentru iHidro.ro Web Portal."""

    def __init__(self, username: str, password: str, twocaptcha_api_key: str = ""):
        """Initializare client Web Portal API."""
        self._username = username
        self._password = password
        self._twocaptcha_api_key = twocaptcha_api_key

        # Sesiune si autentificare
        self._session = requests.Session()
        self._session.verify = False
        self._csrf_token = None
        self._is_authenticated = False

        # Set realistic browser headers
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;'
                      'q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ro-RO,ro;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })

        # Cache
        self._pods_cache: List[Dict[str, Any]] = []
        self._index_history_cache: Dict[str, Any] = {}

    # =========================================================================
    # 2captcha reCAPTCHA v3 solving
    # =========================================================================

    def _solve_recaptcha_v3(self, page_url: str) -> str:
        """
        Solve reCAPTCHA v3 using 2captcha.com API.

        Args:
            page_url: The URL of the page with reCAPTCHA

        Returns:
            The solved reCAPTCHA token string

        Raises:
            TwoCaptchaError: If solving fails
        """
        if not self._twocaptcha_api_key:
            raise TwoCaptchaError(
                "2captcha API key not configured. "
                "Add your 2captcha API key in the integration options."
            )

        _LOGGER.debug("Solving reCAPTCHA v3 via 2captcha (action=%s)...", RECAPTCHA_ACTION)

        # Submit task to 2captcha
        submit_params = {
            "key": self._twocaptcha_api_key,
            "method": "userrecaptcha",
            "googlekey": RECAPTCHA_SITE_KEY,
            "pageurl": page_url,
            "version": "v3",
            "action": RECAPTCHA_ACTION,
            "min_score": RECAPTCHA_MIN_SCORE,
            "json": 1,
        }

        try:
            resp = requests.post(TWOCAPTCHA_SUBMIT_URL, data=submit_params, timeout=30)
            result = resp.json()
        except Exception as err:
            raise TwoCaptchaError(f"Failed to submit to 2captcha: {err}") from err

        if result.get("status") != 1:
            error_text = result.get("request", "unknown error")
            if "ERROR_WRONG_USER_KEY" in str(error_text) or "ERROR_KEY_DOES_NOT_EXIST" in str(error_text):
                raise TwoCaptchaError(f"Invalid 2captcha API key: {error_text}")
            if "ERROR_ZERO_BALANCE" in str(error_text):
                raise TwoCaptchaError(f"2captcha balance is zero: {error_text}")
            raise TwoCaptchaError(f"2captcha submit error: {error_text}")

        task_id = result["request"]
        _LOGGER.debug("2captcha task submitted: %s", task_id)

        # Poll for result
        for attempt in range(TWOCAPTCHA_MAX_ATTEMPTS):
            time.sleep(TWOCAPTCHA_POLL_INTERVAL)

            try:
                resp = requests.get(TWOCAPTCHA_RESULT_URL, params={
                    "key": self._twocaptcha_api_key,
                    "action": "get",
                    "id": task_id,
                    "json": 1,
                }, timeout=30)
                result = resp.json()
            except Exception as err:
                _LOGGER.warning("2captcha poll error (attempt %d): %s", attempt + 1, err)
                continue

            if result.get("status") == 1:
                token = result["request"]
                _LOGGER.debug(
                    "2captcha solved (attempt %d, token length: %d)",
                    attempt + 1, len(token)
                )
                return token

            request_text = str(result.get("request", ""))
            if "CAPCHA_NOT_READY" in request_text:
                _LOGGER.debug("2captcha not ready (attempt %d/%d)", attempt + 1, TWOCAPTCHA_MAX_ATTEMPTS)
                continue

            # Any other response is an error
            raise TwoCaptchaError(f"2captcha error: {request_text}")

        raise TwoCaptchaError("2captcha timeout: solving took too long")

    # =========================================================================
    # Authentication
    # =========================================================================

    def login(self) -> None:
        """
        Autentificare la Web Portal iHidro cu reCAPTCHA v3 via 2captcha.

        Fluxul complet:
        1. GET /portal/default.aspx → CSRF token + cookies
        2. POST updateState → pregateste serverul
        3. 2captcha → rezolva reCAPTCHA v3
        4. POST validateLogin → autentificare
        5. GET Dashboard.aspx → CSRF token post-login
        """
        _LOGGER.info("Web Portal: Starting login for '%s'", self._username)

        if not self._twocaptcha_api_key:
            raise WebPortalLoginError(
                "2captcha API key required for Web Portal login. "
                "Configure it in integration settings."
            )

        # Reset session
        self._session.cookies.clear()
        self._csrf_token = None
        self._is_authenticated = False

        page_url = "https://ihidro.ro/portal/default.aspx"

        # Step 1: GET login page
        _LOGGER.debug("Step 1: GET login page")
        try:
            resp = self._session.get(page_url, allow_redirects=True, timeout=30)
            resp.raise_for_status()
        except Exception as err:
            raise WebPortalLoginError(f"Failed to load login page: {err}") from err

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Extract CSRF token
        csrf_field = soup.find('input', {'id': 'hdnCSRFToken'})
        if not csrf_field or not csrf_field.get('value'):
            raise WebPortalLoginError("Could not find CSRF token on login page")
        pre_login_csrf = csrf_field['value']
        _LOGGER.debug("Pre-login CSRF: %s...", str(pre_login_csrf)[:30])

        # Extract captcha key from page (should match our constant)
        captcha_field = soup.find('input', {'id': 'hdncaptchakey'})
        page_site_key = captcha_field['value'] if captcha_field else RECAPTCHA_SITE_KEY
        _LOGGER.debug("Captcha site key: %s", page_site_key)

        _LOGGER.debug("Session cookies after page load: %s", list(self._session.cookies.keys()))

        # Step 2: POST updateState
        _LOGGER.debug("Step 2: POST updateState")
        ajax_headers = {
            'Content-Type': 'application/json; charset=UTF-8',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://ihidro.ro',
            'Referer': page_url,
        }

        try:
            resp = self._session.post(
                "https://ihidro.ro/portal/default.aspx/updateState",
                json={},
                headers=ajax_headers,
                timeout=30,
            )
            _LOGGER.debug("updateState response: %s %s", resp.status_code, resp.text[:100])
        except Exception as err:
            _LOGGER.warning("updateState failed (non-fatal): %s", err)

        # Step 3: Solve reCAPTCHA v3
        _LOGGER.info("Web Portal: Solving reCAPTCHA v3 via 2captcha...")
        captcha_token = self._solve_recaptcha_v3(page_url)

        # Step 4: POST validateLogin
        _LOGGER.debug("Step 4: POST validateLogin")
        login_payload = {
            "username": self._username,
            "password": self._password,
            "rememberme": False,
            "calledFrom": "LN",
            "ExternalLoginId": "",
            "LoginMode": "1",
            "utilityAcountNumber": "",
            "token": captcha_token,
            "isEdgeBrowser": False,
        }

        login_headers = {
            'Content-Type': 'application/json; charset=UTF-8',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://ihidro.ro',
            'Referer': page_url,
            'csrftoken': pre_login_csrf,
        }

        try:
            resp = self._session.post(
                "https://ihidro.ro/portal/default.aspx/validateLogin",
                json=login_payload,
                headers=login_headers,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as err:
            raise WebPortalLoginError(f"validateLogin request failed: {err}") from err

        _LOGGER.debug("validateLogin response (%d bytes): %s", len(resp.text), resp.text[:300])

        # Parse login response
        try:
            login_result = resp.json()
            d_value = login_result.get('d', '')

            if isinstance(d_value, str):
                parsed = json.loads(d_value)
            else:
                parsed = d_value

            # Check for errors
            if isinstance(parsed, dict):
                if 'dtException' in parsed:
                    exc = parsed['dtException']
                    msg = exc[0].get('MessageInformation', 'Unknown error') if exc else 'Unknown'
                    raise WebPortalLoginError(f"Login exception: {msg}")

                if 'dtResponse' in parsed:
                    dt_resp = parsed['dtResponse']
                    if dt_resp and dt_resp[0].get('Status') == '0':
                        msg = dt_resp[0].get('Message', 'Unknown error')
                        if 'Invalid Captcha' in msg:
                            raise WebPortalLoginError(
                                "reCAPTCHA token rejected by iHidro server. "
                                "The 2captcha token was not accepted. "
                                "This may be a temporary issue - try again later."
                            )
                        raise WebPortalLoginError(f"Login failed: {msg}")

            # Check for successful login (parsed is a list with STATUS != 0)
            if isinstance(parsed, list) and len(parsed) > 0:
                first = parsed[0]
                status = first.get('STATUS')
                message = first.get('Message', '')

                if status == 0 or status == '0':
                    if message:
                        raise WebPortalLoginError(f"Login failed: {message}")
                    else:
                        raise WebPortalLoginError(
                            "Login failed with empty message. "
                            "Captcha may have passed but credentials rejected."
                        )

                _LOGGER.info("Web Portal: validateLogin succeeded (STATUS=%s)", status)

        except (json.JSONDecodeError, KeyError, TypeError) as err:
            _LOGGER.warning("Could not fully parse login response: %s", err)
            # Continue anyway - we'll check Dashboard access next

        # Step 5: GET Dashboard to extract post-login CSRF
        _LOGGER.debug("Step 5: GET Dashboard for post-login CSRF")
        try:
            resp = self._session.get(
                "https://ihidro.ro/portal/Dashboard.aspx",
                headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Referer': page_url,
                },
                allow_redirects=True,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as err:
            raise WebPortalLoginError(f"Failed to access Dashboard: {err}") from err

        # Check if we got redirected back to login
        if 'txtLogin' in resp.text and 'btnlogin' in resp.text:
            raise WebPortalLoginError(
                "Login appeared to succeed but Dashboard redirected to login page. "
                "Session may not have been established."
            )

        # Extract post-login CSRF token
        soup = BeautifulSoup(resp.text, 'html.parser')
        csrf_field = soup.find('input', {'id': 'hdnCSRFToken'})

        if csrf_field and csrf_field.get('value'):
            self._csrf_token = csrf_field['value']
            _LOGGER.debug("Post-login CSRF: %s...", str(self._csrf_token)[:30])
        else:
            _LOGGER.warning("No CSRF token found on Dashboard - API calls may fail")

        self._is_authenticated = True
        _LOGGER.info(
            "Web Portal: Login successful for '%s' (cookies: %s)",
            self._username, list(self._session.cookies.keys())
        )

    def login_if_needed(self) -> None:
        """Login only if not already authenticated."""
        if self._is_authenticated:
            _LOGGER.debug("Web Portal: Already authenticated, skipping login.")
            return
        self.login()

    # =========================================================================
    # API Methods
    # =========================================================================

    def get_all_pods(self) -> List[Dict[str, Any]]:
        """
        Obtine lista tuturor POD-urilor utilizatorului.

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

        _LOGGER.debug("Web Portal: Getting POD list...")

        try:
            response = self._post_json(
                "/portal/IndexHistory.aspx/GetAllPODBind",
                {}
            )

            d_value = response.get('d', '{}')

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
            _LOGGER.info("Web Portal: Found %d POD(s)", len(pods))

            return pods

        except Exception as err:
            _LOGGER.error("Error getting PODs: %s", err, exc_info=True)
            return []

    def get_index_history(self, installation: str, pod: str) -> List[Dict[str, Any]]:
        """
        Obtine istoricul indexului pentru un POD.

        Endpoint: POST /portal/SelfMeterReading.aspx/LoadW2UIGridData
                  (same endpoint used in SelfMeterReading page)

        Args:
            installation: Numar installation (ex: "4000801506")
            pod: Numar POD (ex: "EMO4307667")

        Returns:
            List[Dict] cu istoric index, sortat descrescator dupa data
        """
        self.login_if_needed()

        _LOGGER.debug("Web Portal: Getting index history for POD %s...", pod)

        try:
            response = self._post_json(
                "/portal/SelfMeterReading.aspx/LoadW2UIGridData",
                {
                    "installation": installation,
                    "podvalue": pod,
                }
            )

            data_str = response.get('d', '[]')
            if isinstance(data_str, str):
                history = json.loads(data_str)
            else:
                history = data_str if isinstance(data_str, list) else []

            # Sort by date descending
            history.sort(key=lambda x: self._parse_date(x.get('Date', '')), reverse=True)

            cache_key = f"{installation}_{pod}"
            self._index_history_cache[cache_key] = history
            _LOGGER.info("Web Portal: Found %d index records for POD %s", len(history), pod)

            return history

        except Exception as err:
            _LOGGER.error("Error getting index history for POD %s: %s", pod, err)
            return []

    def get_latest_meter_reading(self, installation: str, pod: str) -> Optional[Dict[str, Any]]:
        """
        Obtine ultimul index inregistrat pentru un POD.

        Args:
            installation: Numar installation
            pod: Numar POD

        Returns:
            Dict cu ultimul index sau None
        """
        history = self.get_index_history(installation, pod)

        if not history:
            return None

        latest = history[0]

        return {
            "index": latest.get("Index"),
            "date": latest.get("Date"),
            "type": latest.get("ReadingType"),
            "counter_series": latest.get("CounterSeries"),
            "registers": latest.get("Registers", "1.8.0"),
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
        additional_data: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Trimite indexul contorului la Hidroelectrica.

        Endpoint: POST /portal/SelfMeterReading.aspx/SubmitSelfMeterReading

        Payload format confirmed from HAR capture (ihidro.ro2.har).

        Args:
            pod: Numar POD (ex: "EMO4307667")
            installation: Numar installation (ex: "4000801506")
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

        # Validation
        if new_reading < prev_reading:
            return {
                "success": False,
                "message": f"New reading ({new_reading}) cannot be less than previous ({prev_reading})",
                "data": None,
            }

        # Default meter data (can be overridden via additional_data)
        defaults = {
            "registerCat": "1.8.0",
            "distributor": "DELGAZ GRID",
            "meterInterval": "lunar",
            "supplier": "HE",
            "distCustomer": "",
            "distCustomerId": "",
            "distContract": "",
            "distContractDate": "",
        }

        if additional_data:
            defaults.update(additional_data)

        # Build payload (exact format from HAR capture)
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
                    "newmeterread": str(new_reading),
                }]
            },
            "installation_number": installation,
            "pod_value": pod,
        }

        _LOGGER.info(
            "Web Portal: Submitting reading %d for POD %s (prev: %d, date: %s)",
            new_reading, pod, prev_reading, reading_date,
        )

        try:
            # Optional: call GetMeterValue first (validation step from HAR)
            try:
                self._post_json(
                    "/portal/SelfMeterReading.aspx/GetMeterValue",
                    {
                        "objSubmitMeterReadProxy": {
                            "UsageSelfMeterReadEntity": [{
                                **payload["objSubmitMeterReadProxy"]["UsageSelfMeterReadEntity"][0],
                                "newmeterread": "0",
                            }]
                        },
                        "installation_number": installation,
                        "pod_value": pod,
                    }
                )
            except Exception:
                _LOGGER.debug("GetMeterValue pre-check failed (non-fatal)")

            # Actual submit
            response = self._post_json(
                "/portal/SelfMeterReading.aspx/SubmitSelfMeterReading",
                payload,
            )

            result = response.get('d', '')

            if isinstance(result, str) and ('success' in result.lower() or result == ''):
                _LOGGER.info("Web Portal: Meter reading submitted successfully!")
                return {
                    "success": True,
                    "message": "Meter reading submitted successfully",
                    "data": response,
                }
            else:
                _LOGGER.warning("Web Portal: Unexpected submit response: %s", result)
                return {
                    "success": False,
                    "message": str(result) or "Unknown error",
                    "data": response,
                }

        except Exception as err:
            _LOGGER.error("Error submitting meter reading: %s", err)
            return {
                "success": False,
                "message": str(err),
                "data": None,
            }

    # =========================================================================
    # Internal methods
    # =========================================================================

    def _post_json(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a POST JSON request to the Web Portal.

        Args:
            endpoint: Path (ex: "/portal/IndexHistory.aspx/GetAllPODBind")
            payload: JSON data to send

        Returns:
            Dict with decoded JSON response
        """
        url = f"https://ihidro.ro{endpoint}"

        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "isajax": "1",
            "Origin": "https://ihidro.ro",
            "Referer": "https://ihidro.ro/portal/SelfMeterReading.aspx",
        }

        if self._csrf_token:
            headers["csrftoken"] = self._csrf_token

        _LOGGER.debug("Web Portal POST: %s", endpoint)

        response = self._session.post(url, json=payload, headers=headers, timeout=15)

        # Handle 401 - re-authenticate
        if response.status_code == 401:
            _LOGGER.warning("Web Portal: Got 401, re-authenticating...")
            self._is_authenticated = False
            self.login()

            if self._csrf_token:
                headers["csrftoken"] = self._csrf_token

            response = self._session.post(url, json=payload, headers=headers, timeout=15)

        if response.status_code != 200:
            _LOGGER.error(
                "Web Portal error: %s %s - %s",
                response.status_code, endpoint, response.text[:200],
            )
            raise Exception(
                f"Web Portal {endpoint}: {response.status_code} - {response.text[:200]}"
            )

        return response.json()

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Parse date from DD/MM/YYYY format."""
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except (ValueError, TypeError):
            return datetime.min

    def close(self) -> None:
        """Close HTTP session."""
        self._session.close()
        _LOGGER.debug("Web Portal session closed")
