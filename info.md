# iHidro - Integrare Home Assistant pentru Hidroelectrica Romania

Integrare completa pentru monitorizarea si gestionarea conturilor de energie electrica de la **Hidroelectrica Romania** (ihidro.ro).

## Functionalitati principale

- **21-25 entitati per POD** (senzori, buton, switch, number entities)
- **17 senzori standard**: sold, facturi, plati, consum lunar/zilnic/anual, index contor, estimare factura, tarif real, anomalie consum
- **4 senzori prosumator** (auto-detectati): productie, compensare ANRE, generare energie, consum net
- Suport pentru **multiple POD-uri** (puncte de consum)
- **Senzor extern de energie optional** (ex: Shelly EM, ISMeter EM2) pentru tracking live index si consum
- **Trimitere automata index contor** cu calibrare offset si delay configurabil
- **Trimitere manuala index** direct din HA (buton + number entity)
- Pre-validare index inainte de trimitere
- **3 blueprint-uri** de automatizare incluse (reminder plata, notificare fereastra citire, alerta factura restanta)
- **Lovelace card personalizat** inclus (auto-inregistrat)
- Traduceri complete romana/engleza
- Diagnostice anonimizate cu snapshot senzori
- Migrare automata de la versiunile anterioare (v1.x, v2.x)

## Instalare

### HACS (Recomandat)

1. Deschide HACS in Home Assistant
2. Click pe "Integrations"
3. Click pe meniul cu 3 puncte -> "Custom repositories"
4. Adauga: `https://github.com/emanuelbesliu/homeassistant-ihidro`
5. Categorie: "Integration"
6. Cauta "iHidro Romania" si instaleaza

### Manual

Copiaza directorul `custom_components/ihidro` in directorul `custom_components` al Home Assistant.

## Configurare

1. Reporneste Home Assistant
2. **Settings -> Devices & Services -> Add Integration**
3. Cauta "iHidro Romania"
4. Introduceti credentialele ihidro.ro
5. Selectati POD-urile dorite
6. (Optional) Selectati un senzor extern de energie pentru tracking live si autotransmitere

## Documentatie Completa

Vezi [README complet](https://github.com/emanuelbesliu/homeassistant-ihidro/blob/main/README.md) pentru:
- Lista completa de entitati si descrieri
- Ghid autotransmitere index
- Configurare senzor extern de energie
- Exemple de automatizari
- Troubleshooting

## Support

- [GitHub Issues](https://github.com/emanuelbesliu/homeassistant-ihidro/issues)
