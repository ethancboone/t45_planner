#!/usr/bin/env python3
"""
FAA AIXM NASR Downloader & XML Extractor (official FAA sources)

What it does
------------
1) Discovers NASR cycles on the FAA NASR Subscription index (28-day cycles).
2) For a selected cycle, finds AIXM 5.1 (Airports/NAVAIDs/AWOS/AWY) and/or
   AIXM 5.0 (SAA) ZIP links on the cycle page.
3) Downloads the requested ZIP(s).
4) Extracts ONLY the XML files (skips readmes/csv/pdf/etc.) with path safety.
5) Organizes output as:
   <root>/<YYYY-MM-DD>/<kind>/xml/<dataset_name>/<files>.xml
   and writes <root>/<YYYY-MM-DD>/<kind>/manifest.json

Designed to be scaled behind a web service:
- Pure functions you can import and call (no hard CLI-only structure).
- Deterministic, idempotent paths.
- JSON manifest for quick indexing/search on your site.
- Minimal deps (requests, beautifulsoup4).

Usage
-----
# Install deps:
#   python -m pip install requests beautifulsoup4

# Download latest cycle AIXM 5.1, extract XMLs, build manifest:
#   python faa_aixm_pipeline.py --kind aixm51 --root ./nasr_data

# Download both AIXM 5.1 + 5.0 SAA:
#   python faa_aixm_pipeline.py --kind both --root ./nasr_data

# List discovered effective dates:
#   python faa_aixm_pipeline.py --list

# Target a specific date (must exist on FAA):
#   python faa_aixm_pipeline.py --date 2025-06-12 --kind aixm51 --root ./nasr_data

Notes
-----
- Typical ZIPs are hosted under per-cycle pages and/or nfdc.faa.gov.
- This script only extracts *.xml (case-insensitive).
- Safe extraction guards against path traversal.

Author: you :)
"""

from __future__ import annotations
import argparse
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zipfile import ZipFile, ZipInfo

import requests
from bs4 import BeautifulSoup

# ------------------------------
# Config
# ------------------------------
BASE_INDEX_URL = "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/"
TIMEOUT = 30
RETRY_COUNT = 4
RETRY_SLEEP = 2.0
USER_AGENT = "Mozilla/5.0 (compatible; FAA-AIXM-Downloader/1.1; +https://www.faa.gov/)"

DATE_LINK_RE = re.compile(r"/NASR_Subscription/(\d{4}-\d{2}-\d{2})/?$")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

# ------------------------------
# Data classes
# ------------------------------
@dataclass
class DownloadResult:
    kind: str              # "aixm51" or "aixm50"
    date: str              # YYYY-MM-DD
    url: str               # source URL
    zip_path: str          # absolute path
    sha256: str            # sha256 of the zip
    size_bytes: int

@dataclass
class ExtractResult:
    kind: str
    date: str
    zip_filename: str
    dataset_name: str
    files: List[str]       # relative paths under kind dir
    total_bytes: int

@dataclass
class Manifest:
    date: str
    created_unix: int
    downloads: List[DownloadResult]
    extracts: List[ExtractResult]
    version: int = 1


# ------------------------------
# HTTP helpers
# ------------------------------
def _get(url: str) -> requests.Response:
    """GET with retries."""
    last = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_SLEEP * attempt)
            else:
                raise
    raise last  # type: ignore


# ------------------------------
# Discovery
# ------------------------------
def discover_effective_dates(index_html: str) -> List[str]:
    """Return effective dates (YYYY-MM-DD) found on the index page, newest-first."""
    soup = BeautifulSoup(index_html, "html.parser")
    dates: List[str] = []
    for a in soup.find_all("a", href=True):
        m = DATE_LINK_RE.search(a.get("href"))
        if m:
            dates.append(m.group(1))
    return sorted(set(dates), reverse=True)


def find_aixm_links(cycle_html: str) -> Dict[str, str]:
    """
    Parse a cycle page and return dict:
      - "aixm51": URL to AIXM 5.1 zip (Airports/NAVAIDs/AWOS/AWY)
      - "aixm50": URL to SAA AIXM 5.0 zip (special use airspace)
    """
    soup = BeautifulSoup(cycle_html, "html.parser")
    links: Dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "").strip().lower()

        # normalize to absolute
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.faa.gov" + href

        href_l = href.lower()
        if "aixm" in href_l and href_l.endswith(".zip"):
            if "5.1" in href_l or "aixm5.1" in href_l or "aixm51" in href_l or re.search(r"[^0-9]51[^0-9]", href_l):
                links["aixm51"] = href
            if "5.0" in href_l or "aixm5.0" in href_l or "aixm50" in href_l or "saa" in href_l or re.search(r"[^0-9]50[^0-9]", href_l):
                links["aixm50"] = href

        if "aixm 5.1" in text and href_l.endswith(".zip"):
            links["aixm51"] = href
        if ("aixm 5.0" in text or "saa" in text) and href_l.endswith(".zip"):
            links["aixm50"] = href

    return links


