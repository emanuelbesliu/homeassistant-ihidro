"""
ihidro-browser: A lightweight browser microservice for ihidro.ro Web Portal.

Uses nodriver (stealthy Chrome automation) with a persistent browser instance
to handle CSRF tokens and reCAPTCHA v3 automatically.

Endpoints:
  GET  /health         - Health check
  POST /scrape-all     - Login + fetch PODs + index history for all PODs
  POST /submit-reading - Login + submit a meter reading
  POST /restart-browser - Force-restart the browser instance

The ihidro.ro Web Portal uses:
  - ASP.NET with dynamic CSRF tokens (hidden field #hdnCSRFToken)
  - jQuery $.ajaxSetup interceptor that attaches csrftoken header to all POST requests
  - reCAPTCHA v3 (invisible, score-based) for login
  - ASP.NET session cookies

Since all of these require a real browser context, we use nodriver to:
  1. Load the login page (which populates CSRF token and loads reCAPTCHA)
  2. Trigger login via the page's own JS functions
  3. After login, extract the new CSRF token and make API calls via fetch()
"""

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from typing import Optional

import nodriver as nd
from aiohttp import web

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8193))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
HEADLESS = os.environ.get("HEADLESS", "true").lower() == "true"

PORTAL_BASE_URL = "https://ihidro.ro/portal"
LOGIN_PAGE_URL = f"{PORTAL_BASE_URL}/default.aspx"
DASHBOARD_URL = f"{PORTAL_BASE_URL}/Dashboard.aspx"
INDEX_HISTORY_URL = f"{PORTAL_BASE_URL}/IndexHistory.aspx"
SELF_METER_READING_URL = f"{PORTAL_BASE_URL}/SelfMeterReading.aspx"

# API endpoints (ASP.NET WebMethods)
API_UPDATE_STATE = f"{LOGIN_PAGE_URL}/updateState"
API_VALIDATE_LOGIN = f"{LOGIN_PAGE_URL}/validateLogin"
API_GET_ALL_POD = f"{INDEX_HISTORY_URL}/GetAllPODBind"
API_LOAD_GRID_DATA = f"{SELF_METER_READING_URL}/LoadW2UIGridData"
API_GET_METER_VALUE = f"{SELF_METER_READING_URL}/GetMeterValue"
API_SUBMIT_READING = f"{SELF_METER_READING_URL}/SubmitSelfMeterReading"
API_GET_TOKEN_TIME = f"{PORTAL_BASE_URL}/Common.aspx/getTokentime"

# Timeouts
LOGIN_TIMEOUT = 60  # seconds to wait for login to complete
RECAPTCHA_TIMEOUT = 30  # seconds to wait for reCAPTCHA v3

logger = logging.getLogger("ihidro-browser")

# ---------------------------------------------------------------------------
# Global browser state
# ---------------------------------------------------------------------------
browser: Optional[nd.Browser] = None
browser_lock = asyncio.Lock()
xvfb_display = None


def start_xvfb():
    """Start virtual X display for head-full Chrome in headless environments."""
    global xvfb_display
    if xvfb_display is None and os.name != "nt":
        try:
            from xvfbwrapper import Xvfb
            xvfb_display = Xvfb()
            xvfb_display.start()
            logger.info("Virtual display started")
        except ImportError:
            logger.warning("xvfbwrapper not installed, assuming display available")


async def get_browser() -> nd.Browser:
    """Get or create the persistent browser instance."""
    global browser
    async with browser_lock:
        if browser is not None:
            try:
                proc = getattr(browser, "_process", None) or getattr(
                    browser, "get_process", None
                )
                if proc is not None:
                    returncode = getattr(proc, "returncode", None)
                    if returncode is None:
                        return browser
                    logger.warning(
                        "Browser process died (rc=%s), recreating...", returncode
                    )
                else:
                    if browser.tabs:
                        return browser
                    logger.warning("Browser has no tabs, recreating...")
            except Exception as e:
                logger.warning("Browser health check failed: %s, recreating...", e)
            browser = None

        logger.info("Creating new browser instance...")
        if HEADLESS:
            start_xvfb()

        options = nd.Config()
        options.sandbox = False
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-gpu")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")

        language = os.environ.get("LANG", "ro-RO")
        options.lang = language

        browser = await nd.Browser.create(config=options)
        logger.info("Browser created successfully")
        return browser


