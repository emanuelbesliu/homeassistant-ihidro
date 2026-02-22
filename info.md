# iHidro - Integrare Home Assistant

Integrare completă pentru monitorizarea și gestionarea conturilor de energie electrică de la **Hidroelectrica România** (ihidro.ro).

## Funcționalități

- ✅ Monitorizare sold curent, facturi, plăți și consum
- ✅ Suport pentru multiple POD-uri (puncte de consum)
- ✅ Trimitere automată index contor lunar
- ✅ Integrare cu Shelly 3EM și alte monitoare de energie
- ✅ 6 senzori dedicați per POD
- ✅ Traduceri complete română/engleză

## Instalare

### HACS (Recomandat)

1. Deschide HACS în Home Assistant
2. Click pe "Integrations"
3. Click pe meniul cu 3 puncte → "Custom repositories"
4. Adaugă: `https://github.com/emanuelbesliu/homeassistant-ihidro`
5. Categorie: "Integration"
6. Caută "iHidro Romania" și instalează

### Manual

```bash
cd /config/custom_components
git clone https://github.com/emanuelbesliu/homeassistant-ihidro.git ihidro
mv ihidro/custom_components/ihidro/* ihidro/
rm -rf ihidro/custom_components
```

## Configurare

1. Repornește Home Assistant
2. **Settings → Devices & Services → Add Integration**
3. Caută "iHidro Romania"
4. Introduceți credențialele ihidro.ro

## Documentație Completă

Vezi [README complet](README.md) pentru:
- Instrucțiuni detaliate de instalare
- Exemple de automatizări
- Configurare dashboard
- Troubleshooting

## Support

- [GitHub Issues](https://github.com/emanuelbesliu/homeassistant-ihidro/issues)
- [Documentație completă](README.md)
