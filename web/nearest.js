async function loadData() {
  const res = await fetch('data/airfields.json');
  if (!res.ok) throw new Error('Failed to load dataset');
  return res.json();
}

// Theme wiring (match planner/index behavior)
(function initThemeMenu() {
  const THEME_KEY = 'theme';
  function getStoredMode() { try { return localStorage.getItem(THEME_KEY) || 'auto'; } catch (_) { return 'auto'; } }
  function setStoredMode(mode) { try { localStorage.setItem(THEME_KEY, mode); } catch (_) {} }
  function effectiveTheme(mode) {
    if (mode === 'dark' || mode === 'light') return mode;
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    return prefersDark ? 'dark' : 'light';
  }
  function label(mode) { return mode === 'auto' ? 'Theme: Auto' : (mode === 'dark' ? 'Theme: Dark' : 'Theme: Light'); }
  function apply(mode) {
    const eff = effectiveTheme(mode);
    document.documentElement.setAttribute('data-bs-theme', eff);
    const btn = document.getElementById('themeMenuButton');
    if (btn) btn.textContent = label(mode);
    if (typeof switchBaseLayer === 'function') switchBaseLayer(eff);
  }
  const stored = getStoredMode();
  apply(stored);
  window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.theme-option').forEach(el => el.addEventListener('click', () => {
      const m = el.getAttribute('data-theme');
      if (m) { setStoredMode(m); apply(m); }
    }));
  });
})();

// Helpers
function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
function distanceNm(lat1, lon1, lat2, lon2) {
  const toRad = d => (d * Math.PI) / 180;
  const R_km = 6371.0088;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const km = R_km * c;
  return km * 0.539957; // km -> NM
}

function resolveRef(all, code) {
  if (!code) return null;
  const c = code.toUpperCase().trim();
  const candidates = all.filter(a => {
    const icao = String(a.icao || a.code || '').toUpperCase();
    const faa = String(a.code || '').toUpperCase();
    // match exact ICAO or FAA code, allow 'K' prefix flexibility
    return (
      icao === c || faa === c ||
      (c.length === 3 && icao === `K${c}`) ||
      (c.length === 4 && c.startsWith('K') && faa === c.slice(1))
    );
  });
  return candidates[0] || null;
}

