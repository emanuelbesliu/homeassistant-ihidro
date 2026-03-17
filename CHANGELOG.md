# Changelog

All notable changes to the iHidro Romania Home Assistant Integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.8](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.7...v2.0.8) (2026-03-17)


### Bug Fixes

* move Delay Autotransmitere to number platform and convert Citire Permisă to Da/Nu sensor ([6926572](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/692657262e2a168ec576986934e2ed9a5cf1a251))

## [2.0.7](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.6...v2.0.7) (2026-03-17)


### Bug Fixes

* resolve 'bill_table' not defined in coordinator overdue detection ([3d8fbeb](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/3d8fbebcab662c3f3eca8b975bb81c9242532505))

## [2.0.6](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.5...v2.0.6) (2026-03-17)


### Bug Fixes

* replace all safe_get_table calls with correct API extraction functions ([459df8e](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/459df8ec9b42ebeee9cccdcd58c5b1f80d61825b))

## [2.0.5](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.4...v2.0.5) (2026-03-17)


### Bug Fixes

* await async_register_static_paths and handle LovelaceData object ([c8c5287](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/c8c52873005351deeca402a816364a3fd3293e66))

## [2.0.4](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.3...v2.0.4) (2026-03-17)


### Bug Fixes

* add http to after_dependencies for hassfest validation ([179c84f](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/179c84f2e6986c2a8080c87e7d4a4973fe19f506))

## [2.0.3](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.2...v2.0.3) (2026-03-17)


### Bug Fixes

* handle list-type result.Data in diagnostics endpoint summary ([c60a410](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/c60a410ce8536e52b770e21140764de359c0e196))
* use async_register_static_paths for HA 2024.7+ compatibility ([e4a94e5](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/e4a94e5ad462e184dcde6fe04930556eb7a77a2d))

## [2.0.2](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.1...v2.0.2) (2026-03-16)


### Bug Fixes

* eliminate payment_history references, correct all API payloads, and remove cnecrea comparison ([577b377](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/577b37738d6208a56dfc2822ded2b5e46ad34efa))

## [2.0.1](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.0...v2.0.1) (2026-03-16)


### Bug Fixes

* align version references from 3.0.0 to 2.0.0 to match GitHub release ([fd0f68c](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/fd0f68c6c83012a45c0a1e6d26331e11935ef087))

## [2.0.0](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v1.4.3...v2.0.0) (2026-03-16)

### ⚠ BREAKING CHANGES

* Complete integration rewrite. All entities are recreated. Config version bumped to 3 with automatic migration from v1.x.

### Features

* v2.0.0 complete rewrite — direct API, 22-26 entities per POD, auto-submit ([951d07c](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/951d07c5014fa00fb83c8ef1f0d6157988e154a5))

### Bug Fixes

* add CONFIG_SCHEMA and lovelace after_dependency for hassfest validation ([9cb6add](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/9cb6add450d0dc9f99df40246253b7cf1423e367))
* remove invalid BinarySensorDeviceClass.PAYMENT (no such device class) ([e507d1a](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/e507d1a0e00a789a32f807fe508acc54224ba48d))

### Added
- **19 sensor entities** per POD (up from 6): current balance, last bill, meter reading, monthly consumption, last payment, POD info, contract date, annual consumption, annual index, annual payments total, daily consumption, days until due, real tariff, invoice estimation, consumption anomaly detection; prosumer-only: production, ANRE compensation, generation, net usage
- **3 binary sensors**: reading window open, overdue bill, due date approaching
- **1 button entity**: manual meter reading submission with pre-validation (GetMeterValue)
- **1 number entity**: meter reading input (replaces need for manual input_number helper)
- **1 switch entity**: auto-submit meter reading (requires external energy sensor)
- **1 delay number entity**: configurable delay (0-10 days) before auto-submission
- **External energy sensor integration** (optional) — offset calibration method for automatic meter index computation
- **Per-UAN coordinators** — each POD has its own data coordinator with 2-phase refresh
- **Event detection** — fires HA events on billing changes (new bill, payment, reading window open/close)
- **Reauth flow** — handles expired/invalid credentials without removing the integration
- **Options flow** — configure energy sensor, update interval from integration options
- **Diagnostics platform** — anonymized data dump for troubleshooting
- **3 automation blueprints**: bill payment reminder, reading window notification, overdue bill alert
- **Custom Lovelace card** (`www/ihidro-card.js`) — auto-registered via frontend integration
- **Prosumer support** — automatic detection and dedicated sensors for production/compensation
- **Config migration** — handles v1.0.x through v1.4.x configs, cleans obsolete keys (`twocaptcha_api_key`, `browser_service_url`)
- Complete Romanian and English translations (99 translation keys)

### Changed
- API client rewritten with `aiohttp` (async) instead of `requests` (sync)
- All API calls now go through the mobile app endpoints (no browser/CAPTCHA needed)
- Sensor platform completely rewritten with proper `CoordinatorEntity` pattern
- Config flow rewritten with 2-step setup, 6-point validation

### Removed
- `web_portal_api.py` — browser-based submission (replaced by direct API)
- `browser-service/` — Docker container for headless browser
- `requirements.txt` — no longer needed (deps declared in manifest.json only)
- `SOLUTIE_INDEX_MANUAL.md`, `TESTING.md`, `WEB_PORTAL_CSRF_ISSUE.md` — obsolete docs
- `infra/` directory — Kubernetes manifests for browser-service
- `twocaptcha_api_key` config option (CAPTCHA no longer needed)
- `browser_service_url` config option (browser service removed)
- Dead API methods: `get_validate_user_login_data`, `get_raw_user_setting_data`, `get_window_dates_enc`
- Dead helper functions: `format_kwh_ro`, `get_active_registers`, `build_account_key`

## [1.4.3](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v1.4.2...v1.4.3) (2026-03-09)


### Bug Fixes

* add security-events permission and upgrade codeql-action to v4 ([3d1f870](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/3d1f870812180e6d7ec82341c14b7e9ec70e741f))

## [1.3.2] - 2026-03-04

### Changed
- Bump requests from 2.31.0 to 2.32.0 (#3)
- Dependency updates from Dependabot

## [1.3.1] - 2024-XX-XX

### Changed
- Initial automated versioning setup
- Dependency management via Dependabot