# ------------------------------
# Downloading
# ------------------------------
def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, out_dir: Path, progress: bool = True) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1] or "download.zip"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    out_path = out_dir / safe_name

    with SESSION.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0") or "0")
        chunk = 1024 * 1024
        written = 0
        with open(out_path, "wb") as f:
            for part in r.iter_content(chunk_size=chunk):
                if not part:
                    continue
                f.write(part)
                if progress:
                    written += len(part)
                    if total:
                        pct = (written / total) * 100
                        print(f"\r  ↳ {safe_name}: {written/1_048_576:.1f}/{total/1_048_576:.1f} MiB ({pct:5.1f}%)", end="")
                    else:
                        print(f"\r  ↳ {safe_name}: {written/1_048_576:.1f} MiB", end="")
        if progress:
            print()
    return out_path


# ------------------------------
# Extraction (XML only, safe)
# ------------------------------
def _is_xml_name(name: str) -> bool:
    return name.lower().endswith(".xml")


def _safe_join(base: Path, *paths: str) -> Path:
    """Join paths and ensure the result stays under base (no traversal)."""
    p = base.joinpath(*paths).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise ValueError(f"Unsafe path traversal detected: {p}")
    return p


def infer_dataset_name(zip_filename: str) -> str:
    """
    Create a "dataset_name" from the zip filename to group related XMLs.
    Examples:
        'aixm5.1.zip' -> 'aixm5_1'
        'SAA_AIXM_20250612.zip' -> 'saa_aixm_20250612'
    """
    stem = Path(zip_filename).stem
    name = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    if not name:
        name = "dataset"
    return name


def extract_xmls_from_zip(zip_path: Path, dest_dir: Path, kind: str, date: str) -> ExtractResult:
    """
    Extract only XML files from zip into:
      dest_dir/<date>/<kind>/xml/<dataset_name>/
    Returns ExtractResult with per-file relative paths (under <date>/<kind>/)
    """
    zip_filename = zip_path.name
    dataset = infer_dataset_name(zip_filename)

    kind_root = _safe_join(dest_dir, date, kind)
    xml_root = _safe_join(kind_root, "xml", dataset)
    xml_root.mkdir(parents=True, exist_ok=True)

    rel_files: List[str] = []
    total_bytes = 0

    with ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if not _is_xml_name(info.filename):
                continue

            # Normalize the internal path to a safe filename under dataset
            # Keep only the basename to avoid deep nesting (optional: keep subdirs)
            # Here we keep subdirectories but sanitize.
            parts = [p for p in Path(info.filename).parts if p not in ("", ".", "..")]
            # Final target path
            target = _safe_join(xml_root, *parts)

            # Ensure parent exists
            target.parent.mkdir(parents=True, exist_ok=True)

            # Extract with stream to avoid Zip Slip
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                data = src.read()
                dst.write(data)
                total_bytes += len(data)

            rel_path = str(target.relative_to(kind_root))  # relative under <date>/<kind>/
            rel_files.append(rel_path)

    return ExtractResult(
        kind=kind,
        date=date,
        zip_filename=zip_filename,
        dataset_name=dataset,
        files=sorted(rel_files),
        total_bytes=total_bytes,
    )


# ------------------------------
# Orchestration
# ------------------------------
def ensure_manifest_path(root: Path, date: str, kind: str) -> Path:
    """Return the path for manifest.json under <root>/<date>/<kind>/manifest.json"""
    kind_root = root / date / kind
    kind_root.mkdir(parents=True, exist_ok=True)
    return kind_root / "manifest.json"


def load_existing_manifest(path: Path) -> Optional[Manifest]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # tolerate forward/backward changes
        downloads = [DownloadResult(**d) for d in obj.get("downloads", [])]
        extracts = [ExtractResult(**e) for e in obj.get("extracts", [])]
        return Manifest(
            date=obj.get("date", ""),
            created_unix=obj.get("created_unix", 0),
            downloads=downloads,
            extracts=extracts,
            version=int(obj.get("version", 1)),
        )
    except Exception:
        return None


def save_manifest(path: Path, manifest: Manifest) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            **asdict(manifest),
            # dataclasses -> plain dict is fine; lists already converted above
        }, f, indent=2)