function fmtNm(n) {
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(1)} NM`;
}

function formatCityState(a) {
  const city = a.city || a.municipality || '';
  const st = a.state || a.state_code || a.state_abbrev || '';
  const parts = [city, st].filter(Boolean);
  return parts.join(', ');
}

function computeNearest(all, ref, count = 5) {
  const rlat = ref.lat ?? ref.latitude;
  const rlon = ref.lon ?? ref.longitude;
  if (typeof rlat !== 'number' || typeof rlon !== 'number') return [];
  const refCode = String(ref.icao || ref.code || '').toUpperCase();
  const candidates = [];
  for (const a of all) {
    const lat = a.lat ?? a.latitude;
    const lon = a.lon ?? a.longitude;
    if (typeof lat !== 'number' || typeof lon !== 'number') continue;
    const code = String(a.icao || a.code || '').toUpperCase();
    if (code === refCode) continue; // exclude the same field
    const d = distanceNm(rlat, rlon, lat, lon);
    candidates.push({ a, d });
  }
  candidates.sort((x, y) => x.d - y.d);
  return candidates.slice(0, count);
}

function renderResults(pairs, ref) {
  const ul = document.getElementById('results');
  ul.innerHTML = '';
  if (!pairs.length) {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center';
    li.textContent = 'No results.';
    ul.appendChild(li);
    return;
  }
  for (const { a, d } of pairs) {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center';

    const left = document.createElement('div');
    const code = (a.icao || a.code || '').toString().toUpperCase();
    const name = a.name || '';
    const loc = formatCityState(a);
    left.innerHTML = `<div class="fw-semibold">${code} <span class="text-secondary">${name}</span></div>` +
                     (loc ? `<div class="small text-secondary">${loc}</div>` : '');

    const right = document.createElement('div');
    right.className = 'text-nowrap result-distance fw-semibold';
    right.textContent = fmtNm(d);

    li.appendChild(left);
    li.appendChild(right);
    ul.appendChild(li);
  }
}

function setStatus(msg) {
  const el = document.getElementById('status');
  if (el) el.textContent = msg || '';
}

(function mapModule(){
  let mapInstance = null;
  let markerLayer = null;
  let lineLayer = null;
  let baseLight = null;
  let baseDark = null;
  let initTries = 0;
  const MAX_INIT_TRIES = 40; // ~8s if interval 200ms
  const markerStyle = {
    radius: 7,
    fillColor: '#0d6efd',
    color: '#ffffff',
    weight: 2,
    opacity: 0.9,
    fillOpacity: 0.95,
  };
  const refMarkerStyle = {
    radius: 8,
    fillColor: '#dc3545',
    color: '#ffffff',
    weight: 2,
    opacity: 0.95,
    fillOpacity: 0.98,
  };
  const lineStyle = {
    color: '#0d6efd',
    weight: 2,
    opacity: 0.6,
  };

  function initMap() {
    if (typeof L === 'undefined') {
      if (initTries++ < MAX_INIT_TRIES) setTimeout(initMap, 200);
      const ms = document.getElementById('mapSummary');
      if (ms) ms.textContent = 'Waiting for map library…';
      return;
    }
    if (!mapInstance) {
      // Continental US default view
      mapInstance = L.map('map', { zoomControl: true }).setView([39.0, -98.0], 4);
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
      // Draw lines below markers
      lineLayer = L.layerGroup().addTo(mapInstance);
      markerLayer = L.layerGroup().addTo(mapInstance);
      setTimeout(() => mapInstance && mapInstance.invalidateSize(), 0);
    }
  }

  function fitTo(ref, pairs) {
    if (!mapInstance || typeof L === 'undefined') return;
    const bounds = [];
    const rlat = ref.lat ?? ref.latitude;
    const rlon = ref.lon ?? ref.longitude;
    if (typeof rlat === 'number' && typeof rlon === 'number') bounds.push([rlat, rlon]);
    for (const { a } of pairs) {
      const lat = a.lat ?? a.latitude;
      const lon = a.lon ?? a.longitude;
      if (typeof lat === 'number' && typeof lon === 'number') bounds.push([lat, lon]);
    }
    if (bounds.length >= 2) {
      mapInstance.fitBounds(bounds, { padding: [24, 24] });
    } else if (bounds.length === 1) {
      mapInstance.setView(bounds[0], 8);
    }
  }

  function renderMap(ref, pairs) {
    if (typeof L === 'undefined') {
      const ms = document.getElementById('mapSummary');
      if (ms) ms.textContent = 'Map library not ready';
      initMap();
      return;
    }
    initMap();
    if (!mapInstance || !markerLayer) return;
    markerLayer.clearLayers();
    if (lineLayer) lineLayer.clearLayers();

    // Reference marker
    if (ref) {
      const rlat = ref.lat ?? ref.latitude;
      const rlon = ref.lon ?? ref.longitude;
      if (typeof rlat === 'number' && typeof rlon === 'number') {
        const code = String(ref.icao || ref.code || '').toUpperCase();
        const name = ref.name || '';
        const m = L.circleMarker([rlat, rlon], refMarkerStyle).bindPopup(`<div class="fw-semibold">${code} <span class="text-secondary">${name}</span></div>`);
        m.addTo(markerLayer);
      }
      const refEl = document.getElementById('mapRef');
      if (refEl) {
        const code = String(ref.icao || ref.code || '').toUpperCase();
        refEl.textContent = `Reference: ${code}`;
      }
    }

    // Nearest markers and connecting lines
    for (const { a, d } of pairs) {
      const lat = a.lat ?? a.latitude;
      const lon = a.lon ?? a.longitude;
      if (typeof lat !== 'number' || typeof lon !== 'number') continue;
      const code = (a.icao || a.code || '').toString().toUpperCase();
      const name = a.name || '';
      const html = `<div class="fw-semibold">${code} <span class="text-secondary">${name}</span></div><div class="small text-secondary">${d.toFixed(1)} NM</div>`;
      const m = L.circleMarker([lat, lon], markerStyle).bindPopup(html, { maxWidth: 280 });
      m.addTo(markerLayer);
      // Draw connection from reference to this airfield
      if (ref && lineLayer) {
        const rlat = ref.lat ?? ref.latitude;
        const rlon = ref.lon ?? ref.longitude;
        if (typeof rlat === 'number' && typeof rlon === 'number') {
          const pl = L.polyline([[rlat, rlon], [lat, lon]], lineStyle);
          pl.bindTooltip(`${d.toFixed(1)} NM`, { sticky: true });
          pl.on('mouseover', () => pl.setStyle({ weight: 4, opacity: 0.85 }));
          pl.on('mouseout', () => pl.setStyle({ weight: lineStyle.weight, opacity: lineStyle.opacity }));
          pl.addTo(lineLayer);
        }
      }
    }

    const ms = document.getElementById('mapSummary');
    if (ms) ms.textContent = `${pairs.length} nearest shown`;
    if (ref) fitTo(ref, pairs);
  }

  // expose for theme switching and renderer
  window.switchBaseLayer = function(theme) {
    if (!mapInstance || !baseLight || !baseDark) return;
    const wantDark = theme === 'dark';
    if (wantDark) {
      if (mapInstance.hasLayer(baseLight)) mapInstance.removeLayer(baseLight);
      if (!mapInstance.hasLayer(baseDark)) baseDark.addTo(mapInstance);
    } else {
      if (mapInstance.hasLayer(baseDark)) mapInstance.removeLayer(baseDark);
      if (!mapInstance.hasLayer(baseLight)) baseLight.addTo(mapInstance);
    }
  };

  window._nearest_map = { initMap, renderMap };
})();

(async () => {
  let all = [];
  // Initialize map early so it appears even if data fetch fails (e.g., file:// CORS)
  if (window._nearest_map && typeof window._nearest_map.initMap === 'function') {
    window._nearest_map.initMap();
  }
  try {
    const data = await loadData();
    all = (data.airfields || []).map(a => ({ ...a }));
    setStatus(`${all.length} airfields loaded`);
    // Ensure map is initialized (no-op if already)
    if (window._nearest_map && typeof window._nearest_map.initMap === 'function') {
      window._nearest_map.initMap();
    }
  } catch (e) {
    setStatus(`Failed to load data: ${e}`);
    // Keep page usable even without data
  }

  const input = document.getElementById('destField');
  const btn = document.getElementById('findBtn');
  function run() {
    const raw = (input.value || '').trim();
    if (!raw) { setStatus('Enter an ICAO or FAA code.'); renderResults([], null); return; }
    const ref = resolveRef(all, raw);
    if (!ref) { setStatus(`Destination “${raw.toUpperCase()}” not found in dataset.`); renderResults([], null); return; }
    const code = String(ref.icao || ref.code || '').toUpperCase();
    const name = ref.name || '';
    setStatus(`Reference set: ${code}${name ? ' — ' + name : ''}`);
    const nearest = computeNearest(all, ref, 5);
    renderResults(nearest, ref);
    if (window._nearest_map && typeof window._nearest_map.renderMap === 'function') {
      window._nearest_map.renderMap(ref, nearest);
    }
  }
  btn.addEventListener('click', run);
  input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') run(); });

})();
