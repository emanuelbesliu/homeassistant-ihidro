"""Integrarea iHidro pentru Home Assistant.

Gestionează:
- Setup/teardown per config entry
- Per-account coordinators (un coordinator per UAN)
- Token persistence (supraviețuiește restartului HA)
- Config entry migration (v1 → v2 → v3)
- Serviciul de trimitere index
- Runtime data typed (IhidroRuntimeData dataclass)
- Înregistrare automată card Lovelace
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .api import IhidroAPI, IhidroApiError, IhidroAuthError
from .const import (
    DOMAIN,
    CONFIG_VERSION,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    CONF_SELECTED_ACCOUNTS,
    CONF_TOKEN_USER_ID,
    CONF_TOKEN_SESSION,
    DEFAULT_UPDATE_INTERVAL,
    SERVICE_SUBMIT_METER_READING,
    ATTR_UTILITY_ACCOUNT_NUMBER,
    ATTR_ACCOUNT_NUMBER,
    ATTR_METER_NUMBER,
)
from .coordinator import IhidroAccountCoordinator

_LOGGER = logging.getLogger(__name__)

IHIDRO_CARD_URL = f"/ihidro/ihidro-card.js"
IHIDRO_CARD_NAME = "ihidro-card"

PLATFORMS: List[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
]

# Schema pentru serviciul de trimitere index
SUBMIT_METER_READING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_UTILITY_ACCOUNT_NUMBER): str,
        vol.Required(ATTR_ACCOUNT_NUMBER): str,
        vol.Required(ATTR_METER_NUMBER): str,
        vol.Required("meter_reading"): vol.Coerce(float),
        vol.Optional("reading_date"): str,
    }
)


@dataclass
class IhidroRuntimeData:
    """Typed runtime data pentru iHidro integration."""

    api: IhidroAPI
    coordinators: Dict[str, IhidroAccountCoordinator] = field(default_factory=dict)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Configurare componentă din configuration.yaml (nu este folosită)."""
    return True


