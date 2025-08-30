async function loadData() {
  const res = await fetch('data/airfields.json');
  if (!res.ok) throw new Error('Failed to load dataset');
  return res.json();
}

// (METAR cache loading removed)

// (removed: METAR categories local loader)

// ---- Theme handling (light | dark | auto) ---------------------------------
const THEME_KEY = 'theme';
let themeMql = null;

function getStoredMode() {
  try { return localStorage.getItem(THEME_KEY) || null; } catch (_) { return null; }
}
function setStoredMode(mode) {
  try { localStorage.setItem(THEME_KEY, mode); } catch (_) {}
}
function ensureMql() {
  if (!themeMql && window.matchMedia) {
    themeMql = window.matchMedia('(prefers-color-scheme: dark)');
  }
  return themeMql;
}
function effectiveTheme(mode) {
  const mql = ensureMql();
  if (mode === 'dark' || mode === 'light') return mode;
  return mql && mql.matches ? 'dark' : 'light';
}
function labelForMode(mode) {
  return mode === 'auto' ? 'Theme: Auto' : (mode === 'dark' ? 'Theme: Dark' : 'Theme: Light');
}
function applyThemeMode(mode) {
  const eff = effectiveTheme(mode);
  document.documentElement.setAttribute('data-bs-theme', eff);
  const btn = document.getElementById('themeMenuButton');
  if (btn) btn.textContent = labelForMode(mode);
  if (typeof switchBaseLayer === 'function') switchBaseLayer(eff);
}
function setThemeMode(mode) {
  setStoredMode(mode);
  applyThemeMode(mode);
}
function initTheme() {
  const mode = getStoredMode() || 'auto';
  applyThemeMode(mode);
  const mql = ensureMql();
  if (mql) {
    mql.addEventListener('change', () => {
      const current = getStoredMode() || 'auto';
      if (current === 'auto') applyThemeMode('auto');
    });
  }
  document.querySelectorAll('.theme-option').forEach(el => {
    el.addEventListener('click', () => {
      const m = el.getAttribute('data-theme');
      if (m) setThemeMode(m);
    });
  });
}

// (removed: METAR live loader)

function normType(t) {
  return String(t || '').toUpperCase();
}

function unique(arr) {
  return Array.from(new Set(arr));
}

function passesRunwayFilter(runways, minLen, minWid) {
  if (!minLen && !minWid) return true;
  return runways.some(r => {
    const len = r.length_ft || 0;
    const wid = r.width_ft || 0;
    return (minLen ? len >= minLen : true) && (minWid ? wid >= minWid : true);
  });
}

function passesGearTypeFilter(gear, allowed) {
  if (!allowed.size) return true;
  return gear.some(g => allowed.has(normType(g.type)));
}

// Removed: threshold distance filtering (not reliable)

function createCardNode(a) {
  const li = document.createElement('li');
  li.className = 'col';

  const card = document.createElement('div');
  card.className = 'card h-100 shadow-sm';

  const body = document.createElement('div');
  body.className = 'card-body';

  const header = document.createElement('div');
  header.className = 'mb-1';
  const codeEl = document.createElement('div');
  codeEl.className = 'fw-semibold';
  codeEl.textContent = String(a.icao || a.code || '').toUpperCase();
  header.appendChild(codeEl);
  body.appendChild(header);

  const nameLine = document.createElement('div');
  nameLine.className = 'text-secondary small mb-1';
  nameLine.textContent = a.name || '';
  body.appendChild(nameLine);

  const loc = formatCityState(a);
  if (loc) {
    const locEl = document.createElement('div');
    locEl.className = 'small text-secondary mb-1';
    locEl.textContent = loc;
    body.appendChild(locEl);
  }

  const rws = (a.runways || []).map(r => `${r.designator || ''} ${r.length_ft || '?'}×${r.width_ft || '?'} ft`).slice(0, 6);
  const rwRow = document.createElement('div');
  rwRow.className = 'd-flex flex-wrap gap-2';
  if (rws.length) {
    for (const r of rws) {
      const chip = document.createElement('span');
      chip.className = 'badge text-bg-light border';
      chip.textContent = r;
      rwRow.appendChild(chip);
    }
  } else {
    const chip = document.createElement('span');
    chip.className = 'badge text-bg-light border';
    chip.textContent = 'No runway data';
    rwRow.appendChild(chip);
  }
  body.appendChild(rwRow);

  const gearDiv = document.createElement('div');
  gearDiv.className = 'mt-2 text-secondary small';
  const gearTypes = unique((a.gear || []).map(g => normType(g.type))).join(', ');
  gearDiv.textContent = `Gear: ${gearTypes || '—'}`;
  body.appendChild(gearDiv);

  card.appendChild(body);
  li.appendChild(card);
  return li;
}

