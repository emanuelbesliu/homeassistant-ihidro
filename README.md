# 🏠 iHidro - Integrare Home Assistant pentru Hidroelectrica România

[![Version](https://img.shields.io/badge/version-1.0.5-blue.svg)](https://github.com/emanuelbesliu/ihidro)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **🚧 v1.1.0 Work in Progress:** Dual API support (Mobile + Web Portal) is being implemented to enable meter reading sensors for classic meters. See [WEB_PORTAL_CSRF_ISSUE.md](../WEB_PORTAL_CSRF_ISSUE.md) for details. Current stable version: **v1.0.5**

Integrare personalizată Home Assistant pentru monitorizarea și gestionarea conturilor de energie electrică de la **Hidroelectrica România** (ihidro.ro).

## ✨ Funcționalități

### 📊 Monitorizare Completă
- ✅ **Sold curent** - Vezi în timp real soldul facturilor
- ✅ **Facturi** - Istoric complet al facturilor (curente și trecute)
- ✅ **Plăți** - Istoric complet al plăților efectuate
- ✅ **Consum** - Monitorizare consum electric lunar și istoric
- ✅ **Index contor** - Citire automată index curent declarat
- ✅ **Informații POD** - Detalii complete pentru fiecare punct de consum

### 🤖 Trimitere Automată Index
- ✅ **Serviciu dedicat** pentru trimiterea indexului contorului
- ✅ **Automatizare lunară** - Trimite automat indexul în fiecare lună pe data de 22
- ✅ **Integrare Shelly 3EM** - Calcul automat bazat pe consumul real
- ✅ **Notificări** - Confirmare trimitere index sau alerte în caz de eroare

### 🏢 Suport Multi-POD
- Gestionează **multiple puncte de consum** (POD-uri) în același timp
- Senzori dedicați pentru fiecare POD
- Grupare automată pe device-uri în Home Assistant

## 📦 Instalare

### Metoda 1: Manual

1. Copiază directorul `ihidro` în `custom_components/`:
   ```bash
   cd /config
   mkdir -p custom_components
   cp -r ihidro custom_components/
   ```

2. Repornește Home Assistant

3. Mergi la **Settings → Devices & Services → Add Integration**

4. Caută "**iHidro**" și urmează pașii de configurare

### Metoda 2: HACS (În Curând)

_Integrarea va fi disponibilă în HACS în viitorul apropiat._

## ⚙️ Configurare

### Pas 1: Adaugă Integrarea

1. În Home Assistant, mergi la **Settings → Devices & Services**
2. Click pe **+ Add Integration**
3. Caută "**iHidro Romania**"
4. Introduceți credențialele ihidro.ro:
   - **Username**: Email sau cod client
   - **Password**: Parola contului
   - **Interval actualizare** (opțional): Implicit 3600s (1 oră)

### Pas 2: Verifică Senzorii Creați

După configurare, vei avea următorii senzori pentru fiecare POD:

| Senzor | Descriere | Unitate |
|--------|-----------|---------|
| `sensor.ihidro_sold_curent_XXXXX` | Sold curent (factură) | RON |
| `sensor.ihidro_ultima_factura_XXXXX` | Număr ultima factură | - |
| `sensor.ihidro_index_contor_XXXXX` | Index curent contor ⚠️ | kWh |
| `sensor.ihidro_consum_lunar_XXXXX` | Consum lunar ⚠️ | kWh |
| `sensor.ihidro_ultima_plata_XXXXX` | Suma ultima plată | RON |
| `sensor.ihidro_pod_info_XXXXX` | Informații POD | - |

_*XXXXX = Numărul POD-ului (Utility Account Number)_

**⚠️ Senzorii de Index și Consum:**
- Acești senzori vor arăta "Unknown" pentru **contoarele clasice** (fără smart meter AMI)
- Acest lucru este **comportament normal** - API-ul Hidroelectrica nu expune aceste date pentru contoarele non-smart
- **Soluție:** Consultă [SOLUTIE_INDEX_MANUAL.md](SOLUTIE_INDEX_MANUAL.md) pentru ghid complet de configurare a indexului manual

## 🚀 Utilizare

### 📘 Ghid Complet de Testare

**Pentru instrucțiuni detaliate de testare și utilizare, consultă [TESTING.md](TESTING.md)**

Ghidul include:
- ✅ Verificarea instalării și configurării
- ✅ Identificarea detaliilor POD-ului
- ✅ Testarea serviciului de trimitere index
- ✅ Configurarea automatizărilor
- ✅ Troubleshooting și debugging

### Trimitere Manuală Index

Poți trimite manual indexul folosind serviciul `ihidro.submit_meter_reading`:

```yaml
action: ihidro.submit_meter_reading
data:
  utility_account_number: "12345678"
  account_number: "87654321"
  meter_number: "CNT123456"
  meter_reading: 12345.5
  reading_date: "02/22/2024"  # Opțional
```

**⚠️ IMPORTANT:** 
- Verifică fereastra de transmitere înainte de trimitere (tipic 18-25 a fiecărei luni)
- **Pentru contoare clasice:** Consultă [SOLUTIE_INDEX_MANUAL.md](SOLUTIE_INDEX_MANUAL.md) pentru configurare cu input_number helper

### Automatizare Lunară (Recomandată)

Creează o automatizare pentru trimiterea automată în fiecare lună:

```yaml
alias: "Auto Trimite Index iHidro"
description: "Trimite automat indexul pe data de 22 a fiecărei luni"
mode: single

triggers:
  - platform: time
    at: "09:00:00"

condition:
  - condition: template
    value_template: "{{ now().day == 22 }}"

actions:
  - variables:
      # Citește datele din senzorii iHidro
      uan: "{{ state_attr('sensor.ihidro_sold_curent_12345678', 'utility_account_number') }}"
      an: "{{ state_attr('sensor.ihidro_sold_curent_12345678', 'account_number') }}"
      meter: "{{ state_attr('sensor.ihidro_index_contor_12345678', 'meter_number') }}"
      
      # Calculează indexul bazat pe ultima declarație + consum lunar
      last_reading: "{{ states('sensor.ihidro_index_contor_12345678') | float }}"
      monthly_consumption: "{{ states('sensor.shelly_3em_energy_monthly') | float }}"
      new_reading: "{{ (last_reading + monthly_consumption) | round(2) }}"

  - action: ihidro.submit_meter_reading
    data:
      utility_account_number: "{{ uan }}"
      account_number: "{{ an }}"
      meter_number: "{{ meter }}"
      meter_reading: "{{ new_reading }}"

  - action: notify.mobile_app_your_phone
    data:
      title: "✅ Index Hidroelectrica Trimis"
      message: "Index {{ new_reading }} kWh trimis cu succes!"
```

**📁 Exemplu complet de automatizare disponibil în:**
`automations/auto_submit_ihidro_meter_reading_example.yaml`

### Integrare cu Shelly 3EM

Dacă ai un Shelly 3EM pentru monitorizarea consumului:

```yaml
# Helper pentru index de bază (creează în Settings → Helpers)
input_number.index_hidroelectrica_baza:
  min: 0
  max: 999999
  step: 0.1
  unit_of_measurement: kWh

# Automatizare cu Shelly
actions:
  - variables:
      base_reading: "{{ states('input_number.index_hidroelectrica_baza') | float }}"
      shelly_consumption: "{{ states('sensor.shelly3em_channel_a_energy') | float }}"
      new_reading: "{{ (base_reading + shelly_consumption) | round(2) }}"
  
  - action: ihidro.submit_meter_reading
    data:
      meter_reading: "{{ new_reading }}"
      # ... rest parametri
  
  # Actualizează indexul de bază pentru luna viitoare
  - action: input_number.set_value
    target:
      entity_id: input_number.index_hidroelectrica_baza
    data:
      value: "{{ new_reading }}"
```

## 📊 Exemple Dashboard

### Card Sold Curent

```yaml
type: entities
title: Hidroelectrica - Sold Curent
entities:
  - entity: sensor.ihidro_sold_curent_12345678
    name: Sold de Plată
  - type: attribute
    entity: sensor.ihidro_sold_curent_12345678
    attribute: due_date
    name: Scadență
  - type: attribute
    entity: sensor.ihidro_sold_curent_12345678
    attribute: status
    name: Status
```

### Card Consum Lunar

```yaml
type: custom:mini-graph-card
name: Consum Electric Lunar
entities:
  - entity: sensor.ihidro_consum_lunar_12345678
hours_to_show: 720  # 30 zile
line_width: 2
points_per_hour: 0.04
```

### Card Index Contor

```yaml
type: glance
title: Index Contor Electric
entities:
  - entity: sensor.ihidro_index_contor_12345678
    name: Index Curent
  - entity: sensor.ihidro_consum_lunar_12345678
    name: Consum Luna
  - entity: sensor.ihidro_sold_curent_12345678
    name: Sold de Plată
```

## 🔧 Configurare Avansată

### Interval de Actualizare

Poți modifica intervalul de actualizare din **Settings → Devices & Services → iHidro → Configure**:

- **Minim**: 300 secunde (5 minute)
- **Implicit**: 3600 secunde (1 oră)
- **Maxim**: 86400 secunde (24 ore)

### Atribute Senzori

Fiecare senzor expune atribute adiționale utile:

```yaml
# Exemplu: sensor.ihidro_sold_curent_12345678
attributes:
  utility_account_number: "12345678"
  account_number: "87654321"
  address: "Str. Exemplu Nr. 1, București"
  due_date: "2024-02-28"
  bill_number: "BILL123456"
  status: "Neplătit"
```

Poți accesa aceste atribute în automatizări:

```yaml
{{ state_attr('sensor.ihidro_sold_curent_12345678', 'due_date') }}
```

## 🐛 Troubleshooting

### Eroare de Autentificare

**Problema**: "Invalid credentials" la configurare

**Soluții**:
1. Verifică username-ul și parola pe [ihidro.ro](https://client.hidroelectrica.ro)
2. Asigură-te că nu ai activat autentificare 2FA
3. Verifică că nu ai caractere speciale în parolă care necesită escape

### Senzorii nu se actualizează

**Problema**: Senzorii rămân "unavailable" sau nu se actualizează

**Soluții**:
1. Verifică logurile: **Settings → System → Logs**
2. Caută erori legate de "ihidro"
3. Verifică intervalul de actualizare (minim 5 minute)
4. Repornește Home Assistant

### Eroare la trimiterea indexului

**Problema**: Serviciul `submit_meter_reading` eșuează

**Soluții**:
1. Verifică că ești în fereastra de citire (între data X și Y a lunii)
2. Verifică că indexul nou este mai mare decât ultimul declarat
3. Verifică că ai acces la POD-ul respectiv
4. Consultă logurile pentru detalii

**⚠️ IMPORTANT**: Endpoint-ul pentru trimiterea indexului a fost estimat bazat pe structura API-ului Hidroelectrica. Dacă întâmpini probleme, consultă [TESTING.md](TESTING.md) pentru debugging sau deschide un issue pe GitHub.

## 📝 Structura Fișierelor

```
custom_components/ihidro/
├── __init__.py           # Entry point și servicii
├── manifest.json         # Metadata integrare
├── const.py              # Constante și endpoint-uri API
├── api.py                # Client API iHidro
├── coordinator.py        # Data Update Coordinator
├── config_flow.py        # Configurare UI
├── sensor.py             # Entități senzor
├── services.yaml         # Definire servicii
└── translations/         # Traduceri
    ├── ro.json
    └── en.json
```

## 🔐 Securitate

- **Credențialele** sunt stocate encrypt în Home Assistant
- **Comunicația** cu API-ul folosește HTTPS
- **Session token** expiră automat și se reînnoiește
- **Date sensibile** nu sunt logate în plaintext

## 🤝 Contribuții

Contribuțiile sunt binevenite! Pentru bug-uri sau feature requests, deschide un issue pe GitHub.

### Development

Pentru a dezvolta integrarea:

1. Fork repository-ul
2. Creează un branch pentru feature-ul tău
3. Testează în Home Assistant
4. Creează un Pull Request

## 📄 Licență

MIT License - Vezi [LICENSE](LICENSE) pentru detalii.

## 🙏 Mulțumiri

- **@cnecrea** pentru integrarea Hidroelectrica originală care a servit ca referință
- **Home Assistant Community** pentru suport și documentație
- **Hidroelectrica România** pentru API-ul public

## 📞 Support

- **GitHub Issues**: [Raportează probleme](https://github.com/emanuelbesliu/ihidro/issues)
- **Home Assistant Community**: [Forum discuții](https://community.home-assistant.io/)

---

**🔌 Dezvoltat cu ❤️ pentru comunitatea Home Assistant România**

*Această integrare nu este afiliată oficial cu Hidroelectrica România.*