async def _async_register_lovelace_card(hass: HomeAssistant) -> None:
    """Înregistrează fișierul JS al cardului Lovelace ca resursă statică.

    Fișierul www/ihidro-card.js este servit la /ihidro/ihidro-card.js.
    Utilizatorul trebuie să adauge manual resursa în Lovelace:
        URL: /ihidro/ihidro-card.js
        Type: JavaScript Module
    """
    # Evităm înregistrarea duplicată (folosim propriul flag în hass.data)
    if hass.data.get(f"{DOMAIN}_card_registered"):
        return
    hass.data[f"{DOMAIN}_card_registered"] = True

    card_path = os.path.join(os.path.dirname(__file__), "www", "ihidro-card.js")
    if not os.path.isfile(card_path):
        _LOGGER.warning(
            "Fișierul ihidro-card.js nu a fost găsit la %s — "
            "cardul Lovelace nu va fi disponibil",
            card_path,
        )
        return

    # Înregistrăm calea statică pentru a servi fișierul JS
    # HA 2024.7+ a înlocuit register_static_path cu async_register_static_paths
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(IHIDRO_CARD_URL, card_path, False)]
        )
    except (ImportError, AttributeError):
        # Fallback pentru versiuni mai vechi de HA
        hass.http.register_static_path(IHIDRO_CARD_URL, card_path, cache_headers=False)
    _LOGGER.debug("Card Lovelace înregistrat la %s", IHIDRO_CARD_URL)

    # Adăugăm resursa la frontend (auto-include în Lovelace fără intervenție manuală)
    # Folosim lovelace_resources dacă este disponibil (HA 2023.1+)
    try:
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        lovelace_data = hass.data.get("lovelace")
        resources = getattr(lovelace_data, "resources", None) if lovelace_data else None
        if isinstance(resources, ResourceStorageCollection):
            # Verificăm dacă resursa e deja adăugată
            existing = [
                r
                for r in resources.async_items()
                if r.get("url", "").startswith("/ihidro/")
            ]
            if not existing:
                await resources.async_create_item(
                    {"res_type": "module", "url": IHIDRO_CARD_URL}
                )
                _LOGGER.info(
                    "Resursa Lovelace ihidro-card.js a fost adăugată automat"
                )
            else:
                _LOGGER.debug(
                    "Resursa Lovelace ihidro-card.js deja înregistrată"
                )
    except (ImportError, KeyError, AttributeError) as err:
        _LOGGER.debug(
            "Nu s-a putut auto-înregistra resursa Lovelace "
            "(necesită adăugare manuală): %s",
            err,
        )


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrare config entry de la versiuni vechi.

    Scenarii de migrare suportate:
    - v1 (iHidro v1.0.x - v1.2.x): data contine username, password, update_interval
    - v1 (iHidro v1.3.x):          + twocaptcha_api_key (obsolet, trebuie sters)
    - v1 (iHidro v1.4.x):          + browser_service_url (obsolet, trebuie sters)
    - v1 → v2: Adaugă câmpuri token persistence + selected_accounts
    - v2 → v3: Adaugă suport pentru noi platforme (binary_sensor, button, number, switch)

    Chei obsolete care trebuie eliminate:
    - twocaptcha_api_key (v1.3.x) — 2Captcha nu mai este necesar
    - browser_service_url (v1.4.x) — browser service eliminat
    - Aceleași chei pot exista și în options (din options flow-ul vechi)
    """
    if config_entry.version < CONFIG_VERSION:
        _LOGGER.info(
            "Migrăm config entry iHidro de la v%d la v%d",
            config_entry.version,
            CONFIG_VERSION,
        )
        new_data = {**config_entry.data}

        if config_entry.version < 2:
            # v1 → v2: Adaugă câmpuri de persistență token + selecție conturi
            new_data.setdefault(CONF_TOKEN_USER_ID, None)
            new_data.setdefault(CONF_TOKEN_SESSION, None)
            new_data.setdefault(CONF_SELECTED_ACCOUNTS, [])

            # Curățăm chei obsolete din data (v1.3.x / v1.4.x)
            _obsolete_data_keys = (
                "twocaptcha_api_key",
                "browser_service_url",
            )
            for key in _obsolete_data_keys:
                if key in new_data:
                    _LOGGER.info(
                        "Migrare: Eliminăm cheia obsoletă '%s' din config_entry.data",
                        key,
                    )
                    del new_data[key]

        # v2 → v3: Nu are modificări la data, doar versiunea (noi platforme)

        # Curățăm opțiunile vechi (pot conține chei din options flow-urile v1.x)
        new_options = {**config_entry.options} if config_entry.options else {}
        _obsolete_options_keys = (
            "twocaptcha_api_key",
            "browser_service_url",
        )
        options_changed = False
        for key in _obsolete_options_keys:
            if key in new_options:
                _LOGGER.info(
                    "Migrare: Eliminăm cheia obsoletă '%s' din config_entry.options",
                    key,
                )
                del new_options[key]
                options_changed = True

        # Actualizăm config entry
        update_kwargs = {
            "data": new_data,
            "version": CONFIG_VERSION,
        }
        if options_changed:
            update_kwargs["options"] = new_options

        hass.config_entries.async_update_entry(
            config_entry,
            **update_kwargs,
        )
        _LOGGER.info(
            "Migrare config entry iHidro completată cu succes (v%d → v%d)",
            config_entry.version,
            CONFIG_VERSION,
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurare integrare din config entry."""
    _LOGGER.debug("=== iHidro: Începem setup pentru entry %s ===", entry.entry_id)

    # Obținem sesiunea aiohttp partajată de HA
    session = async_get_clientsession(hass)

    # Inițializăm API-ul (async, fără requests)
    api = IhidroAPI(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    # Injectăm token-uri salvate (dacă există) — evităm re-autentificare la restart
    saved_user_id = entry.data.get(CONF_TOKEN_USER_ID)
    saved_session_token = entry.data.get(CONF_TOKEN_SESSION)
    if saved_user_id and saved_session_token:
        api.inject_tokens(saved_user_id, saved_session_token)
        _LOGGER.debug("Token-uri restaurate din config entry")

    # Autentificare și obținere conturi
    try:
        await api.login_if_needed()
    except IhidroAuthError as err:
        _LOGGER.error("Eroare autentificare iHidro: %s", err)
        # Invalidăm token-urile salvate — încercăm un login proaspăt
        api.invalidate_session()
        try:
            await api.login()
        except IhidroAuthError:
            # Trigger reauth flow dacă și al doilea login eșuează
            entry.async_start_reauth(hass)
            return False
        except (TimeoutError, aiohttp.ClientError, OSError) as err2:
            raise ConfigEntryNotReady(
                f"Timeout la re-autentificare iHidro: {err2}"
            ) from err2
    except IhidroApiError as err:
        # Eroare non-auth de la API (ex: 500, răspuns invalid după re-auth)
        raise ConfigEntryNotReady(
            f"Eroare API iHidro la inițializare: {err}"
        ) from err
    except (TimeoutError, aiohttp.ClientError, OSError) as err:
        raise ConfigEntryNotReady(
            f"Serverul iHidro nu răspunde: {err}"
        ) from err

    # Obținem lista de POD-uri
    all_accounts = api.get_utility_accounts()
    if not all_accounts:
        _LOGGER.warning("Nu s-au găsit POD-uri pentru utilizatorul curent")
        return False

    # Filtrăm conturile selectate (dacă utilizatorul a ales conturi specifice)
    selected = entry.data.get(CONF_SELECTED_ACCOUNTS, [])
    if selected:
        accounts = [
            acc
            for acc in all_accounts
            if acc["UtilityAccountNumber"] in selected
        ]
    else:
        accounts = all_accounts

    if not accounts:
        _LOGGER.warning("Niciun cont selectat nu mai este disponibil")
        return False

    # Creăm un coordinator per cont (UAN)
    coordinators: Dict[str, IhidroAccountCoordinator] = {}
    failed_count = 0
    for account_info in accounts:
        uan = account_info["UtilityAccountNumber"]
        coordinator = IhidroAccountCoordinator(
            hass=hass,
            api=api,
            entry=entry,
            account_info=account_info,
        )
        try:
            # Facem primul refresh de date
            await coordinator.async_config_entry_first_refresh()
            coordinators[uan] = coordinator
        except Exception as err:
            _LOGGER.error(
                "Eroare la inițializarea coordinator-ului pentru POD %s: %s",
                uan,
                err,
            )
            failed_count += 1
            continue

    if not coordinators:
        _LOGGER.error("Toți coordinatorii au eșuat la inițializare")
        return False

    if failed_count > 0:
        _LOGGER.warning(
            "%d din %d coordinatori au eșuat la inițializare, "
            "continuăm cu cei funcționali",
            failed_count,
            len(accounts),
        )

    # Stocăm runtime data typed
    runtime_data = IhidroRuntimeData(api=api, coordinators=coordinators)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = runtime_data

    # Migrăm entitățile care au schimbat platforma (binary_sensor → sensor)
    # Sold Factură a fost mutat din binary_sensor în sensor.
    # Citire Permisă a fost mutat din binary_sensor în sensor (v2.0.8).
    # Factură Restantă — eliminat complet (consolidat în Sold Factură).
    #   Trebuie curățat atât din binary_sensor (v1.x/v2.x) cât și din sensor (v3.0.5).
    ent_reg = er.async_get(hass)
    for uan in coordinators:
        # Migrare binary_sensor → sensor (sold_factura, citire_permisa)
        _migrations = [
            (f"{entry.entry_id}_{uan}_sold_factura", "sensor"),
            (f"{entry.entry_id}_{uan}_citire_permisa", "sensor"),
        ]
        for unique_id, new_platform in _migrations:
            old_entity = ent_reg.async_get_entity_id(
                "binary_sensor", DOMAIN, unique_id
            )
            if old_entity is not None:
                _LOGGER.info(
                    "Migrăm entitatea %s din binary_sensor → %s",
                    old_entity,
                    new_platform,
                )
                ent_reg.async_remove(old_entity)

        # Cleanup complet: factura_restanta eliminat (consolidat în sold_factura)
        _removals = [
            (f"{entry.entry_id}_{uan}_factura_restanta", "binary_sensor"),
            (f"{entry.entry_id}_{uan}_factura_restanta", "sensor"),
        ]
        for unique_id, platform in _removals:
            old_entity = ent_reg.async_get_entity_id(
                platform, DOMAIN, unique_id
            )
            if old_entity is not None:
                _LOGGER.info(
                    "Eliminăm entitatea %s (%s) — consolidat în Sold Factură",
                    old_entity,
                    platform,
                )
                ent_reg.async_remove(old_entity)

    # Înregistrăm platformele (sensor, binary_sensor, button, number, switch)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Înregistrăm serviciul de trimitere index (doar o dată per domeniu)
    if not hass.services.has_service(DOMAIN, SERVICE_SUBMIT_METER_READING):
        async def handle_submit_meter_reading(call: ServiceCall) -> None:
            """Handler pentru serviciul de trimitere index.

            Caută coordinator-ul corect prin toate config entry-urile active.
            """
            utility_account_number = call.data[ATTR_UTILITY_ACCOUNT_NUMBER]
            account_number = call.data[ATTR_ACCOUNT_NUMBER]
            meter_number = call.data[ATTR_METER_NUMBER]
            meter_reading = call.data["meter_reading"]
            reading_date = call.data.get(
                "reading_date", datetime.now().strftime("%m/%d/%Y")
            )

            _LOGGER.info(
                "Trimitem index %s pentru contorul %s (UAN: %s, AN: %s)",
                meter_reading,
                meter_number,
                utility_account_number,
                account_number,
            )

            # Căutăm coordinator-ul corect prin toate entry-urile
            coordinator = None
            target_api = None
            for entry_id, rt_data in hass.data.get(DOMAIN, {}).items():
                if isinstance(rt_data, IhidroRuntimeData):
                    coord = rt_data.coordinators.get(utility_account_number)
                    if coord:
                        coordinator = coord
                        target_api = rt_data.api
                        break

            if not coordinator or not target_api:
                _LOGGER.error(
                    "Nu s-a găsit coordinator pentru UAN %s",
                    utility_account_number,
                )
                return

            try:
                # Obținem datele anterioare de citire (pentru metadata)
                previous_data = None
                if coordinator.data:
                    previous_data = coordinator.data.get("previous_meter_read")

                result = await target_api.submit_self_meter_read(
                    utility_account_number=utility_account_number,
                    account_number=account_number,
                    meter_number=meter_number,
                    meter_reading=meter_reading,
                    reading_date=reading_date,
                    previous_meter_read_data=previous_data,
                )

                if result.get("success"):
                    _LOGGER.info(
                        "Index trimis cu succes: %s", result.get("message")
                    )
                    # Forțăm un refresh al datelor după trimitere
                    await coordinator.async_request_refresh()
                else:
                    _LOGGER.error(
                        "Eroare la trimiterea indexului: %s",
                        result.get("message"),
                    )

            except Exception as err:
                _LOGGER.error("Excepție la trimiterea indexului: %s", err)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SUBMIT_METER_READING,
            handle_submit_meter_reading,
            schema=SUBMIT_METER_READING_SCHEMA,
        )

    # Înregistrăm fișierul JS pentru cardul Lovelace custom
    await _async_register_lovelace_card(hass)

    _LOGGER.debug("=== iHidro: Setup completat cu succes ===")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Dezinstalare integrare."""
    _LOGGER.debug("=== iHidro: Dezinstalăm entry %s ===", entry.entry_id)

    # Dezinstalăm platformele
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Ștergem datele din hass.data
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Dezînregistrăm serviciul doar dacă nu mai sunt alte entry-uri
    remaining = {
        k for k in hass.data.get(DOMAIN, {})
        if isinstance(hass.data[DOMAIN].get(k), IhidroRuntimeData)
    }
    if not remaining:
        hass.services.async_remove(DOMAIN, SERVICE_SUBMIT_METER_READING)

    return unload_ok
