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
    document.documentElement.setAttribute('data-bs-theme', effectiveTheme(mode));
    const btn = document.getElementById('themeMenuButton');
    if (btn) btn.textContent = label(mode);
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

(async () => {
  let all = [];
  try {
    const data = await loadData();
    all = (data.airfields || []).map(a => ({ ...a }));
    setStatus(`${all.length} airfields loaded`);
  } catch (e) {
    setStatus(`Failed to load data: ${e}`);
    return;
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
  }
  btn.addEventListener('click', run);
  input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') run(); });
})();

