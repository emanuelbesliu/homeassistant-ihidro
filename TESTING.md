# 🧪 Testing Guide for iHidro Integration

This guide explains how to test the iHidro integration, especially the **Submit Meter Reading** service.

## Prerequisites

1. **Integration Installed:** iHidro integration installed via HACS
2. **Configured:** Integration configured with your iHidro.ro credentials
3. **Sensors Working:** All sensors showing data (Balance, Last Bill, etc.)

---

## 📋 Step 1: Verify Installation

### Check Integration Status

1. Go to **Settings** → **Devices & Services**
2. Find **iHidro** in the list
3. Verify status is **OK** (no errors)
4. Click on the integration to see all entities

### Check Sensors

You should see 6 sensors per POD:

- **iHidro Sold Curent** - Current balance in RON
- **iHidro Ultima Factură** - Last bill info
- **iHidro Ultima Plată** - Last payment info
- **iHidro Index Contor** - Meter reading (may show "Unknown" for classic meters)
- **iHidro Consum Lunar** - Monthly consumption (may show "Unknown")
- **iHidro POD Info** - POD details (address, account numbers)

---

## 🔧 Step 2: Find Your POD Details

Before testing the submit service, you need to find your POD account details:

### Method 1: From POD Info Sensor

1. Go to **Developer Tools** → **States**
2. Find `sensor.ihidro_pod_info_XXXXXXXX` (replace X with your utility account number)
3. Note the **attributes**:
   ```yaml
   utility_account_number: "12345678"
   account_number: "87654321"
   meter_number: "CNT123456"  # May be empty for classic meters
   ```

### Method 2: From Integration Logs

1. Go to **Settings** → **System** → **Logs**
2. Look for iHidro authentication logs
3. Find lines mentioning "POD" or "UtilityAccountNumber"

### Method 3: From iHidro.ro Portal

1. Log in to https://ihidro.ro/portal
2. Go to **My Account** or **Contul Meu**
3. Note your **Cod Loc de Consum** (POD number)

---

## 🧪 Step 3: Test Submit Meter Reading Service

### Important Notes

- **Submission Window:** You can only submit readings during the allowed window (typically 18th-25th of each month)
- **Test Safely:** Use your ACTUAL current meter reading - don't submit fake values
- **Check Before Submit:** Verify the reading window is open using Developer Tools

### Test 1: Check Submission Window

1. Go to **Developer Tools** → **Services**
2. Call service: `ihidro.get_window_dates` (if available)
3. Check the response for `OpeningDate` and `ClosingDate`

**Alternative:** Check manually on https://ihidro.ro/portal/SelfMeterReading.aspx

### Test 2: Manual Service Call

1. Go to **Developer Tools** → **Services**
2. Select service: `ihidro.submit_meter_reading`
3. Fill in the fields:

   ```yaml
   service: ihidro.submit_meter_reading
   data:
     utility_account_number: "12345678"  # Your UAN from Step 2
     account_number: "87654321"           # Your AN from Step 2
     meter_number: "CNT123456"            # Your meter number (check if required)
     meter_reading: 12345.5               # Your ACTUAL current reading
     reading_date: "02/22/2026"           # Optional: defaults to today
   ```

4. Click **CALL SERVICE**

### Test 3: Check Response

After calling the service, check **Home Assistant Logs**:

1. Go to **Settings** → **System** → **Logs**
2. Look for messages from `custom_components.ihidro`
3. Expected responses:

   **✅ Success:**
   ```
   Index trimis cu succes pentru POD 12345678
   ```

   **❌ Outside Window:**
   ```
   Nu vă aflați în fereastra de transmitere index
   ```

   **❌ Invalid Reading:**
   ```
   Index invalid sau mai mic decât ultima citire
   ```

   **❌ API Error:**
   ```
   Eroare la trimiterea indexului: [error message]
   ```

---

## 🤖 Step 4: Test Automation (Optional)

If you want to automate meter reading submission on the 22nd of each month:

### Create Test Automation

1. Copy the example from `/automations/auto_submit_ihidro_meter_reading_example.yaml`
2. Modify the variables with your POD details
3. **Change the trigger** to test immediately:

   ```yaml
   triggers:
     - platform: time
       at: "14:30:00"  # Set to 1 minute from now
   
   condition:
     # Remove the day condition for testing
     []
   ```

4. Save and reload automations
5. Wait for the trigger time
6. Check logs for execution

### Restore Production Settings

After testing, restore the automation:

```yaml
triggers:
  - platform: time
    at: "09:00:00"

condition:
  - condition: template
    value_template: "{{ now().day == 22 }}"
```

---

## 🐛 Troubleshooting

### Issue: "Unknown" Sensors

**Symptoms:** `sensor.ihidro_index_contor` shows "Unknown"

**Cause:** You have a classic (non-smart) meter without AMI

**Solution:** This is expected. You'll need to:
- Manually read your meter
- Store the value in an `input_number` helper
- Use that helper in your automation

### Issue: Service Call Fails with 403/401

**Symptoms:** Service returns authentication error

**Cause:** Session token expired

**Solution:**
1. Go to **Settings** → **Devices & Services**
2. Click on **iHidro**
3. Click **RELOAD**
4. Try the service call again

### Issue: "Outside Submission Window"

**Symptoms:** Service returns message about submission window

**Cause:** You can only submit readings during allowed dates

**Solution:**
- Check the submission window on https://ihidro.ro/portal
- Typically allowed: 18th-25th of each month
- Wait until the window opens

### Issue: "Meter Number Required"

**Symptoms:** Service fails with missing meter_number

**Cause:** API requires meter number but we don't have it

**Solution:**
1. Check your physical meter for the number
2. Or check iHidro.ro portal under meter details
3. Add it to the service call

---

## 📊 Expected Behavior Summary

| Feature | Expected Result |
|---------|----------------|
| **Installation** | No errors, sensors created |
| **Authentication** | Successful login with credentials |
| **Balance Sensor** | Shows current balance in RON |
| **Bill Sensor** | Shows last bill number and amount |
| **Payment Sensor** | Shows last payment amount in RON |
| **Meter Reading Sensor** | "Unknown" for classic meters (expected) |
| **Submit Service** | Success during submission window |
| **Automation** | Triggers on 22nd at specified time |

---

## 🔍 Debugging Tips

### Enable Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.ihidro: debug
```

Restart Home Assistant and check logs for detailed API calls.

### Check API Responses

Look for log entries like:
```
=== Cerere POST: https://hidroelectrica-svc.smartcmobile.com/Service/SelfMeterReading/SubmitMeterReading ===
```

These show the actual API requests and responses.

---

## ✅ Success Checklist

- [ ] Integration installed and configured
- [ ] All sensors showing data (except meter reading if no AMI)
- [ ] POD details identified (UAN, AN, Meter Number)
- [ ] Submission window checked
- [ ] Test service call executed successfully
- [ ] Response logged in Home Assistant logs
- [ ] (Optional) Automation created and tested
- [ ] Debug logging enabled for troubleshooting

---

## 📞 Need Help?

If you encounter issues:

1. **Check logs first:** Settings → System → Logs
2. **Enable debug logging** (see above)
3. **Verify credentials:** Test login at https://ihidro.ro/portal
4. **Check submission window:** Ensure you're within allowed dates
5. **Open an issue:** https://github.com/emanuelbesliu/homeassistant-ihidro/issues

Include in your issue report:
- Home Assistant version
- Integration version
- Relevant log entries (redact personal info!)
- Steps to reproduce the problem