def _safe_evaluate_result(result) -> str:
    """Safely convert a tab.evaluate() result to a string.

    nodriver returns an ExceptionDetails object (not a string) when JS
    evaluation fails.  Detect that and convert to a readable error string.
    """
    if result is None:
        return ""
    type_name = type(result).__name__
    if type_name == "ExceptionDetails" or "ExceptionDetails" in type_name:
        text = getattr(result, "text", None) or str(result)
        raise RuntimeError(f"JS evaluation error: {text}")
    if isinstance(result, str):
        return result
    return str(result)


async def execute_js(tab: nd.Tab, script: str, await_promise: bool = False) -> str:
    """Execute JavaScript in the tab and return the result."""
    result = await tab.evaluate(script, await_promise=await_promise)
    return _safe_evaluate_result(result)


# ---------------------------------------------------------------------------
# ihidro.ro Portal interaction
# ---------------------------------------------------------------------------

async def portal_login(tab: nd.Tab, username: str, password: str) -> dict:
    """
    Perform the full ihidro.ro login flow in the browser.

    Steps:
      1. Navigate to login page (loads CSRF token + reCAPTCHA JS)
      2. Fill in credentials
      3. Trigger login via the page's own JS (which handles reCAPTCHA v3)
      4. Wait for redirect to Dashboard
      5. Extract post-login CSRF token

    Returns:
        dict with keys: success (bool), message (str), csrf_token (str or None)
    """
    logger.info("=== Portal login starting ===")

    # Step 1: Navigate to login page
    logger.info("Step 1: Loading login page...")
    tab = await tab.browser.get(LOGIN_PAGE_URL)
    await tab.sleep(3)  # Wait for page + JS to fully load

    # Verify we're on the login page
    page_url = await execute_js(tab, "location.href")
    logger.info("Current URL: %s", page_url)

    # Step 2: Check that CSRF token and reCAPTCHA are available
    logger.info("Step 2: Checking page state...")
    page_state = await execute_js(
        tab,
        """JSON.stringify({
            url: location.href,
            hasCSRF: !!document.getElementById('hdnCSRFToken'),
            csrfValue: (document.getElementById('hdnCSRFToken') || {}).value || '',
            hasRecaptcha: typeof grecaptcha !== 'undefined',
            hasjQuery: typeof jQuery !== 'undefined',
            captchaKey: (document.getElementById('hdncaptchakey') || {}).value || '',
            captchaVersion: (document.getElementById('hdnIsVersionTwoCaptcha') || {}).value || '',
        })""",
    )
    logger.info("Page state: %s", page_state)

    try:
        state = json.loads(page_state)
    except (json.JSONDecodeError, TypeError):
        return {
            "success": False,
            "message": f"Could not parse page state: {page_state}",
            "csrf_token": None,
        }

    if not state.get("csrfValue"):
        return {
            "success": False,
            "message": "CSRF token not found on login page",
            "csrf_token": None,
        }

    pre_login_csrf = state["csrfValue"]
    logger.info("Pre-login CSRF: %s...", pre_login_csrf[:30])

    # Step 3: Fill credentials and trigger login via JS
    # We use the page's own login flow which handles reCAPTCHA v3 natively.
    # The flow is: fill fields -> click login -> page calls updateState ->
    # page calls ValidateCaptchaV3Login -> page calls ValidateUserLogin
    logger.info("Step 3: Filling credentials and triggering login...")

    # Use JSON.stringify to safely escape the username/password into JS strings
    login_js = """
    (async () => {
        // Fill in the login fields
        const userField = document.getElementById('txtLogin');
        const pwdField = document.getElementById('txtpwd');
        if (!userField || !pwdField) {
            return JSON.stringify({success: false, message: 'Login fields not found'});
        }

        userField.value = PLACEHOLDER_USERNAME;
        pwdField.value = PLACEHOLDER_PASSWORD;

        // Trigger the login button click which starts the full login flow:
        // updateState -> reCAPTCHA v3 -> validateLogin
        const loginBtn = document.getElementById('btnlogin');
        if (!loginBtn) {
            return JSON.stringify({success: false, message: 'Login button not found'});
        }

        // Click the button
        loginBtn.click();

        return JSON.stringify({success: true, message: 'Login triggered'});
    })()
    """.replace(
        "PLACEHOLDER_USERNAME", json.dumps(username)
    ).replace(
        "PLACEHOLDER_PASSWORD", json.dumps(password)
    )

    trigger_result = await execute_js(tab, login_js, await_promise=True)
    logger.info("Login trigger result: %s", trigger_result)

    try:
        trigger_data = json.loads(trigger_result)
        if not trigger_data.get("success"):
            return {
                "success": False,
                "message": trigger_data.get("message", "Login trigger failed"),
                "csrf_token": None,
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Step 4: Wait for login to complete (redirect to Dashboard or error)
    logger.info("Step 4: Waiting for login to complete...")
    start_time = time.time()
    login_succeeded = False

    while time.time() - start_time < LOGIN_TIMEOUT:
        await asyncio.sleep(2)

        current_url = await execute_js(tab, "location.href")
        logger.debug("Waiting... URL: %s", current_url)

        # Check if we've been redirected to Dashboard (login success)
        if "Dashboard" in current_url or "dashboard" in current_url:
            login_succeeded = True
            logger.info("Login succeeded! Redirected to: %s", current_url)
            break

        # Check if we're still on the login page with an error
        error_check = await execute_js(
            tab,
            """(() => {
                const errorDiv = document.getElementById('lblresult');
                const errorMsg = errorDiv ? errorDiv.innerText.trim() : '';
                const isVisible = errorDiv ? (errorDiv.style.display !== 'none' && errorMsg !== '') : false;
                return JSON.stringify({error: errorMsg, visible: isVisible});
            })()""",
        )

        try:
            error_data = json.loads(error_check)
            if error_data.get("visible") and error_data.get("error"):
                return {
                    "success": False,
                    "message": f"Login error: {error_data['error']}",
                    "csrf_token": None,
                }
        except (json.JSONDecodeError, TypeError):
            pass

    if not login_succeeded:
        # One more check - maybe the page navigated but URL doesn't contain Dashboard
        final_url = await execute_js(tab, "location.href")
        if "default.aspx" in final_url.lower():
            return {
                "success": False,
                "message": f"Login timed out after {LOGIN_TIMEOUT}s. Still on login page.",
                "csrf_token": None,
            }
        # Maybe on a different page (Authentication, forced password change, etc.)
        logger.warning("Login may have partially succeeded. URL: %s", final_url)

    # Step 5: Extract post-login CSRF token
    logger.info("Step 5: Extracting post-login CSRF token...")
    await tab.sleep(2)  # Wait for Dashboard to fully load

    post_csrf = await execute_js(
        tab,
        "(document.getElementById('hdnCSRFToken') || {}).value || ''",
    )

    if not post_csrf:
        logger.warning("No CSRF token found on post-login page")
        # Try to get it from the current page's form
        post_csrf = await execute_js(
            tab,
            "document.querySelector('input[name*=hdnCSRFToken]')?.value || ''",
        )

    logger.info(
        "Post-login CSRF: %s...", post_csrf[:30] if post_csrf else "(empty)"
    )

    return {
        "success": True,
        "message": "Login successful",
        "csrf_token": post_csrf,
    }


async def portal_ajax_post(
    tab: nd.Tab, url: str, payload: dict, csrf_token: str
) -> str:
    """
    Execute a POST AJAX call from the browser context with CSRF token.

    This mirrors what jQuery $.ajaxSetup does: attaches csrftoken and isajax
    headers to all non-GET requests.

    Args:
        tab: Browser tab
        url: Full URL of the endpoint
        payload: JSON-serializable dict for the request body
        csrf_token: CSRF token to send in the header

    Returns:
        Response text
    """
    js = """
    (async () => {
        const resp = await fetch(PLACEHOLDER_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "csrftoken": PLACEHOLDER_CSRF,
                "isajax": "1",
            },
            credentials: "same-origin",
            body: PLACEHOLDER_BODY,
        });

        if (!resp.ok) {
            return JSON.stringify({
                __error: true,
                status: resp.status,
                statusText: resp.statusText,
                body: await resp.text(),
            });
        }

        return await resp.text();
    })()
    """.replace(
        "PLACEHOLDER_URL", json.dumps(url)
    ).replace(
        "PLACEHOLDER_CSRF", json.dumps(csrf_token)
    ).replace(
        "PLACEHOLDER_BODY", json.dumps(json.dumps(payload))
    )

    result = await tab.evaluate(js, await_promise=True)
    return _safe_evaluate_result(result)


def _parse_aspnet_response(text: str):
    """Parse an ASP.NET WebMethod response.

    ASP.NET WebMethods wrap their return value in {"d": ...}.
    The "d" value is often a JSON-encoded string that needs a second parse.
    """
    try:
        outer = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text

    d_value = outer.get("d", outer)

    if isinstance(d_value, str):
        try:
            return json.loads(d_value)
        except (json.JSONDecodeError, TypeError):
            return d_value

    return d_value


async def portal_get_pods(tab: nd.Tab, csrf_token: str) -> list:
    """
    Get all PODs for the logged-in user.

    Endpoint: POST /portal/IndexHistory.aspx/GetAllPODBind
    Request body: empty
    Response: {"d": "{\"Data\":[{\"installation\":\"...\",\"pod\":\"...\"}]}"}
    """
    logger.info("Fetching POD list...")
    resp_text = await portal_ajax_post(tab, API_GET_ALL_POD, {}, csrf_token)
    logger.debug("GetAllPODBind response: %s", resp_text[:500])

    parsed = _parse_aspnet_response(resp_text)

    # Handle different response formats
    if isinstance(parsed, dict):
        pods = parsed.get("Data", [])
    elif isinstance(parsed, list):
        pods = parsed
    else:
        logger.warning("Unexpected POD response format: %s", type(parsed))
        pods = []

    logger.info("Found %d POD(s)", len(pods))
    return pods


async def portal_get_index_history(
    tab: nd.Tab, csrf_token: str, installation: str, pod: str
) -> list:
    """
    Get meter reading history for a POD.

    Endpoint: POST /portal/SelfMeterReading.aspx/LoadW2UIGridData
    Request body: {"installation": "...", "podvalue": "..."}
    Response: {"d": "[{\"POD\":\"...\",\"CounterSeries\":\"...\",\"Date\":\"...\",\"Index\":\"...\"}]"}
    """
    logger.info("Fetching index history for POD %s...", pod)
    resp_text = await portal_ajax_post(
        tab,
        API_LOAD_GRID_DATA,
        {"installation": installation, "podvalue": pod},
        csrf_token,
    )
    logger.debug("LoadW2UIGridData response: %s", resp_text[:500])

    parsed = _parse_aspnet_response(resp_text)

    if isinstance(parsed, list):
        history = parsed
    elif isinstance(parsed, dict):
        history = parsed.get("Data", [])
    else:
        history = []

    logger.info("Found %d index records for POD %s", len(history), pod)
    return history


async def portal_submit_reading(
    tab: nd.Tab, csrf_token: str, submit_payload: dict
) -> dict:
    """
    Submit a meter reading.

    Steps:
      1. Call GetMeterValue (pre-validation)
      2. Call SubmitSelfMeterReading (actual submit)

    Args:
        tab: Browser tab
        csrf_token: Post-login CSRF token
        submit_payload: Full payload for SubmitSelfMeterReading

    Returns:
        dict with success status
    """
    installation = submit_payload.get("installation_number", "")
    pod = submit_payload.get("pod_value", "")

    # Step 1: Pre-validation via GetMeterValue
    logger.info("Pre-validating meter reading for POD %s...", pod)
    try:
        # Build the validation payload (same structure but newmeterread=0)
        entity = submit_payload["objSubmitMeterReadProxy"]["UsageSelfMeterReadEntity"][0]
        validate_payload = {
            "objMeterValueProxy": {
                "UsageSelfMeterReadEntity": [{
                    **entity,
                    "newmeterread": "0",
                }]
            },
            "installation_number": installation,
            "pod_value": pod,
        }

        validate_resp = await portal_ajax_post(
            tab, API_GET_METER_VALUE, validate_payload, csrf_token
        )
        logger.debug("GetMeterValue response: %s", validate_resp[:200])
    except Exception as e:
        logger.warning("GetMeterValue pre-check failed (non-fatal): %s", e)

    # Step 2: Submit the reading
    logger.info("Submitting meter reading for POD %s...", pod)
    submit_resp = await portal_ajax_post(
        tab, API_SUBMIT_READING, submit_payload, csrf_token
    )
    logger.info("SubmitSelfMeterReading response: %s", submit_resp[:500])

    parsed = _parse_aspnet_response(submit_resp)

    # Check for errors in response
    if isinstance(parsed, str) and "__error" not in parsed:
        return {"success": True, "message": "Meter reading submitted", "data": parsed}

    if isinstance(parsed, dict):
        if parsed.get("__error"):
            return {
                "success": False,
                "message": f"HTTP {parsed.get('status')}: {parsed.get('body', '')}",
                "data": parsed,
            }
        return {"success": True, "message": "Meter reading submitted", "data": parsed}

    return {"success": True, "message": "Meter reading submitted", "data": submit_resp}


# ---------------------------------------------------------------------------
# API Handlers
# ---------------------------------------------------------------------------

async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"status": "ok", "service": "ihidro-browser"})


