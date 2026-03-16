/**
 * iHidro Card — Custom Lovelace Card for Hidroelectrica România
 *
 * Afișează un dashboard compact cu:
 * - Sold curent + status plată (verde/galben/roșu)
 * - Estimare factură următoare
 * - Tarif real all-in per kWh cu tendință
 * - Grafic consum ultimele 6 luni (bar chart SVG)
 * - Status anomalie consum
 * - Zile până la scadență cu progress bar
 *
 * Configurare în Lovelace:
 *   type: custom:ihidro-card
 *   pod: <UAN>  (opțional, auto-detectează primul POD)
 */

const CARD_VERSION = "1.0.0";

class IhidroCard extends HTMLElement {
  static get properties() {
    return { hass: {}, config: {} };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this._createCard();
    }
    this._updateCard();
  }

  setConfig(config) {
    this._config = config;
  }

  static getConfigElement() {
    return document.createElement("ihidro-card-editor");
  }

  static getStubConfig() {
    return { pod: "" };
  }

  _findEntities() {
    if (!this._hass) return {};
    const pod = this._config?.pod || "";
    const states = this._hass.states;
    const entities = {};

    const sensorMap = {
      sold: "current_balance",
      estimare: "estimare_factura",
      tarif: "tarif_real",
      zile: "days_until_due",
      consum_lunar: "monthly_consumption",
      anomalie: "anomalie_consum",
      consum_anual: "consum_anual",
    };

    for (const [key, suffix] of Object.entries(sensorMap)) {
      for (const [entityId, state] of Object.entries(states)) {
        if (
          entityId.startsWith("sensor.ihidro_") ||
          entityId.startsWith("sensor.") 
        ) {
          if (entityId.includes(suffix)) {
            if (!pod || entityId.includes(pod.toLowerCase().replace(/\s/g, "_"))) {
              entities[key] = state;
              break;
            }
          }
        }
      }
    }
    return entities;
  }

  _createCard() {
    const shadow = this.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>
        :host {
          --ihidro-green: #2e7d32;
          --ihidro-yellow: #f9a825;
          --ihidro-red: #c62828;
          --ihidro-blue: #1565c0;
          --ihidro-bg: var(--ha-card-background, var(--card-background-color, #fff));
          --ihidro-text: var(--primary-text-color, #212121);
          --ihidro-secondary: var(--secondary-text-color, #727272);
          --ihidro-border: var(--divider-color, #e0e0e0);
        }
        ha-card {
          padding: 16px;
          font-family: var(--paper-font-body1_-_font-family, 'Roboto', sans-serif);
        }
        .header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
        }
        .header-icon {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: linear-gradient(135deg, #1565c0, #42a5f5);
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
          font-weight: bold;
          font-size: 14px;
        }
        .header-title {
          font-size: 16px;
          font-weight: 500;
          color: var(--ihidro-text);
        }
        .header-subtitle {
          font-size: 11px;
          color: var(--ihidro-secondary);
        }
        .grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          margin-bottom: 12px;
        }
        .metric {
          background: var(--ihidro-bg);
          border: 1px solid var(--ihidro-border);
          border-radius: 8px;
          padding: 10px;
        }
        .metric-label {
          font-size: 11px;
          color: var(--ihidro-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 4px;
        }
        .metric-value {
          font-size: 20px;
          font-weight: 600;
          color: var(--ihidro-text);
        }
        .metric-value.small {
          font-size: 16px;
        }
        .metric-sub {
          font-size: 11px;
          color: var(--ihidro-secondary);
          margin-top: 2px;
        }
        .metric-value.green { color: var(--ihidro-green); }
        .metric-value.yellow { color: var(--ihidro-yellow); }
        .metric-value.red { color: var(--ihidro-red); }
        .metric-value.blue { color: var(--ihidro-blue); }
        .full-width { grid-column: 1 / -1; }
        .chart-container {
          grid-column: 1 / -1;
          background: var(--ihidro-bg);
          border: 1px solid var(--ihidro-border);
          border-radius: 8px;
          padding: 10px;
        }
        .chart-title {
          font-size: 11px;
          color: var(--ihidro-secondary);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 8px;
        }
        .bar-chart {
          display: flex;
          align-items: flex-end;
          justify-content: space-around;
          height: 80px;
          gap: 4px;
        }
        .bar-wrapper {
          display: flex;
          flex-direction: column;
          align-items: center;
          flex: 1;
        }
        .bar {
          width: 100%;
          max-width: 32px;
          background: linear-gradient(180deg, #42a5f5, #1565c0);
          border-radius: 3px 3px 0 0;
          min-height: 2px;
          transition: height 0.3s ease;
        }
        .bar-label {
          font-size: 9px;
          color: var(--ihidro-secondary);
          margin-top: 4px;
          text-align: center;
        }
        .bar-value {
          font-size: 9px;
          color: var(--ihidro-text);
          margin-bottom: 2px;
          text-align: center;
        }
        .due-bar {
          grid-column: 1 / -1;
          background: var(--ihidro-bg);
          border: 1px solid var(--ihidro-border);
          border-radius: 8px;
          padding: 10px;
        }
        .progress-track {
          width: 100%;
          height: 6px;
          background: var(--ihidro-border);
          border-radius: 3px;
          margin-top: 6px;
          overflow: hidden;
        }
        .progress-fill {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s ease;
        }
        .anomaly-badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 10px;
          font-size: 11px;
          font-weight: 500;
        }
        .anomaly-normal { background: #e8f5e9; color: #2e7d32; }
        .anomaly-warning { background: #fff8e1; color: #f57f17; }
        .anomaly-danger { background: #ffebee; color: #c62828; }
        .no-data {
          text-align: center;
          color: var(--ihidro-secondary);
          padding: 24px;
          font-size: 13px;
        }
      </style>
      <ha-card>
        <div id="content"></div>
      </ha-card>
    `;
  }

  _updateCard() {
    if (!this.shadowRoot) return;
    const content = this.shadowRoot.getElementById("content");
    if (!content) return;

    const e = this._findEntities();

    if (Object.keys(e).length === 0) {
      content.innerHTML = `
        <div class="no-data">
          <div style="font-size: 24px; margin-bottom: 8px;">⚡</div>
          Nu s-au găsit senzori iHidro.<br>
          Verificați configurarea integrării.
        </div>`;
      return;
    }

    const pod = this._config?.pod || e.sold?.attributes?.utility_account_number || "POD";

    // Sold curent
    const sold = e.sold ? parseFloat(e.sold.state) : null;
    const dueDate = e.sold?.attributes?.due_date || "";
    const soldColor = sold === null ? "" : sold <= 0 ? "green" : "red";

    // Estimare factură
    const estimare = e.estimare ? parseFloat(e.estimare.state) : null;
    const estimareStr = estimare !== null ? `~${estimare.toFixed(0)}` : "—";
    const estimareSub = e.estimare?.attributes?.tendinta_consum || "";

    // Tarif real
    const tarif = e.tarif ? parseFloat(e.tarif.state) : null;
    const tarifStr = tarif !== null ? tarif.toFixed(4) : "—";
    const tendinta = e.tarif?.attributes?.tendinta || "";
    const variatie = e.tarif?.attributes?.variatie || "";

    // Zile până la scadență
    const zile = e.zile ? parseInt(e.zile.state) : null;
    const statusPlata = e.zile?.attributes?.status_plata || "";
    let dueColor = "green";
    let duePct = 100;
    if (zile !== null) {
      if (zile < 0) { dueColor = "red"; duePct = 100; }
      else if (zile <= 3) { dueColor = "yellow"; duePct = Math.max(10, (zile / 30) * 100); }
      else { dueColor = "green"; duePct = Math.max(10, (zile / 30) * 100); }
    }
    const dueColorVar = `var(--ihidro-${dueColor})`;

    // Anomalie
    const anomalie = e.anomalie?.state || "date_insuficiente";
    let anomalyClass = "anomaly-normal";
    let anomalyLabel = "Normal";
    if (anomalie === "anomalie" || anomalie === "consum_ridicat") {
      anomalyClass = anomalie === "anomalie" ? "anomaly-danger" : "anomaly-warning";
      anomalyLabel = anomalie === "anomalie" ? "Anomalie!" : "Consum ridicat";
    } else if (anomalie === "consum_scazut") {
      anomalyClass = "anomaly-normal";
      anomalyLabel = "Consum scăzut";
    } else if (anomalie === "date_insuficiente") {
      anomalyLabel = "—";
      anomalyClass = "";
    }

    // Grafic consum (din atributele senzorului de consum lunar)
    let chartHTML = "";
    const history = e.consum_lunar?.attributes?.history;
    if (history && history.length > 0) {
      const values = history.map((h) => parseFloat(h.consumption) || 0).reverse();
      const labels = history.map((h) => h.month || "").reverse();
      const maxVal = Math.max(...values, 1);

      const bars = values
        .map((v, i) => {
          const height = Math.max(2, (v / maxVal) * 70);
          const label = labels[i] ? labels[i].toString().substring(0, 3) : "";
          return `
            <div class="bar-wrapper">
              <div class="bar-value">${v > 0 ? Math.round(v) : ""}</div>
              <div class="bar" style="height: ${height}px;"></div>
              <div class="bar-label">${label}</div>
            </div>`;
        })
        .join("");

      chartHTML = `
        <div class="chart-container">
          <div class="chart-title">Consum ultimele luni (kWh)</div>
          <div class="bar-chart">${bars}</div>
        </div>`;
    }

    content.innerHTML = `
      <div class="header">
        <div class="header-icon">⚡</div>
        <div>
          <div class="header-title">Hidroelectrica — ${pod}</div>
          <div class="header-subtitle">iHidro v${CARD_VERSION}</div>
        </div>
      </div>

      <div class="grid">
        <div class="metric">
          <div class="metric-label">Sold curent</div>
          <div class="metric-value ${soldColor}">
            ${sold !== null ? sold.toFixed(2) : "—"} <span style="font-size:13px">lei</span>
          </div>
          <div class="metric-sub">${dueDate ? `Scadent: ${dueDate}` : ""}</div>
        </div>

        <div class="metric">
          <div class="metric-label">Estimare factură</div>
          <div class="metric-value small blue">
            ${estimareStr} <span style="font-size:13px">lei</span>
          </div>
          <div class="metric-sub">${estimareSub ? `Consum ${estimareSub}` : "luna viitoare"}</div>
        </div>

        <div class="metric">
          <div class="metric-label">Tarif real</div>
          <div class="metric-value small">
            ${tarifStr} <span style="font-size:11px">lei/kWh</span>
          </div>
          <div class="metric-sub">${tendinta} ${variatie}</div>
        </div>

        <div class="metric">
          <div class="metric-label">Anomalie consum</div>
          <div class="metric-value small">
            ${anomalyClass ? `<span class="anomaly-badge ${anomalyClass}">${anomalyLabel}</span>` : anomalyLabel}
          </div>
          <div class="metric-sub">
            ${e.anomalie?.attributes?.deviatie_vs_medie ? `vs medie: ${e.anomalie.attributes.deviatie_vs_medie}` : ""}
          </div>
        </div>

        <div class="due-bar">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div class="metric-label" style="margin:0">Scadență</div>
            <div style="font-size:13px;font-weight:600;color:${dueColorVar}">
              ${zile !== null ? (zile < 0 ? `Restantă ${Math.abs(zile)}z` : zile === 0 ? "Azi!" : `${zile} zile`) : "—"}
            </div>
          </div>
          <div class="progress-track">
            <div class="progress-fill" style="width:${duePct}%;background:${dueColorVar}"></div>
          </div>
          <div class="metric-sub" style="margin-top:4px">${statusPlata}</div>
        </div>

        ${chartHTML}
      </div>
    `;
  }

  getCardSize() {
    return 5;
  }
}

customElements.define("ihidro-card", IhidroCard);

// Editor element for card configuration
class IhidroCardEditor extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  _render() {
    if (!this.innerHTML) {
      this.innerHTML = `
        <div style="padding: 8px;">
          <label style="display:block;margin-bottom:4px;font-weight:500;">
            POD (opțional — lasă gol pentru auto-detectare):
          </label>
          <input type="text" id="pod-input"
            value="${this._config?.pod || ""}"
            placeholder="ex: RO001E..."
            style="width:100%;padding:8px;border:1px solid #ccc;border-radius:4px;font-size:14px;"
          />
        </div>
      `;
      this.querySelector("#pod-input").addEventListener("input", (e) => {
        this._config = { ...this._config, pod: e.target.value };
        const event = new CustomEvent("config-changed", {
          detail: { config: this._config },
        });
        this.dispatchEvent(event);
      });
    }
  }
}

customElements.define("ihidro-card-editor", IhidroCardEditor);

// Register card with HA
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ihidro-card",
  name: "iHidro Card",
  description:
    "Dashboard card pentru Hidroelectrica România — sold, estimare factură, tarif real, grafic consum, anomalii.",
  preview: true,
  documentationURL: "https://github.com/ria-ebesliu/homeassistant-ihidro",
});

console.info(
  `%c iHidro Card v${CARD_VERSION} `,
  "color: white; background: #1565c0; font-weight: bold; padding: 2px 6px; border-radius: 3px;"
);
