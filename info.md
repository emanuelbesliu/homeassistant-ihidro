# iHidro - Integrare Home Assistant pentru Hidroelectrica Romania

Integrare completa pentru monitorizarea si gestionarea conturilor de energie electrica de la **Hidroelectrica Romania** (ihidro.ro).

## Functionalitati principale

- **22-26 entitati per POD** (senzori, butoane, switch-uri, number entities)
- Monitorizare sold curent, facturi, plati si consum
- Suport pentru **multiple POD-uri** (puncte de consum)
- Suport complet **prosumatori** (productie, compensare ANRE)
- **Trimitere automata index contor** cu senzor extern de energie (optional)
- **Trimitere manuala index** direct din HA (buton + number entity)
- Pre-validare index inainte de trimitere (GetMeterValue)
- Senzori de estimare factura, tarif real, anomalie consum
- Binary sensors: fereastra de citire, factura restanta, scadenta
- **3 blueprint-uri** de automatizare incluse
- **Lovelace card personalizat** inclus
- Traduceri complete romana/engleza
- Diagnostice anonimizate
- Migrare automata de la versiunile anterioare (v1.x)

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
5. (Optional) Configurati senzor de energie extern in optiunile integrarii

## Documentatie Completa

Vezi [README complet](https://github.com/emanuelbesliu/homeassistant-ihidro/blob/main/README.md) pentru:
- Lista completa de entitati
- Ghid autotransmitere index
- Exemple de automatizari
- Configurare dashboard
- Troubleshooting

## Support

- [GitHub Issues](https://github.com/emanuelbesliu/homeassistant-ihidro/issues)
