# iHidro - Home Assistant Integration for Hidroelectrica Romania

[![GitHub Release](https://img.shields.io/github/v/release/emanuelbesliu/homeassistant-ihidro)](https://github.com/emanuelbesliu/homeassistant-ihidro/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Custom Home Assistant integration for monitoring and managing electricity accounts from **Hidroelectrica Romania** (ihidro.ro). Features real tariff computation, bill estimation, consumption anomaly detection, prosumer support, and automatic meter reading submission.

## Features

### Monitoring (17-21 sensors per POD)

| Sensor | Description | Unit |
|--------|-------------|------|
| Sold Curent | Current account balance | RON |
| Ultima Factura | Latest invoice details (number, date, amount) | RON |
| Index Contor | Current meter index (live-tracked via energy sensor if configured) | kWh |
| Consum Lunar | Monthly consumption (live-tracked via energy sensor if configured) | kWh |
| Consum Zilnic | Daily consumption (live-tracked via energy sensor if configured) | kWh |
| Consum Anual | Total consumption over last 12 months | kWh |
| Index Istoric | Historical meter readings with dates | kWh |
| Ultima Plata | Last payment details (amount, date, channel) | RON |
| Total Plati Anual | Sum of all payments in the last 12 months | RON |
| POD Info | Contract and POD address details | - |
| Data Contract | Contract start date | - |
| Zile Pana la Scadenta | Days remaining until payment due date | days |
| Tarif Real | All-in cost per kWh computed from actual bill data | RON/kWh |
| Estimare Factura | Projected current month bill based on consumption trend | RON |
| Anomalie Consum | Detects unusual consumption vs. rolling historical average | - |
| Citire Permisa | Whether the meter reading window is currently open (Da/Nu) | - |
| Sold Factura | Payment status: Platit / Neplatit / Restant / Credit | - |

### Prosumer Sensors (auto-detected, 4 additional)

| Sensor | Description | Unit |
|--------|-------------|------|
| Productie Prosumator | Total energy production from latest meter readings | kWh |
| Compensare ANRE | ANRE compensation amounts from bill history | RON |
| Generare Energie | Energy generation with meter history fallback for non-AMI | kWh |
| Consum Net | Net consumption (consumption minus production) | kWh |

### Other Entities

| Entity | Type | Description |
|--------|------|-------------|
| Autotransmitere | Switch | Enable/disable automatic meter reading submission |
| Index Transmitere | Number | Meter reading value for manual submission |
| Delay Autotransmitere | Number | Delay (0-10 days) from window opening before auto-submit |
| Trimite Index | Button | Submit meter reading with pre-validation |

### Entity Count per POD

| User Type | Sensors | Button | Number | Switch | Total |
|-----------|---------|--------|--------|--------|-------|
| Standard  | 17      | 1      | 2      | 1      | **21** |
| Prosumer  | 21      | 1      | 2      | 1      | **25** |

### External Energy Sensor Integration

An optional external energy sensor (e.g., Shelly EM, ISMeter EM2) can be configured for:

- **Live meter index tracking** — Index Contor interpolates between API refreshes using real energy data
- **Live consumption** — Consum Lunar and Consum Zilnic update in real-time
- **Bill estimation accuracy** — Estimare Factura uses live consumption instead of API-only data
- **Auto-submit** — automatically submits meter readings during the reading window

**Offset calibration**: `offset = last_known_api_index - energy_sensor_value`, then `live_index = energy_sensor_current + offset`. Recalibrates each billing cycle or when the API returns new data.

The energy sensor must have:
- `device_class: energy`
- `state_class: total_increasing` or `total`
- Unit: kWh or Wh
- Valid numeric state

### Auto-Submit Meter Reading

1. Configure an external energy sensor (during setup or in options)
2. Enable the **Autotransmitere** switch
3. Optionally adjust the delay (0-10 days from window opening)
4. The integration will automatically:
   - Detect when the reading window opens
   - Wait the configured delay
   - Read the energy sensor and apply offset calibration
   - Submit the reading via the Hidroelectrica API

The switch and delay entities are greyed out (unavailable) if no energy sensor is configured.

### Multi-POD Support

- Manages multiple consumption points (PODs) simultaneously
- Dedicated entities per POD with automatic device grouping
- Per-POD data coordinator with 2-phase refresh (light every cycle, heavy every Nth cycle)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu (top right) and select **Custom repositories**
3. Add `https://github.com/emanuelbesliu/homeassistant-ihidro` with category **Integration**
4. Search for "iHidro" and install
5. Restart Home Assistant

### Manual

1. Copy the `ihidro` directory to your `custom_components/` folder:
   ```bash
   cp -r custom_components/ihidro /config/custom_components/
   ```
2. Restart Home Assistant
3. Go to **Settings > Devices & Services > Add Integration** and search for "iHidro"

## Configuration

### Initial Setup

1. **Settings > Devices & Services > + Add Integration**
2. Search for "**iHidro Romania**"
3. Enter your ihidro.ro credentials:
   - **Username**: Email or client code
   - **Password**: Account password
4. Select which PODs to monitor (if you have multiple)
5. (Optional) Select an external energy sensor for live tracking and auto-submit

### Options

Go to **Settings > Devices & Services > iHidro > Configure** to change:

- **Update interval**: 300s (5 min) to 86400s (24 hours), default 3600s (1 hour)
- **External energy sensor**: Add, change, or remove the energy sensor

## Service: Manual Meter Submission

```yaml
action: ihidro.submit_meter_reading
data:
  utility_account_number: "12345678"
  account_number: "87654321"
  meter_number: "CNT123456"
  meter_reading: 12345.5
  reading_date: "02/22/2024"  # Optional, defaults to today
```

Alternatively, use the **Trimite Index** button entity which reads the value from the Index Transmitere number entity.

## Automation Blueprints

Three ready-to-use blueprints are included:

| Blueprint | Trigger | Action |
|-----------|---------|--------|
| Bill Payment Reminder | Days before due date | Mobile notification |
| Reading Window Notification | Window opens | Mobile notification |
| Overdue Bill Alert | Bill becomes overdue | Mobile notification |

Import from **Settings > Automations > Blueprints > Import Blueprint**.

## Custom Lovelace Card

A custom card (`ihidro-card`) is auto-registered and available in your Lovelace dashboard. It shows:
- Current balance with payment status indicator
- Monthly consumption with trend
- Meter reading with last reading date
- Reading window status

If auto-registration fails, add manually:
- **URL**: `/ihidro/ihidro-card.js`
- **Type**: JavaScript Module

## File Structure

```
custom_components/ihidro/
├── __init__.py              # Entry point, services, migration, card registration
├── api.py                   # Async aiohttp API client (~910 lines)
├── binary_sensor.py         # Empty (all migrated to sensor.py in v3.0)
├── button.py                # Meter reading submission button
├── config_flow.py           # 2-step + reauth + options flow (~505 lines)
├── const.py                 # Constants and API endpoints
├── coordinator.py           # Per-UAN coordinator with 2-phase refresh (~514 lines)
├── diagnostics.py           # Anonymized diagnostic dump (~460 lines)
├── helpers.py               # Utility functions (~630 lines)
├── manifest.json            # Integration metadata
├── number.py                # Index Transmitere + Delay Autotransmitere
├── sensor.py                # 21 sensor classes (~2500 lines)
├── services.yaml            # Service definitions
├── strings.json             # Translation keys
├── switch.py                # Autotransmitere switch (~540 lines)
├── hacs.json                # HACS distribution config
├── translations/
│   ├── en.json              # English translations
│   └── ro.json              # Romanian translations
├── blueprints/automation/
│   ├── bill_payment_reminder.yaml
│   ├── reading_window_notification.yaml
│   └── overdue_bill_alert.yaml
└── www/
    └── ihidro-card.js       # Custom Lovelace card
```

## Migration

The integration automatically migrates config entries from any previous version:

| Old Version | Cleaned Keys | Notes |
|-------------|-------------|-------|
| v1.0.x - v1.2.x | — | Adds token persistence, selected accounts |
| v1.3.x | `twocaptcha_api_key` | Removes obsolete captcha key |
| v1.4.x | `browser_service_url` | Removes obsolete browser service |
| v2.x | — | Schema update to v3 |

Obsolete keys are cleaned from both data and options. No user action required.

## Infrastructure

- Fully async `aiohttp` API client (no requests/selenium/browser dependencies)
- Token persistence across HA restarts
- Reauth flow for expired credentials
- `ConfigEntryNotReady` on network timeouts (auto-retries)
- Anonymized diagnostics with sensor state snapshots
- `RestoreEntity` for switch and delay entities (survive HA restarts)

## Security

- Credentials stored encrypted by Home Assistant
- HTTPS communication with API
- Session tokens auto-expire and auto-renew
- Sensitive data never logged in plaintext
- Diagnostics output anonymized (last 4 chars only for account identifiers)

## Troubleshooting

### Authentication errors
1. Verify credentials at [ihidro.ro](https://client.hidroelectrica.ro)
2. Check HA logs: **Settings > System > Logs**, filter for "ihidro"
3. If persistent, remove and re-add the integration (triggers reauth)

### Sensors showing "Unknown"
1. Some sensors require multiple billing cycles of data to compute values
2. Prosumer sensors only appear if production meter registers (_P) are detected
3. Non-AMI meters may have limited data from the API (tentative data returns null)
4. Download diagnostics to inspect actual API responses

### Meter submission fails
1. Verify the reading window is open (check Citire Permisa sensor — should show "Da")
2. Ensure the new index is higher than the last declared index
3. Check logs for API response details

### Diagnostics
Download diagnostics from **Settings > Devices & Services > iHidro > (device) > Download Diagnostics**. All sensitive data is automatically anonymized. The export includes sensor states, API endpoint summaries, and configuration details.

## Contributing

Contributions welcome. For bugs or feature requests, open an issue on GitHub.

## License

MIT License - See [LICENSE](LICENSE) for details.

## Support

- **GitHub Issues**: [Report problems](https://github.com/emanuelbesliu/homeassistant-ihidro/issues)
- **Home Assistant Community**: [Forum](https://community.home-assistant.io/)

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/emanuelbesliu)

---

*This integration is not officially affiliated with Hidroelectrica Romania.*
