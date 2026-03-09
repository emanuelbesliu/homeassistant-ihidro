"""
Client API pentru iHidro.ro Web Portal (prin ihidro-browser microservice).

Hidroelectrica foloseste 2 sisteme API separate:
1. Mobile API (smartcmobile.com) - pentru facturi, balanta, plati
2. Web Portal API (ihidro.ro/portal) - pentru index contor

Portalul Web foloseste CSRF tokens dinamice si reCAPTCHA v3, care necesita
un browser real. Acest modul deleaga toate operatiunile Web Portal catre
microserviciul ihidro-browser (bazat pe nodriver).

Fluxul:
1. POST /scrape-all → ihidro-browser face login + extrage PODs + index history
2. POST /submit-reading → ihidro-browser face login + trimite indexul
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Timeout for browser service requests (login + scrape can take up to 60s)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=120)


class BrowserServiceError(Exception):
    """Error communicating with ihidro-browser service."""
    pass


class WebPortalLoginError(Exception):
    """Error during web portal login (via browser service)."""
    pass


class IhidroWebPortalAPI:
    """Client API pentru iHidro.ro Web Portal via ihidro-browser microservice."""

    def __init__(
        self,
        username: str,
        password: str,
        browser_service_url: str = "",
    ):
        """Initializare client Web Portal API.

        Args:
            username: iHidro username
            password: iHidro password
            browser_service_url: URL of the ihidro-browser microservice
        """
        self._username = username
        self._password = password
        self._browser_service_url = browser_service_url.rstrip("/")

        # Cache
        self._pods_cache: List[Dict[str, Any]] = []
        self._index_history_cache: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def is_configured(self) -> bool:
        """Check if the browser service URL is configured."""
        return bool(self._browser_service_url)

    async def check_health(self) -> bool:
        """Check if the ihidro-browser service is healthy.

        Returns:
            True if healthy, False otherwise
        """
        if not self._browser_service_url:
            return False

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(f"{self._browser_service_url}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("status") == "ok"
        except Exception as err:
            _LOGGER.debug("Browser service health check failed: %s", err)

        return False

    async def scrape_all(self) -> Dict[str, Any]:
        """
        Login and fetch all POD data via the browser service.

        Calls POST /scrape-all on ihidro-browser.

        Returns:
            Dict with keys: pods (list of pod data with index history)
        """
        if not self._browser_service_url:
            raise BrowserServiceError(
                "Browser service URL not configured. "
                "Set the ihidro-browser service URL in integration settings."
            )

        _LOGGER.info("Web Portal: Starting scrape-all via browser service...")

        payload = {
            "username": self._username,
            "password": self._password,
        }

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.post(
                    f"{self._browser_service_url}/scrape-all",
                    json=payload,
                ) as resp:
                    data = await resp.json()

                    if resp.status == 401:
                        raise WebPortalLoginError(
                            data.get("message", "Login failed")
                        )

                    if resp.status != 200:
                        raise BrowserServiceError(
                            f"Browser service error ({resp.status}): "
                            f"{data.get('message', 'Unknown error')}"
                        )

                    if data.get("status") != "ok":
                        raise BrowserServiceError(
                            f"Browser service returned error: "
                            f"{data.get('message', 'Unknown error')}"
                        )

        except aiohttp.ClientError as err:
            raise BrowserServiceError(
                f"Cannot connect to ihidro-browser service at "
                f"{self._browser_service_url}: {err}"
            ) from err

        # Update caches
        pods_data = data.get("pods", [])
        self._pods_cache = []
        self._index_history_cache = {}

        for pod_entry in pods_data:
            pod_info = pod_entry.get("pod_info", {})
            history = pod_entry.get("index_history", [])

            self._pods_cache.append(pod_info)

            pod_value = pod_info.get("pod", "")
            installation = pod_info.get("installation", "")
            if pod_value and installation:
                cache_key = f"{installation}_{pod_value}"
                self._index_history_cache[cache_key] = history

        _LOGGER.info(
            "Web Portal: Scrape complete — %d PODs fetched", len(self._pods_cache)
        )

        return data

    def get_cached_pods(self) -> List[Dict[str, Any]]:
        """Get cached POD list (from last scrape_all)."""
        return self._pods_cache

    def get_cached_index_history(
        self, installation: str, pod: str
    ) -> List[Dict[str, Any]]:
        """Get cached index history for a POD (from last scrape_all)."""
        cache_key = f"{installation}_{pod}"
        return self._index_history_cache.get(cache_key, [])

    def get_cached_latest_reading(
        self, installation: str, pod: str
    ) -> Optional[Dict[str, Any]]:
        """Get the latest meter reading from cache.

        The browser service returns raw iHidro API fields:
            PrevMRResult  — meter index value
            prevMRDate    — date string like "12/21/2025 12:00:00 AM"
            prevMRRsn     — reading reason code (e.g. "02")
            prevMRCat     — reading category (e.g. "01")
            SerialNumber  — meter serial number
            Registers     — register code (e.g. "1.8.0")
            Registersdesc — human-readable register name
        """
        history = self.get_cached_index_history(installation, pod)
        if not history:
            return None

        # Sort by date descending and return the first
        from datetime import datetime

        def parse_date(date_str: str) -> datetime:
            """Parse iHidro date which is US format with optional time component.

            Examples: "12/21/2025 12:00:00 AM", "01/15/2026"
            """
            if not date_str:
                return datetime.min
            try:
                # Try full datetime format first
                return datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
            except (ValueError, TypeError):
                pass
            try:
                # Try date-only format
                return datetime.strptime(date_str, "%m/%d/%Y")
            except (ValueError, TypeError):
                return datetime.min

        sorted_history = sorted(
            history,
            key=lambda x: parse_date(x.get("prevMRDate", "")),
            reverse=True,
        )

        if not sorted_history:
            return None

        latest = sorted_history[0]

        # Normalize the date to DD/MM/YYYY for display
        raw_date = latest.get("prevMRDate", "")
        display_date = raw_date
        parsed = parse_date(raw_date)
        if parsed != datetime.min:
            display_date = parsed.strftime("%d/%m/%Y")

        return {
            "index": latest.get("PrevMRResult"),
            "date": display_date,
            "type": latest.get("Registersdesc", ""),
            "counter_series": latest.get("SerialNumber", ""),
            "registers": latest.get("Registers", "1.8.0"),
        }

    async def submit_meter_reading(
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
        Submit a meter reading via the browser service.

        Calls POST /submit-reading on ihidro-browser.

        Args:
            pod: POD number (e.g., "EMO4307667")
            installation: Installation number (e.g., "4000801506")
            utility_account_number: Contract Account ID (e.g., "8001067827")
            counter_series: Meter serial number
            prev_reading: Previous meter reading
            new_reading: New meter reading (must be >= prev_reading)
            reading_date: Reading date (DD/MM/YYYY), defaults to today
            additional_data: Extra fields (distributor, customer, etc.)

        Returns:
            Dict with success status
        """
        if not self._browser_service_url:
            raise BrowserServiceError(
                "Browser service URL not configured. "
                "Set the ihidro-browser service URL in integration settings."
            )

        # Default reading date
        if reading_date is None:
            from datetime import datetime
            reading_date = datetime.now().strftime("%d/%m/%Y")

        # Validation
        if new_reading < prev_reading:
            return {
                "success": False,
                "message": (
                    f"New reading ({new_reading}) cannot be less than "
                    f"previous ({prev_reading})"
                ),
                "data": None,
            }

        _LOGGER.info(
            "Web Portal: Submitting reading %d for POD %s (prev: %d, date: %s)",
            new_reading, pod, prev_reading, reading_date,
        )

        payload = {
            "username": self._username,
            "password": self._password,
            "pod": pod,
            "installation": installation,
            "utility_account_number": utility_account_number,
            "counter_series": counter_series,
            "prev_reading": prev_reading,
            "new_reading": new_reading,
            "reading_date": reading_date,
        }

        if additional_data:
            payload["additional_data"] = additional_data

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.post(
                    f"{self._browser_service_url}/submit-reading",
                    json=payload,
                ) as resp:
                    data = await resp.json()

                    if resp.status == 401:
                        return {
                            "success": False,
                            "message": f"Login failed: {data.get('message', '')}",
                            "data": data,
                        }

                    if resp.status == 400:
                        return {
                            "success": False,
                            "message": data.get("message", "Bad request"),
                            "data": data,
                        }

                    if resp.status != 200:
                        return {
                            "success": False,
                            "message": (
                                f"Browser service error ({resp.status}): "
                                f"{data.get('message', 'Unknown error')}"
                            ),
                            "data": data,
                        }

                    success = data.get("success", False)
                    message = data.get("message", "")

                    if success:
                        _LOGGER.info("Web Portal: Meter reading submitted successfully!")
                    else:
                        _LOGGER.warning("Web Portal: Submit failed: %s", message)

                    return {
                        "success": success,
                        "message": message,
                        "data": data,
                    }

        except aiohttp.ClientError as err:
            _LOGGER.error("Browser service connection error: %s", err)
            return {
                "success": False,
                "message": (
                    f"Cannot connect to ihidro-browser service at "
                    f"{self._browser_service_url}: {err}"
                ),
                "data": None,
            }

    async def close(self) -> None:
        """No-op (no persistent session to close)."""
        _LOGGER.debug("Web Portal API client closed")