async def handle_scrape_all(request: web.Request) -> web.Response:
    """
    POST /scrape-all
    Body: {"username": "...", "password": "..."}

    All-in-one endpoint: login + fetch PODs + index history for each POD.
    Returns all data in a single response.
    """
    tab = None
    try:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        if not username or not password:
            return web.json_response(
                {"status": "error", "message": "username and password required"},
                status=400,
            )

        logger.info("=== Starting full scrape for user '%s' ===", username)

        # Step 1: Login
        drv = await get_browser()
        tab = await drv.get(LOGIN_PAGE_URL)
        login_result = await portal_login(tab, username, password)

        if not login_result["success"]:
            try:
                await tab.close()
            except Exception:
                pass
            return web.json_response(
                {
                    "status": "error",
                    "message": login_result["message"],
                    "logged_in": False,
                },
                status=401,
            )

        csrf_token = login_result["csrf_token"]

        # Step 2: Get PODs
        pods = await portal_get_pods(tab, csrf_token)

        # Step 3: Get index history for each POD
        pods_data = []
        for pod_info in pods:
            installation = pod_info.get("installation", "")
            pod_value = pod_info.get("pod", "")

            if not installation or not pod_value:
                logger.warning("Skipping POD with missing data: %s", pod_info)
                continue

            history = await portal_get_index_history(
                tab, csrf_token, installation, pod_value
            )

            pods_data.append({
                "pod_info": pod_info,
                "index_history": history,
            })

        # Step 4: Close tab
        logger.info("Closing scrape tab...")
        try:
            await tab.close()
        except Exception as e:
            logger.debug("Tab close failed (non-critical): %s", e)

        logger.info("=== Full scrape complete: %d PODs ===", len(pods_data))
        return web.json_response({
            "status": "ok",
            "logged_in": True,
            "pods": pods_data,
        })

    except Exception as e:
        logger.error("Scrape-all error: %s", e, exc_info=True)
        if tab is not None:
            try:
                await tab.close()
            except Exception:
                pass
        return web.json_response(
            {"status": "error", "message": str(e)}, status=500
        )