function renderList(data, opts = {}) {
  const list = document.getElementById('list');
  list.innerHTML = '';
  const group = !!opts.group;
  if (!group) {
    for (const a of data) list.appendChild(createCardNode(a));
    return;
  }
  const buckets = new Map();
  for (const a of data) {
    const s = String(getState(a) || '').toUpperCase() || 'Unknown';
    if (!buckets.has(s)) buckets.set(s, []);
    buckets.get(s).push(a);
  }
  const keys = Array.from(buckets.keys()).sort((a, b) => {
    if (a === 'Unknown' && b !== 'Unknown') return 1;
    if (b === 'Unknown' && a !== 'Unknown') return -1;
    return cmp(a, b);
  });
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    const headerLi = document.createElement('li');
    headerLi.className = 'row-break';
    const hd = document.createElement('div');
    hd.className = 'group-header mb-1';
    hd.textContent = k;
    headerLi.appendChild(hd);
    list.appendChild(headerLi);
    const items = buckets.get(k) || [];
    for (const a of items) list.appendChild(createCardNode(a));
    // Add a faint separator line between state groups (except after last),
    // occupying a full row so the next header starts at the left edge.
    if (i < keys.length - 1) {
      const sepLi = document.createElement('li');
      sepLi.className = 'row-break my-2';
      const sep = document.createElement('div');
      sep.className = 'state-separator';
      sepLi.appendChild(sep);
      list.appendChild(sepLi);
    }
  }
}

function updateSummary(total, shown) {
  const el = document.getElementById('summary');
  el.textContent = `Showing ${shown} of ${total} airfields`;
}

function getFilters() {
  const minLength = parseInt(document.getElementById('minLength').value, 10);
  const minWidth = parseInt(document.getElementById('minWidth').value, 10);
  const checked = Array.from(document.querySelectorAll('.gearType:checked')).map(cb => cb.value.toUpperCase());
  // Expand allowed set to include HOOK/base synonyms so 'E-28' also matches 'HOOK E-28'
  const allowed = new Set();
  for (const v of checked) {
    const base = v.replace(/^HOOK\s+/, '');
    allowed.add(base);
    allowed.add(`HOOK ${base}`);
  }
  return {
    minLength: isNaN(minLength) ? null : minLength,
    minWidth: isNaN(minWidth) ? null : minWidth,
    allowed,
  };
}

function applyFilters(all) {
  const { minLength, minWidth, allowed } = getFilters();
  return all.filter(a =>
    passesRunwayFilter(a.runways || [], minLength, minWidth) &&
    passesGearTypeFilter(a.gear || [], allowed)
  );
}

function currentSort() {
  const el = document.getElementById('sortSelect');
  return (el && el.value) || 'code';
}

function getState(a) {
  return (
    a.state || a.state_code || a.state_abbrev || a.province || a.region || ''
  );
}

function formatCityState(a) {
  const city = (a.city || '').toString().trim();
  const st = (getState(a) || '').toString().trim();
  if (city && st) return `${city}, ${st}`;
  if (city) return city;
  if (st) return st;
  return '';
}

function cmp(a, b) {
  return a.localeCompare(b, undefined, { sensitivity: 'base' });
}

function sortData(arr, mode) {
  const data = arr.slice();
  if (mode === 'name') {
    data.sort((x, y) => cmp(String(x.name || ''), String(y.name || '')) || cmp(String(x.code || x.icao || ''), String(y.code || y.icao || '')));
  } else if (mode === 'state_group') {
    data.sort((x, y) => cmp(String(getState(x)).toUpperCase(), String(getState(y)).toUpperCase()) || cmp(String(x.code || x.icao || ''), String(y.code || y.icao || '')));
  } else {
    data.sort((x, y) => cmp(String(x.code || x.icao || ''), String(y.code || y.icao || '')) || cmp(String(x.name || ''), String(y.name || '')));
  }
  return data;
}

let mapInstance = null;
let mapInited = false;
let markerLayer = null;
let baseLight = null;
let baseDark = null;
// (METAR timestamp removed)
const markerStyle = {
  radius: 7,
  fillColor: '#0d6efd',
  color: '#ffffff',
  weight: 2,
  opacity: 0.9,
  fillOpacity: 0.95,
};

// (METAR helpers removed)

// (removed: toast helper)

// (removed: METAR helpers)

function initMap(all) {
  // KMEI (Meridian Key Field) approx
  const KMEI = { lat: 32.3373, lon: -88.7519 };
  if (!mapInstance) {
    mapInstance = L.map('map', { zoomControl: true }).setView([KMEI.lat, KMEI.lon], 8);
    baseLight = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap contributors'
    });
    baseDark = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap contributors © CARTO'
    });
    const theme = document.documentElement.getAttribute('data-bs-theme') || 'light';
    (theme === 'dark' ? baseDark : baseLight).addTo(mapInstance);
    markerLayer = L.layerGroup().addTo(mapInstance);
  } else {
    mapInstance.setView([KMEI.lat, KMEI.lon], 8);
  }
  mapInstance.invalidateSize();
  const ms = document.getElementById('mapSummary');
  if (ms) ms.textContent = `${all.length} airfields loaded`;
  mapInited = true;
}

