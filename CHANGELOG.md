# Changelog

All notable changes to the iHidro Romania Home Assistant Integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.10](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.9...v3.0.10) (2026-04-07)


### Bug Fixes

* use max meter index instead of most recent entry ([5cc464c](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/5cc464ce17b4a189eca747e62fdc283c6c83aaf5)), closes [#35](https://github.com/emanuelbesliu/homeassistant-ihidro/issues/35)

## [3.0.9](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.8...v3.0.9) (2026-03-19)


### Bug Fixes

* prevent deadlock in _get_utility_accounts and catch IhidroApiError at setup ([089b709](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/089b7098d4af7b5339613f5e31015014c4d581c3))

## [3.0.8](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.7...v3.0.8) (2026-03-19)


### Bug Fixes

* resolve 401 race condition and energy sensor state_class warning ([0eb69c1](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/0eb69c15d96d764db05cc32d0618f68601b1cb68))


### Documentation

* update README and info.md to reflect v3.x codebase ([7d5509f](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/7d5509fd86abe0888d96397d0f1e91a910ef8a66))

## [3.0.7](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.6...v3.0.7) (2026-03-17)


### Bug Fixes

* resolve prosumer Unknown sensors, consolidate Sold Factură + Factură Restantă ([8924630](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/8924630363d7b5f36764ade90035c8bbceecc836))

## [3.0.6](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.5...v3.0.6) (2026-03-17)


### Bug Fixes

* rewrite diagnostics with proper anonymization, sensor states, and endpoint summaries ([935b561](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/935b56195b4d5ed2a6f9b5c198e1dea0f826aa85))

## [3.0.5](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.4...v3.0.5) (2026-03-17)


### Bug Fixes

* migrate Factură Restantă to sensor (Da/Nu), improve Zile Până la Scadență ([bdc06e9](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/bdc06e92fc5532fea2b7cf42a7fcb000c09edcf7))

## [3.0.4](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.3...v3.0.4) (2026-03-17)


### Bug Fixes

* data_source attribute now reflects actual value source ([00daef6](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/00daef6ef664477baa2d9fc406b18b1e454ca7c8))
* retry setup on network timeout instead of failing permanently ([c7085bb](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/c7085bbd1ee99c5a100110b6a5029632a74b93cc))

## [3.0.3](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.2...v3.0.3) (2026-03-17)


### Bug Fixes

* persist Delay Autotransmitere value across HA restarts ([6e9fa0a](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/6e9fa0a9ea8f3a992d81c0097ddca92a9cb20442))

## [3.0.2](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.1...v3.0.2) (2026-03-17)


### Bug Fixes

* handle negative meter reading deltas from regularization corrections ([850ca60](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/850ca605f0f6c68fac3df1305d2f1dc8831f48e1))

## [3.0.1](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v3.0.0...v3.0.1) (2026-03-17)


### Bug Fixes

* update manifest.json version to 3.0.0 to match GitHub release ([d22c2f4](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/d22c2f4a576a354e0cb38b9be7ff788e69d6f7b7))

## [3.0.0](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.9...v3.0.0) (2026-03-17)


### ⚠ BREAKING CHANGES

* Complete integration rewrite. All entities are recreated. Config version bumped to 3 with automatic migration from v1.x.

### Features

* Add submission window validation and improve logging ([c6320f8](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/c6320f8ffed30afec66e8edef3859a1c76e4696a))
* Complete Playwright-based Web Portal authentication for v1.1.0 ([71e0a87](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/71e0a875303db71ce95462793fbefeb713cb39ca))
* replace 2captcha with ihidro-browser microservice for Web Portal ([be81b1b](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/be81b1b8e60b3a579d3999e235890597e43c0993))
* v3.0.0 complete rewrite — direct API, 22-26 entities per POD, auto-submit ([951d07c](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/951d07c5014fa00fb83c8ef1f0d6157988e154a5))


### Bug Fixes

* add CONFIG_SCHEMA and lovelace after_dependency for hassfest validation ([9cb6add](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/9cb6add450d0dc9f99df40246253b7cf1423e367))
* add http to after_dependencies for hassfest validation ([179c84f](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/179c84f2e6986c2a8080c87e7d4a4973fe19f506))
* add security-events permission and upgrade codeql-action to v4 ([3d1f870](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/3d1f870812180e6d7ec82341c14b7e9ec70e741f))
* align version references from 3.0.0 to 2.0.0 to match GitHub release ([fd0f68c](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/fd0f68c6c83012a45c0a1e6d26331e11935ef087))
* allow empty pre-login CSRF token in ihidro-browser ([3451113](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/34511137a3704424b1139e8547a946acfe75b9f2))
* await async_register_static_paths and handle LovelaceData object ([c8c5287](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/c8c52873005351deeca402a816364a3fd3293e66))
* Change currency from EUR to RON for all monetary sensors ([99a2432](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/99a24327d1da921bbbcc267ee5badcbc8a9ecc29))
* **ci:** don't commit zip files to git, only to releases ([ba5168f](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/ba5168f31aac80a8c27c4b0af13c197da39e8054))
* correct ascending sort bugs, add energy sensor live tracking, and migrate Sold Factură to sensor platform ([36ad345](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/36ad345963e9aa466ee26777afaf97a249798559))
* eliminate payment_history references, correct all API payloads, and remove cnecrea comparison ([577b377](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/577b37738d6208a56dfc2822ded2b5e46ad34efa))
* handle list-type result.Data in diagnostics endpoint summary ([c60a410](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/c60a410ce8536e52b770e21140764de359c0e196))
* map raw iHidro API field names to sensor expected keys ([5bfba86](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/5bfba86f0c018dfbb7a3d73e5e794410a3baa1b9))
* move Delay Autotransmitere to number platform and convert Citire Permisă to Da/Nu sensor ([6926572](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/692657262e2a168ec576986934e2ed9a5cf1a251))
* remove invalid BinarySensorDeviceClass.PAYMENT (no such device class) ([e507d1a](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/e507d1a0e00a789a32f807fe508acc54224ba48d))
* remove invalid filename key from hacs.json ([8539d95](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/8539d955d3094b258af4b126a5524c0ae5696a89))
* Remove non-existent GetPaymentHistory endpoint ([0008fb9](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/0008fb90bbd7dca7a2c85494f50b2eea3dfb5eb3))
* replace all safe_get_table calls with correct API extraction functions ([459df8e](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/459df8ec9b42ebeee9cccdcd58c5b1f80d61825b))
* Replace Playwright with requests + BeautifulSoup for v1.1.1 ([30b0043](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/30b004340d84b8dd9afb1809749bf6a2af39f6ca))
* resolve 'bill_table' not defined in coordinator overdue detection ([3d8fbeb](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/3d8fbebcab662c3f3eca8b975bb81c9242532505))
* Romanian number parsing and populate submit additional_data ([a901937](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/a901937e0b81401cea38d8c437beb39b548bafe0))
* Update all sensors to match actual iHidro API response structures ([016078d](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/016078d5f635b72237f8112433a00185a5ac0e0a))
* use async_register_static_paths for HA 2024.7+ compatibility ([e4a94e5](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/e4a94e5ad462e184dcde6fe04930556eb7a77a2d))


### Documentation

* Add comprehensive testing guide and update README ([c43189b](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/c43189b9a90640c216e29b62bd6cf7d16a447c26))
* Add detailed CSRF token issue documentation ([2176a1c](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/2176a1c236b13e7c0689dfbd1af9218536fbefcb))
* Add solution guide for manual meter reading ([bbaee18](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/bbaee182f6567ca7eb96987dd9e680cc5311fa80))

## [2.0.9](https://github.com/emanuelbesliu/homeassistant-ihidro/compare/v2.0.8...v2.0.9) (2026-03-17)


### Bug Fixes

* correct ascending sort bugs, add energy sensor live tracking, and migrate Sold Factură to sensor platform ([36ad345](https://github.com/emanuelbesliu/homeassistant-ihidro/commit/36ad345963e9aa466ee26777afaf97a249798559))

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
