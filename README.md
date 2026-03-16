# iHidro - Home Assistant Integration for Hidroelectrica Romania

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/emanuelbesliu/ihidro)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Custom Home Assistant integration for monitoring and managing electricity accounts from **Hidroelectrica Romania** (ihidro.ro), with advanced features like real tariff computation, bill estimation, consumption anomaly detection, and auto-submit meter readings.

## Features

### Monitoring (15-19 sensors per POD)
- **Current balance** with payment status and due date tracking
- **Bill history** with annual consumption and payment totals
- **Meter reading** with active counter series detection
- **Monthly consumption** from usage history
- **Payment history** split by channel (bank, cash, online)
- **POD info** with contract details and master data
- **Daily consumption** and generation data
- **Prosumer support** — production, ANRE compensation, net usage (auto-detected)

### Breakaway Features
- **Real tariff sensor** — computes all-in cost per kWh from actual bill data (amount / consumption), not just the published rate
- **Bill estimation sensor** — extrapolates current month's bill from consumption trend; supports optional external energy sensor (e.g. Shelly 3EM) for higher accuracy
- **Consumption anomaly sensor** — detects unusual consumption patterns by comparing current usage against rolling historical average
- **Days until due sensor** — countdown to payment deadline

### Auto-Submit Meter Reading
- **Auto-submit switch** — when enabled, automatically reads the external energy sensor during the reading window and submits the meter index via API
- **Configurable delay** — 0-10 day delay from window opening (default: 1 day)
- **Offset calibration** — `offset = last_known_index - energy_sensor_value`, then `index = energy_sensor_current + offset`. Recalibrates each billing cycle.
- Switch and delay entities are greyed out (unavailable) if no energy sensor is configured

### Additional Entities
- **3 binary sensors** — payment status (paid/unpaid), overdue bill detection, reading window open/closed
- **1 button** — manual meter reading submission with pre-validation (window check, value sanity)
- **1 number input** — meter reading value entry for manual submission
- **3 automation blueprints** — bill payment reminder, reading window notification, overdue bill alert
- **Custom Lovelace card** — compact dashboard with balance, consumption, and status indicators (auto-registered)

### Multi-POD Support
- Manages multiple consumption points (PODs) simultaneously
- Dedicated entities per POD with automatic device grouping
- Per-POD coordinator with 2-phase refresh (light every cycle, heavy every Nth cycle)

### Infrastructure
- Async aiohttp API client (no requests/selenium/browser dependencies)
- Token persistence across HA restarts
- Reauth flow for expired credentials
- Config entry migration from all old versions (v1.0.x through v1.4.x)
- Anonymized diagnostics dump for troubleshooting

## Entity Count

| User Type | Sensors | Binary Sensors | Button | Number | Switch | Delay | Total |
|-----------|---------|----------------|--------|--------|--------|-------|-------|
| Standard  | 15      | 3              | 1      | 1      | 1      | 1     | **22** |
| Prosumer  | 19      | 3              | 1      | 1      | 1      | 1     | **26** |

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
   cp -r ihidro /config/custom_components/
   ```
2. Restart Home Assistant
3. Go to **Settings > Devices & Services > Add Integration** and search for "iHidro"

## Configuration

### Step 1: Add Integration

1. **Settings > Devices & Services > + Add Integration**
2. Search for "**iHidro Romania**"
3. Enter your ihidro.ro credentials:
   - **Username**: Email or client code
   - **Password**: Account password
4. Select which PODs to monitor (if you have multiple)

### Step 2: Options (Optional)

Go to **Settings > Devices & Services > iHidro > Configure** to set:

- **Update interval**: 300s (5 min) to 86400s (24 hours), default 3600s (1 hour)
- **External energy sensor**: Select a cumulative energy sensor (e.g. `sensor.shelly_3em_total_energy`) for bill estimation and auto-submit. Must have:
  - `device_class: energy`
  - `state_class: total_increasing` or `total`
  - Unit: kWh or Wh
  - Valid numeric state

## Auto-Submit Setup

1. Configure an external energy sensor in options (see above)
2. Enable the **Autotransmitere** switch entity
3. Optionally adjust the delay (0-10 days from window opening)
4. The integration will automatically:
   - Detect when the reading window opens
   - Wait the configured delay
   - Read the energy sensor value
   - Apply offset calibration to compute the meter index
   - Submit the reading via the Hidroelectrica API

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

Alternatively, use the built-in **Trimite Index** button entity which reads the value from the Number input entity.

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
- Current balance with payment status (green/yellow/red)
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
├── api.py                   # Async aiohttp API client (~880 lines)
├── binary_sensor.py         # 3 binary sensors
├── button.py                # Meter reading submission button
├── config_flow.py           # 2-step + reauth + options flow
├── const.py                 # Constants and API endpoints
├── coordinator.py           # Per-UAN coordinator with 2-phase refresh
├── diagnostics.py           # Anonymized diagnostic dump
├── helpers.py               # Utility functions (~380 lines)
├── manifest.json            # Integration metadata (v2.0.0)
├── number.py                # Meter reading input entity
├── sensor.py                # 19 sensor classes (~1750 lines)
├── services.yaml            # Service definitions
├── strings.json             # Translation keys
├── switch.py                # Auto-submit switch + delay number
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

## Migration from v1.x

The integration automatically migrates config entries from any v1.x version:

| Old Version | Cleaned Keys | Added Keys |
|-------------|-------------|------------|
| v1.0.x - v1.2.x | — | token persistence, selected accounts |
| v1.3.x | `twocaptcha_api_key` | token persistence, selected accounts |
| v1.4.x | `browser_service_url` | token persistence, selected accounts |

Obsolete keys are also cleaned from options entries. No user action required.

## Security

- Credentials stored encrypted by Home Assistant
- HTTPS communication with API
- Session tokens auto-expire and auto-renew
- Sensitive data never logged in plaintext
- Diagnostics output is anonymized (last 4 chars only)

## Troubleshooting

### Authentication errors
1. Verify credentials at [ihidro.ro](https://client.hidroelectrica.ro)
2. Check HA logs: **Settings > System > Logs**, filter for "ihidro"
3. If persistent, remove and re-add the integration (triggers reauth)

### Sensors unavailable
1. Check logs for API errors
2. Verify internet connectivity
3. Reduce update interval if rate-limited
4. Check Hidroelectrica service status

### Meter submission fails
1. Verify the reading window is open (check binary sensor)
2. Ensure the new index is higher than the last declared index
3. Check logs for API response details

### Diagnostics
Download diagnostics from **Settings > Devices & Services > iHidro > (device) > Download Diagnostics**. All sensitive data is automatically anonymized.

## Contributing

Contributions welcome. For bugs or feature requests, open an issue on GitHub.

## License

MIT License - See [LICENSE](LICENSE) for details.

## Credits

- **Home Assistant Community** for documentation and support

## Support

- **GitHub Issues**: [Report problems](https://github.com/emanuelbesliu/homeassistant-ihidro/issues)
- **Home Assistant Community**: [Forum](https://community.home-assistant.io/)

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/emanuelbesliu)

---

*This integration is not officially affiliated with Hidroelectrica Romania.*