function switchBaseLayer(theme) {
  if (!mapInstance || !baseLight || !baseDark) return;
  const wantDark = theme === 'dark';
  if (wantDark) {
    if (mapInstance.hasLayer(baseLight)) mapInstance.removeLayer(baseLight);
    if (!mapInstance.hasLayer(baseDark)) baseDark.addTo(mapInstance);
  } else {
    if (mapInstance.hasLayer(baseDark)) mapInstance.removeLayer(baseDark);
    if (!mapInstance.hasLayer(baseLight)) baseLight.addTo(mapInstance);
  }
}

// (removed: autoscroll helper)

function renderMarkers(data) {
  if (!mapInstance || !markerLayer) return;
  markerLayer.clearLayers();
  for (const a of data) {
    const lat = a.lat ?? a.latitude;
    const lon = a.lon ?? a.longitude;
    if (typeof lat !== 'number' || typeof lon !== 'number') continue;
    const m = L.circleMarker([lat, lon], markerStyle);
    const gearTypes = unique((a.gear || []).map(g => normType(g.type))).join(', ');
    const rws = (a.runways || []).map(r => `${r.designator || ''} ${r.length_ft || '?'}×${r.width_ft || '?'} ft`).slice(0, 6);
    const html = `
      <div>
        <div class="fw-semibold">${a.code || a.icao || ''} <span class="text-secondary">${a.name || ''}</span></div>
        
        <div class="small text-secondary">Gear: ${gearTypes || '—'}</div>
        <div class="mt-1 small">${rws.map(x => `<span class='badge text-bg-light border me-1'>${x}</span>`).join('')}</div>
      </div>`;
    m.bindPopup(html, { maxWidth: 300 });
    m.on('mouseover', () => m.setStyle({ radius: markerStyle.radius + 2 }));
    m.on('mouseout', () => m.setStyle({ radius: markerStyle.radius }));
    m.addTo(markerLayer);
  }
}

function wireUI(all) {
  const inputs = [
    document.getElementById('minLength'),
    document.getElementById('minWidth'),
    ...Array.from(document.querySelectorAll('.gearType')),
  ];
  const onChange = () => {
    const sortMode = currentSort();
    const filtered = applyFilters(all);
    const sorted = sortData(filtered, sortMode);
    const group = sortMode === 'state_group';
    renderList(sorted, { group });
    updateSummary(all.length, sorted.length);
    if (mapInited) renderMarkers(sorted);
  };
  inputs.forEach(i => i.addEventListener('input', onChange));
  inputs.forEach(i => i.addEventListener('change', onChange));
  const sortEl = document.getElementById('sortSelect');
  if (sortEl) sortEl.addEventListener('change', onChange);
  document.getElementById('resetBtn').addEventListener('click', () => {
    document.getElementById('minLength').value = '';
    document.getElementById('minWidth').value = '';
    document.querySelectorAll('.gearType').forEach(cb => cb.checked = true);
    onChange();
  });
  // Tab activation: initialize map when Map tab shown
  const mapTab = document.getElementById('map-tab');
  if (mapTab) {
    mapTab.addEventListener('shown.bs.tab', () => {
      // Ensure user sees the map at the very top
      try {
        const mapEl = document.getElementById('map');
        if (mapEl) mapEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else window.scrollTo({ top: 0, behavior: 'smooth' });
      } catch (_) {}
      document.body.classList.add('map-mode');
      if (!mapInited) initMap(all);
      // Ensure Leaflet sizes after the fade/display swap completes
      setTimeout(() => mapInstance && mapInstance.invalidateSize(), 220);
      // Render markers for current filter state
      const filtered = applyFilters(all);
      const sorted = sortData(filtered, currentSort());
      renderMarkers(sorted);
    });
  }
  // Remove map-mode when switching back to Table tab
  const tableTab = document.getElementById('table-tab');
  if (tableTab) {
    tableTab.addEventListener('shown.bs.tab', () => {
      document.body.classList.remove('map-mode');
    });
  }
  // Initialize the map in the background as well, so it's ready when the tab opens
  try {
    if (!mapInited && typeof L !== 'undefined') {
      initMap(all);
      const filtered = applyFilters(all);
      const sorted = sortData(filtered, currentSort());
      renderMarkers(sorted);
    } else if (typeof L === 'undefined') {
      const ms = document.getElementById('mapSummary');
      if (ms) ms.textContent = 'Map library failed to load';
    }
  } catch (_) {
    // ignore; will retry on tab shown
  }
  onChange();
}

(async () => {
  try {
    // Theme init and menu wiring
    initTheme();

    const data = await loadData();
    const all = (data.airfields || []).map(a => ({ ...a }));
    wireUI(all);
  } catch (e) {
    const list = document.getElementById('list');
    list.innerHTML = `<li class=\"col\"><div class=\"alert alert-danger\" role=\"alert\">Failed to load data: ${e}</div></li>`;
  }
})();
