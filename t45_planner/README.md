T-45 Planner — Arresting Gear Airfields

A small toolkit to discover and explore U.S. airfields that have aircraft arresting gear, derived from FAA NASR AIXM data. It includes:

- A Python pipeline to download official FAA AIXM ZIPs and extract XML files only
- A parser that finds arresting-gear mentions and summarizes runway data
- A simple, static web UI to filter and view the results on a map


## Quick Start

1) Python environment

- Python 3.10+ recommended (3.11 tested)
- Install minimal deps:
  
  ```bash
 python -m pip install requests beautifulsoup4
  ```

2) Get AIXM XML (two options)

- Option A: Use the built-in FAA downloader to fetch the latest NASR cycle and extract only XML files:
  
  ```bash
  # List available cycle dates (28‑day cycles)
  python faa_aixm_pipeline.py --list

  # Download latest AIXM 5.1 (Airports/NAVAIDs/AWOS/AWY) and extract XMLs
  python faa_aixm_pipeline.py --kind aixm51 --root ./nasr_data

  # Or download both 5.1 and SAA 5.0
 python faa_aixm_pipeline.py --kind both --root ./nasr_data
  ```

- Option B: Use the sample APT_AIXM.xml in `data/` (good for offline testing)

3) Build the dataset consumed by the web UI

- From FAA-downloaded data (adjust the date to the cycle you fetched):
  
  ```bash
  python find_arresting_gear_airfields.py \
    --root nasr_data/YYYY-MM-DD/aixm51/xml \
    --format json \
    --out web/data/airfields.json
  ```

- From the included sample file:
  
  ```bash
  python find_arresting_gear_airfields.py \
    --root data \
    --format json \
    --out web/data/airfields.json
  ```

4) Run the web UI (static site)

```bash
cd web
python -m http.server 8000
# open http://localhost:8000/
```


## Features

- Parses AIXM Airport/Heliport features and notes to find arresting-gear mentions (e.g., BAK‑12/12A/12B, BAK‑14, MB60, EMAS)
- Extracts per‑runway‑end lengths and widths; reduces length by displaced threshold when available
- Outputs a compact JSON dataset for a frontend map and filter UI
- Downloader discovers NASR cycles automatically and extracts only XML entries from ZIPs with safe path handling


## Repository Layout

- `faa_aixm_pipeline.py` — Discover, download, and extract FAA NASR AIXM ZIPs (XML only), organized by date/kind with a manifest
- `find_arresting_gear_airfields.py` — Parse AIXM XML to identify airfields with arresting gear and summarize runways; can emit text, CSV, codes, or JSON
- `data/` — Example input (`APT_AIXM.xml`) for offline testing
- `web/` — Static frontend: `index.html` (home), `planner.html` (app), `app.js`, `styles.css`, and output data in `web/data/`

Optional: add `web/data/meta.json` so the homepage can show exact data currency:

```json
{
  "effective_date": "YYYY-MM-DD",
  "generated_at": "2025-08-29T17:00:00Z",
  "cycle_length_days": 28
}
```

If omitted, the homepage falls back to the `Last-Modified` time of `web/data/airfields.json` and assumes a 28‑day cycle to estimate staleness.


## Data Notes & Limitations

- Detection relies on free‑text notes in AIXM; formatting varies, so some gear or distances may be missed or over‑inclusive
- Distance parsing captures common patterns like “FT FM THR” and parenthetical feet; context can be ambiguous
- Runway length per end is reduced by displaced threshold when available; many entries may not include that detail
- The included JSON and sample XML are for demonstration only. Always verify with official sources and NOTAMs before operational use


## Common Commands

- List cycles: `python faa_aixm_pipeline.py --list`
- Download latest AIXM 5.1: `python faa_aixm_pipeline.py --kind aixm51 --root ./nasr_data`
- Export arresting‑gear airfields JSON: `python find_arresting_gear_airfields.py --root <xml_root> --format json --out web/data/airfields.json`
- Serve UI locally: `cd web && python -m http.server 8000`


## Running Tests

- This repo includes unit tests for the FAA pipeline and extractors (unittest-based).
- Run all tests from the project root:

  ```bash
  python -m unittest -v
  ```

  Or run a specific file:

  ```bash
  python -m unittest tests/test_faa_aixm_pipeline.py -v
  ```


## CLI Reference

`faa_aixm_pipeline.py` (download + extract only XMLs)
- `--root PATH`: Output directory (default `./nasr_aixm_data`).
- `--date YYYY-MM-DD`: Target effective date (default: latest discovered).
- `--kind {aixm51|aixm50|both}`: Which package(s) to process (default `aixm51`).
- `--list`: Print discovered cycle dates and exit.
- `--no-keep-zips`: Delete ZIPs after extraction.
- `--quiet`: Reduce progress output.

`find_arresting_gear_airfields.py` (produce dataset)
- `--root PATH`: Folder containing AIXM XML (e.g., `nasr_data/<date>/aixm51/xml`).
- `--format {text|csv|codes|json}`: Output format (default `text`).
- `--out PATH`: When `--format json`, write JSON to this path (otherwise prints to stdout).


## Attribution

- Data: FAA NASR AIXM (official FAA sources; updates on a 28‑day cycle)
- Map tiles: OpenStreetMap contributors
- UI: Bootstrap 5, Leaflet


## Disclaimer

This tool is for research and planning support only and is not a source for real‑time operational decisions. Validate all information using official publications and current NOTAMs.
