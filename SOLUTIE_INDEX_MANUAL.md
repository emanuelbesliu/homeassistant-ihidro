# 📝 Ghid: Configurare Index Contor Manual

## Problema

Senzorul `sensor.ihidro_index_contor_XXXXX` arată "Unknown" pentru că:
- Ai un contor clasic (nu smart meter AMI)
- API-ul `GetMultiMeter` returnează array gol pentru `MeterDetails`
- Hidroelectrica nu expune indexul prin API pentru contoarele clasice

## ✅ Soluție: Input Number Helper

### Pas 1: Creează Helper în Home Assistant

1. Mergi la **Settings** → **Devices & Services** → **Helpers**
2. Click pe **+ CREATE HELPER**
3. Selectează **Number**
4. Configurează:
   - **Name**: `Index Contor Curent`
   - **Icon**: `mdi:counter`
   - **Minimum**: `0`
   - **Maximum**: `999999`
   - **Step**: `0.1` (sau `1` dacă contorul tău nu are zecimale)
   - **Unit of measurement**: `kWh`
   - **Display mode**: `Box`

5. Click **CREATE**

Acum vei avea un entity: `input_number.index_contor_curent`

### Pas 2: Actualizează Manual Indexul

Când citești contorul fizic:

1. Mergi la **Developer Tools** → **States**
2. Găsește `input_number.index_contor_curent`
3. Setează valoarea la indexul citit de pe contor
4. SAU folosește un card în dashboard:

```yaml
type: entities
title: Index Contor Electric
entities:
  - entity: input_number.index_contor_curent
    name: Index Curent (manual)
```

### Pas 3: Automatizare cu Helper

Modifică automatizarea de trimitere index să folosească helper-ul:

```yaml
alias: "Auto Trimite Index iHidro - Manual"
description: "Trimite indexul citit manual pe data de 22"
mode: single

triggers:
  - platform: time
    at: "09:00:00"

condition:
  - condition: template
    value_template: "{{ now().day == 22 }}"

actions:
  # Citim indexul din helper
  - variables:
      meter_reading: "{{ states('input_number.index_contor_curent') | float }}"
      utility_account: "XXXXXXXX"  # Înlocuiește cu UAN-ul tău
      account_number: "YYYYYYYY"   # Înlocuiește cu AN-ul tău
      meter_number: ""              # Lasă gol dacă nu știi
  
  # Trimitem indexul
  - action: ihidro.submit_meter_reading
    data:
      utility_account_number: "{{ utility_account }}"
      account_number: "{{ account_number }}"
      meter_number: "{{ meter_number }}"
      meter_reading: "{{ meter_reading }}"
  
  # Notificare (opțional)
  - action: persistent_notification.create
    data:
      title: "✅ Index Trimis la iHidro"
      message: "Index {{ meter_reading }} kWh trimis cu succes!"
```

---

## Opțiunea 2: Folosește Shelly 3EM sau Alt Contor Smart

Dacă ai un Shelly 3EM sau alt dispozitiv de monitorizare energie:

### Pas 2.1: Identifică Senzorul de Energie

Caută în HA un senzor de tipul:
- `sensor.shelly3em_channel_a_energy`
- `sensor.smart_meter_total_energy`
- Orice senzor care măsoară energia totală în kWh

### Pas 2.2: Automatizare cu Calcul Automat

```yaml
alias: "Auto Index iHidro cu Shelly"
description: "Calculează automat indexul bazat pe Shelly 3EM"
mode: single

triggers:
  - platform: time
    at: "09:00:00"

condition:
  - condition: template
    value_template: "{{ now().day == 22 }}"

actions:
  - variables:
      # Index de bază (ultima citire declarată la Hidroelectrica)
      # Actualizează această valoare manual după fiecare transmitere
      base_reading: 10000  # ÎNLOCUIEȘTE cu indexul tău de bază
      
      # Consum total din Shelly (de la instalare)
      shelly_total: "{{ states('sensor.shelly3em_channel_a_energy') | float }}"
      
      # Calculăm indexul corect
      new_reading: "{{ (base_reading + shelly_total) | round(2) }}"
      
      utility_account: "XXXXXXXX"
      account_number: "YYYYYYYY"
      meter_number: ""
  
  - action: ihidro.submit_meter_reading
    data:
      utility_account_number: "{{ utility_account }}"
      account_number: "{{ account_number }}"
      meter_number: "{{ meter_number }}"
      meter_reading: "{{ new_reading }}"
  
  - action: persistent_notification.create
    data:
      title: "✅ Index Trimis"
      message: >
        Index {{ new_reading }} kWh trimis!
        (Bază: {{ base_reading }} + Shelly: {{ shelly_total }})
```

---

## Opțiunea 3: Integrare cu Template Sensor

Creează un template sensor care combină baza + consumul curent:

```yaml
# În configuration.yaml
template:
  - sensor:
      - name: "Index Contor Calculat"
        unique_id: index_contor_calculat
        unit_of_measurement: "kWh"
        device_class: energy
        state_class: total_increasing
        state: >
          {% set base = states('input_number.index_baza_hidroelectrica') | float(0) %}
          {% set consumption = states('sensor.shelly3em_channel_a_energy') | float(0) %}
          {{ (base + consumption) | round(2) }}
        attributes:
          index_baza: "{{ states('input_number.index_baza_hidroelectrica') }}"
          consum_shelly: "{{ states('sensor.shelly3em_channel_a_energy') }}"
```

Apoi folosește `sensor.index_contor_calculat` în automatizare.

---

## 🔍 Găsește Detaliile POD

Pentru a completa automatizarea, ai nevoie de:

### 1. Utility Account Number (UAN)

Verifică în Home Assistant:
```
Developer Tools → States → sensor.ihidro_pod_info_XXXXXXXX
```

Sau verifică atributele senzorului de sold:
```yaml
{{ state_attr('sensor.ihidro_sold_curent', 'utility_account_number') }}
```

### 2. Account Number (AN)

La fel:
```yaml
{{ state_attr('sensor.ihidro_sold_curent', 'account_number') }}
```

### 3. Meter Number (opțional)

Dacă API-ul cere meter_number:
- Caută pe contorul fizic (număr de serie)
- Sau verifică pe portal la https://ihidro.ro/portal
- Sau lasă câmpul gol (`""`) și vezi dacă funcționează

---

## 📊 Dashboard Card Recomandat

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Index Contor Manual
    entities:
      - entity: input_number.index_contor_curent
        name: Index Citit de pe Contor
        icon: mdi:counter
      - entity: sensor.ihidro_sold_curent
        name: Sold de Plată
      - entity: sensor.ihidro_ultima_factura
        name: Ultima Factură

  - type: button
    name: Trimite Index Acum
    icon: mdi:upload
    tap_action:
      action: call-service
      service: ihidro.submit_meter_reading
      service_data:
        utility_account_number: "XXXXXXXX"  # Înlocuiește
        account_number: "YYYYYYYY"          # Înlocuiește
        meter_number: ""
        meter_reading: "{{ states('input_number.index_contor_curent') }}"
```

---

## ⚠️ Important

1. **Senzorul "Unknown" este NORMAL** pentru contoarele clasice
2. **Nu poți obține indexul automat** de la API dacă nu ai smart meter
3. **Soluția:** Folosește input_number helper + citire manuală
4. **Alternativa:** Instalează Shelly 3EM pentru monitorizare automată

---

## ❓ Ai nevoie de ajutor?

Spune-mi:
- Ai Shelly 3EM sau alt dispozitiv de monitorizare?
- Vrei să configurăm helper-ul împreună?
- Care sunt UAN și AN pentru POD-ul tău?