async def handle_submit_reading(request: web.Request) -> web.Response:
    """
    POST /submit-reading
    Body: {
        "username": "...",
        "password": "...",
        "pod": "EMO4307667",
        "installation": "4000801506",
        "utility_account_number": "8001067827",
        "counter_series": "1702233822626815",
        "prev_reading": 5396,
        "new_reading": 5400,
        "reading_date": "09/03/2026",       # DD/MM/YYYY, optional (defaults to today)
        "additional_data": {                  # optional
            "registerCat": "1.8.0",
            "distributor": "DELGAZ GRID",
            "meterInterval": "lunar",
            "supplier": "HE",
            "distCustomer": "...",
            "distCustomerId": "...",
            "distContract": "...",
            "distContractDate": "..."
        }
    }

    Login + submit a meter reading.
    """
    tab = None
    try:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        if not username or not password:
            return web.json_response(
                {"status": "error", "message": "username and password required"},
                status=400,
            )

        pod = body.get("pod")
        installation = body.get("installation")
        utility_account_number = body.get("utility_account_number")
        counter_series = body.get("counter_series")
        prev_reading = body.get("prev_reading")
        new_reading = body.get("new_reading")
        reading_date = body.get("reading_date")
        additional_data = body.get("additional_data", {})

        # Validate required fields
        missing = []
        for field in ["pod", "installation", "utility_account_number",
                       "counter_series", "prev_reading", "new_reading"]:
            if body.get(field) is None:
                missing.append(field)
        if missing:
            return web.json_response(
                {
                    "status": "error",
                    "message": f"Missing required fields: {', '.join(missing)}",
                },
                status=400,
            )

        # Default reading date to today
        if not reading_date:
            from datetime import datetime
            reading_date = datetime.now().strftime("%d/%m/%Y")

        # Validate new reading >= prev reading
        if int(new_reading) < int(prev_reading):
            return web.json_response(
                {
                    "status": "error",
                    "message": (
                        f"New reading ({new_reading}) cannot be less than "
                        f"previous ({prev_reading})"
                    ),
                },
                status=400,
            )

        logger.info(
            "=== Submitting reading: POD=%s, new=%s, prev=%s ===",
            pod, new_reading, prev_reading,
        )

        # Step 1: Login
        drv = await get_browser()
        tab = await drv.get(LOGIN_PAGE_URL)
        login_result = await portal_login(tab, username, password)

        if not login_result["success"]:
            try:
                await tab.close()
            except Exception:
                pass
            return web.json_response(
                {
                    "status": "error",
                    "message": login_result["message"],
                    "logged_in": False,
                },
                status=401,
            )

        csrf_token = login_result["csrf_token"]

        # Step 2: Build the submit payload (exact format from HAR)
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
        defaults.update(additional_data)

        submit_payload = {
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

        # Step 3: Submit
        result = await portal_submit_reading(tab, csrf_token, submit_payload)

        # Step 4: Close tab
        try:
            await tab.close()
        except Exception as e:
            logger.debug("Tab close failed (non-critical): %s", e)

        logger.info("=== Submit complete: %s ===", result.get("message"))
        return web.json_response({
            "status": "ok" if result["success"] else "error",
            **result,
        })

    except Exception as e:
        logger.error("Submit-reading error: %s", e, exc_info=True)
        if tab is not None:
            try:
                await tab.close()
            except Exception:
                pass
        return web.json_response(
            {"status": "error", "message": str(e)}, status=500
        )


async def handle_restart_browser(request: web.Request) -> web.Response:
    """POST /restart-browser - Force-restart the browser instance."""
    global browser
    async with browser_lock:
        if browser is not None:
            try:
                browser.stop()
            except Exception:
                pass
            browser = None
    return web.json_response({"status": "ok", "message": "Browser restarted"})


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/scrape-all", handle_scrape_all)
    app.router.add_post("/submit-reading", handle_submit_reading)
    app.router.add_post("/restart-browser", handle_restart_browser)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=LOG_LEVEL,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Suppress noisy loggers
    logging.getLogger("nodriver.core.browser").setLevel(logging.WARNING)
    logging.getLogger("nodriver.core.tab").setLevel(logging.WARNING)
    logging.getLogger("nodriver.core.connection").setLevel(logging.WARNING)
    logging.getLogger("websockets.client").setLevel(logging.WARNING)

    logger.info("Starting ihidro-browser service on %s:%d...", HOST, PORT)
    app = create_app()
    web.run_app(app, host=HOST, port=PORT)
