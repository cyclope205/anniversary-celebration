/* Anniversary Celebration — auto-building Lovelace card.
 * Renders every sensor produced by the Anniversary Celebration integration,
 * split into "Vivants" and "Souvenirs", sorted by proximity of the next
 * anniversary, with a 🔔 mark when today's notification has already fired.
 */
const ATTRIBUTION = "Data calculated by Anniversary Celebration";

const MONTHS_FR = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

function formatDob(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const day = String(d.getDate()).padStart(2, "0");
  return `né(e) le ${day} ${MONTHS_FR[d.getMonth()]} ${d.getFullYear()}`;
}

function countdownLabel(days) {
  const n = Number(days);
  if (n <= 0) return "🎉 Aujourd’hui !";
  if (n === 1) return "Demain";
  return `J-${n}`;
}

class AnniversaryCelebrationCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      title_alive: "🎂 Anniversaires",
      title_deceased: "🕯️ Souvenirs",
      show_deceased: true,
      max_items: 0,
      ...config,
    };
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._buildSkeleton();
      this._built = true;
    }
    this._render();
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return { title_alive: "🎂 Anniversaires", title_deceased: "🕯️ Souvenirs", show_deceased: true, max_items: 0 };
  }

  static getConfigElement() {
    return document.createElement("anniversary-celebration-card-editor");
  }

  _buildSkeleton() {
    this.innerHTML = `
      <ha-card>
        <style>
          .ac-wrap { padding: 8px 4px 12px 4px; }
          .ac-section-title {
            font-size: 20px; font-weight: 700; text-align: center;
            margin: 6px 0 8px 0; text-shadow: 0 0 10px rgba(0,0,0,0.2);
          }
          .ac-list { display: flex; flex-direction: column; gap: 3px; padding: 0 10px; }
          .ac-row {
            display: grid;
            grid-template-columns: 34px 1fr auto;
            grid-template-areas: "i n c" "i l c" "i d c";
            align-items: center;
            column-gap: 10px;
            row-gap: 2px;
            padding: 7px 14px;
            border-radius: 14px;
            min-height: 50px;
          }
          .ac-row.alive { background: #18181b; border: 1px solid rgba(255,255,255,0.08); color: #fff; }
          .ac-row.alive.today {
            background: linear-gradient(135deg, rgba(255,214,10,0.22), rgba(24,24,27,0.92));
            border: 1px solid rgba(255,214,10,0.65);
            box-shadow: 0 0 14px 1px rgba(255,214,10,0.35);
          }
          .ac-row.deceased { background: #15181f; border: 1px solid rgba(143,166,199,0.22); color: #c7d4e6; }
          .ac-icon { grid-area: i; width: 22px; text-align: center; }
          .ac-row.alive .ac-icon { color: #ffd60a; }
          .ac-row.deceased .ac-icon { color: #8fa6c7; }
          .ac-name { grid-area: n; font-size: 13px; font-weight: 600; }
          .ac-label { grid-area: l; font-size: 11px; opacity: 0.65; }
          .ac-dob { grid-area: d; font-size: 10px; opacity: 0.45; }
          .ac-badge {
            grid-area: c; justify-self: end; align-self: center;
            font-weight: 700; font-size: 12px; white-space: nowrap;
            padding: 4px 10px; border-radius: 10px;
          }
          .ac-row.alive .ac-badge { color: #ffd60a; background: rgba(255,214,10,0.12); }
          .ac-row.deceased .ac-badge { color: #8fa6c7; background: rgba(143,166,199,0.12); }
          .ac-bell { margin-left: 6px; }
          .ac-empty { text-align: center; opacity: 0.6; font-size: 13px; padding: 10px 0; }
        </style>
        <div class="ac-wrap">
          <div class="ac-section-title">${this._config.title_alive}</div>
          <div class="ac-list" id="ac-alive"></div>
          ${this._config.show_deceased ? `
            <div class="ac-section-title">${this._config.title_deceased}</div>
            <div class="ac-list" id="ac-deceased"></div>
          ` : ""}
        </div>
      </ha-card>
    `;
  }

  _collect() {
    const hass = this._hass;
    const people = Object.values(hass.states).filter(
      (s) => s.attributes && s.attributes.attribution === ATTRIBUTION
    );
    const alive = [];
    const deceased = [];
    for (const s of people) {
      (s.attributes.status === "deceased" ? deceased : alive).push(s);
    }
    const byDays = (a, b) => Number(a.state) - Number(b.state);
    alive.sort(byDays);
    deceased.sort(byDays);
    const max = Number(this._config.max_items) || 0;
    return {
      alive: max > 0 ? alive.slice(0, max) : alive,
      deceased: max > 0 ? deceased.slice(0, max) : deceased,
    };
  }

  _renderRow(stateObj, kind) {
    const a = stateObj.attributes;
    const name = `${a.first_name || ""} ${a.last_name || ""}`.trim() || stateObj.entity_id;
    const ageNow = a.current_years;
    const ageNext = a.years_at_anniversary;
    const today = Number(stateObj.state) <= 0;
    const verb = kind === "deceased" ? "aurait" : "aura";
    const icon = kind === "deceased" ? "mdi:candle" : "mdi:cake-variant";
    const bell = a.notified_today ? '<ha-icon class="ac-bell" icon="mdi:bell-ring" style="--mdc-icon-size:13px;"></ha-icon>' : "";
    return `
      <div class="ac-row ${kind}${today ? " today" : ""}">
        <ha-icon class="ac-icon" icon="${icon}"></ha-icon>
        <div class="ac-name">${name}${ageNow !== undefined ? ` · ${ageNow} ans` : ""}${bell}</div>
        <div class="ac-label">${verb} ${ageNext} ans au prochain anniversaire</div>
        <div class="ac-dob">${formatDob(a.date)}</div>
        <div class="ac-badge">${countdownLabel(stateObj.state)}</div>
      </div>
    `;
  }

  _render() {
    if (!this._hass) return;
    const { alive, deceased } = this._collect();
    const aliveEl = this.querySelector("#ac-alive");
    const deceasedEl = this.querySelector("#ac-deceased");
    if (aliveEl) {
      aliveEl.innerHTML = alive.length
        ? alive.map((s) => this._renderRow(s, "alive")).join("")
        : '<div class="ac-empty">Aucune personne configurée</div>';
    }
    if (deceasedEl) {
      deceasedEl.innerHTML = deceased.length
        ? deceased.map((s) => this._renderRow(s, "deceased")).join("")
        : '<div class="ac-empty">Aucune personne configurée</div>';
    }
  }
}

class AnniversaryCelebrationCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = {
      title_alive: "🎂 Anniversaires",
      title_deceased: "🕯️ Souvenirs",
      show_deceased: true,
      max_items: 0,
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _fire(key, value) {
    this._config = { ...this._config, [key]: value };
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      })
    );
  }

  _render() {
    this.innerHTML = `
      <style>
        .ac-editor-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
        .ac-editor-row label { font-size: 14px; }
        .ac-editor-row input[type="text"], .ac-editor-row input[type="number"] {
          width: 180px; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color, #444);
          background: var(--card-background-color, transparent); color: inherit;
        }
      </style>
      <div class="ac-editor-row">
        <label>Titre — Anniversaires</label>
        <input type="text" id="ac-title-alive" value="${this._config.title_alive}">
      </div>
      <div class="ac-editor-row">
        <label>Afficher Souvenirs (personnes décédées)</label>
        <ha-switch id="ac-show-deceased" ${this._config.show_deceased ? "checked" : ""}></ha-switch>
      </div>
      <div class="ac-editor-row">
        <label>Titre — Souvenirs</label>
        <input type="text" id="ac-title-deceased" value="${this._config.title_deceased}" ${this._config.show_deceased ? "" : "disabled"}>
      </div>
      <div class="ac-editor-row">
        <label>Nombre de personnes affichées (0 = toutes)</label>
        <input type="number" min="0" id="ac-max-items" value="${this._config.max_items}">
      </div>
    `;

    this.querySelector("#ac-title-alive").addEventListener("change", (e) =>
      this._fire("title_alive", e.target.value)
    );
    this.querySelector("#ac-title-deceased").addEventListener("change", (e) =>
      this._fire("title_deceased", e.target.value)
    );
    this.querySelector("#ac-max-items").addEventListener("change", (e) =>
      this._fire("max_items", Number(e.target.value) || 0)
    );
    const toggle = this.querySelector("#ac-show-deceased");
    toggle.addEventListener("change", (e) => {
      this._fire("show_deceased", e.target.checked);
      this._render();
    });
  }
}

customElements.define("anniversary-celebration-card-editor", AnniversaryCelebrationCardEditor);

customElements.define("anniversary-celebration-card", AnniversaryCelebrationCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "anniversary-celebration-card",
  name: "Anniversary Celebration",
  description: "Carte auto-générée des anniversaires (vivants et souvenirs), avec rappel de notification.",
});