def run_pipeline(
    root: Path,
    date: Optional[str],
    kinds: Iterable[str],  # "aixm51", "aixm50"
    keep_zips: bool = True,
    progress: bool = True,
) -> None:
    """
    High-level workflow:
      - discover date if not provided
      - per kind: find link, download, checksum, extract XMLs
      - update manifest.json for each kind
    """
    # 1) Discover dates
    print(f"[1/4] Fetching NASR index: {BASE_INDEX_URL}")
    idx_resp = _get(BASE_INDEX_URL)
    dates = discover_effective_dates(idx_resp.text)
    if not dates:
        raise RuntimeError("No effective dates found on NASR index page.")

    target_date = date or dates[0]
    if target_date not in dates:
        print(f"  • WARNING: {target_date} not listed on index; attempting anyway.")

    # 2) Fetch cycle page & locate links
    cycle_url = BASE_INDEX_URL.rstrip("/") + f"/{target_date}"
    print(f"[2/4] Fetching cycle page: {cycle_url}")
    cycle_resp = _get(cycle_url)
    links = find_aixm_links(cycle_resp.text)
    if not links:
        raise RuntimeError("No AIXM links found on the cycle page. FAA page may have changed.")

    # For each requested kind, download and extract
    for kind in kinds:
        if kind not in ("aixm51", "aixm50"):
            continue

        manifest_path = ensure_manifest_path(root, target_date, kind)
        manifest = load_existing_manifest(manifest_path) or Manifest(
            date=target_date, created_unix=int(time.time()), downloads=[], extracts=[]
        )

        if kind not in links:
            print(f"[WARN] No link found for {kind} on {target_date}. Skipping.")
            save_manifest(manifest_path, manifest)
            continue

        url = links[kind]
        print(f"[3/4] Downloading {kind}: {url}")
        zips_dir = root / target_date / kind / "zips"
        zip_path = download_file(url, zips_dir, progress=progress)

        # checksum + size
        sha = sha256_file(zip_path)
        size = zip_path.stat().st_size

        # Record the download
        dl = DownloadResult(
            kind=kind, date=target_date, url=url, zip_path=str(zip_path.resolve()),
            sha256=sha, size_bytes=size
        )
        # Deduplicate prior entries if re-run
        manifest.downloads = [d for d in manifest.downloads if d.zip_path != dl.zip_path] + [dl]

        # 4) Extract only XMLs
        print(f"[4/4] Extracting XMLs from: {zip_path.name}")
        extract = extract_xmls_from_zip(zip_path, root, kind, target_date)
        # Deduplicate prior extracts for same zip/dataset
        manifest.extracts = [
            e for e in manifest.extracts
            if not (e.zip_filename == extract.zip_filename and e.dataset_name == extract.dataset_name)
        ] + [extract]

        # Optionally remove zip
        if not keep_zips:
            try:
                zip_path.unlink()
            except Exception as e:
                logging.warning(f"Could not delete zip {zip_path}: {e}")

        save_manifest(manifest_path, manifest)

        print(f"  ✔ Wrote manifest: {manifest_path}")
        print(f"  ✔ Extracted {len(extract.files)} XMLs "
              f"({extract.total_bytes/1_048_576:.2f} MiB) to {root / target_date / kind / 'xml' / extract.dataset_name}")


# ------------------------------
# CLI
# ------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download + extract ONLY XMLs from FAA AIXM NASR ZIPs.")
    p.add_argument("--root", default="./nasr_aixm_data", help="Root output directory.")
    p.add_argument("--date", help="Effective date YYYY-MM-DD (default: latest discovered).")
    p.add_argument("--kind", choices=["aixm51", "aixm50", "both"], default="aixm51",
                   help="Which AIXM package(s) to process (default: aixm51).")
    p.add_argument("--list", action="store_true", help="List available dates and exit.")
    p.add_argument("--no-keep-zips", action="store_true", help="Delete zips after extraction.")
    p.add_argument("--quiet", action="store_true", help="Less noisy progress.")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    # Basic logging setup
    logging.basicConfig(level=logging.INFO if not args.quiet else logging.WARNING, format="%(message)s")

    if args.list:
        idx_resp = _get(BASE_INDEX_URL)
        for d in discover_effective_dates(idx_resp.text):
            print(d)
        return

    kinds = ("aixm51",) if args.kind == "aixm51" else ("aixm50",) if args.kind == "aixm50" else ("aixm51", "aixm50")

    run_pipeline(
        root=Path(args.root),
        date=args.date,
        kinds=kinds,
        keep_zips=not args.no_keep_zips,
        progress=not args.quiet,
    )


if __name__ == "__main__":
    main()