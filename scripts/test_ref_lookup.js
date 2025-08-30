#!/usr/bin/env node
/*
  Test reference field lookup against the dataset used by web/planner.html.
  Mirrors resolveRef() logic from web/app.js and checks multiple codes.

  Usage:
    node scripts/test_ref_lookup.js [CODE ...]

  If no codes are provided, a default list is tested.
*/

const fs = require('fs');
const path = require('path');

function loadAirfields() {
  const p = path.join(__dirname, '..', 'web', 'data', 'airfields.json');
  const raw = fs.readFileSync(p, 'utf8');
  const json = JSON.parse(raw);
  return Array.isArray(json.airfields) ? json.airfields : [];
}

function resolveRef(all, code) {
  if (!code) return null;
  const c = String(code).toUpperCase();
  const candidates = all.filter(a => {
    const icao = String(a.icao || a.code || '').toUpperCase();
    const faa = String(a.code || '').toUpperCase();
    return (
      icao === c || faa === c ||
      (c.length === 3 && icao === `K${c}`) ||
      (c.length === 4 && c.startsWith('K') && faa === c.slice(1))
    );
  });
  return candidates[0] || null;
}

function main() {
  const all = loadAirfields();
  if (!all.length) {
    console.error('No airfields loaded from web/data/airfields.json');
    process.exit(1);
  }

  const tests = process.argv.slice(2);
  const codes = tests.length ? tests : [
    'KMEI', 'MEI', // Meridian Key Field (civil) — may be absent in dataset
    'KNMM', 'NMM', // Meridian NAS (present as KNMM/NMM)
    'KNPA', 'NPA', // NAS Pensacola
    'KNGU', 'NGU', // NAS Norfolk
    'KNDZ', 'NDZ', // NOLF Spencer
  ];

  console.log(`Total airfields: ${all.length}`);
  console.log('Testing codes:', codes.join(', '));
  console.log('---');

  for (const code of codes) {
    const hit = resolveRef(all, code);
    if (!hit) {
      console.log(`${code}: NOT FOUND`);
      continue;
    }
    const icao = String(hit.icao || hit.code || '').toUpperCase();
    const faa = String(hit.code || '').toUpperCase();
    const name = hit.name || '';
    const lat = hit.lat ?? hit.latitude;
    const lon = hit.lon ?? hit.longitude;
    console.log(`${code}: OK -> icao=${icao} faa=${faa} name="${name}" lat=${lat} lon=${lon}`);
  }
}

if (require.main === module) {
  main();
}

