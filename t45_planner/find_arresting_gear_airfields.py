#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


AG_PATTERN = re.compile(r"\bA-?GEAR\b", re.IGNORECASE)
GEAR_TYPE_RE = re.compile(
    r"\b(?:(HOOK)\s+)?(" \
    r"BAK-?12[ABab]?|BAK-?14|BAK-?9|BAK-?13|BAK-?15|" \
    r"MB-?60|EMAS|" \
    r"E-?5[A-Za-z]?|E-?28[A-Za-z]?|E-?32[A-Za-z]?|" \
    r"MAAS" \
    r")\b",
    re.IGNORECASE,
)
FT_FROM_THR_RE = re.compile(r"(\d{2,5})\s*FT\s*FM\s*THR", re.IGNORECASE)
PAREN_FEET_RE = re.compile(r"\((\d{2,5})\s*(?:FT|FT\.|')?\)", re.IGNORECASE)


def localname(tag: str) -> str:
    """Return the local tag name, stripping namespace if present."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def iter_airport_timeslices(xml_path: str) -> Iterator[ET.Element]:
    """Yield each AirportHeliportTimeSlice element from a large AIXM file using iterparse."""
    # Iterate on end events so elements are complete when inspected.
    context = ET.iterparse(xml_path, events=("end",))
    for event, elem in context:
        if localname(elem.tag) == "AirportHeliportTimeSlice":
            yield elem
            # Clear to keep memory usage low
            elem.clear()


def timeslice_has_gear(ts: ET.Element) -> bool:
    """Return True if any descendant note mentions arresting gear.

    Matches either the generic "A-GEAR" wording or specific gear type terms
    like BAK-12, BAK-14, E-28, MB60, MAAS, etc.
    """
    for note in ts.iter():
        if localname(note.tag) == "note":
            text = (note.text or "").strip()
            if AG_PATTERN.search(text) or GEAR_TYPE_RE.search(text):
                return True
    return False


def extract_designator_and_name(ts: ET.Element) -> Tuple[Optional[str], Optional[str]]:
    """Extract ICAO/FAA designator and airport name from a TimeSlice element.

    Prefers direct children named designator and name under the TimeSlice to avoid
    capturing names nested within servedCity, etc.
    """
    code = None
    name = None
    for child in list(ts):
        tag = localname(child.tag)
        if tag == "designator" and code is None:
            code = (child.text or "").strip() or None
        elif tag == "name" and name is None:
            name = (child.text or "").strip() or None
        # Stop early if both found
        if code and name:
            break
    return code, name


def sample_gear_note(ts: ET.Element) -> Optional[str]:
    """Return one representative note mentioning arresting gear, if any."""
    for note in ts.iter():
        if localname(note.tag) == "note":
            text = (note.text or "").strip()
            if AG_PATTERN.search(text) or GEAR_TYPE_RE.search(text):
                return text
    return None


def parse_gear_from_text(note: str) -> List[Dict[str, object]]:
    """Extract gear mentions and distances from a note string.

    Returns list of dicts: {type: str, distances_from_threshold_ft: [int], distances_misc_ft: [int]}
    """
    txt = (note or "").strip()
    if not txt:
        return []
    items: List[Dict[str, object]] = []

    # Collect distances with explicit "FM THR"
    d_thr = [int(x) for x in FT_FROM_THR_RE.findall(txt)]
    # Collect any parenthetical distances (context unknown)
    d_misc = [int(x) for x in PAREN_FEET_RE.findall(txt)]

    for m in GEAR_TYPE_RE.finditer(txt):
        hook, gear = m.groups()
        raw = gear.upper()
        # Normalize minimal: only fix BAK12 variants to BAK-12; keep BAK14 as-is
        norm = re.sub(r"^BAK\s*-?\s*12([A-Z]?)$", lambda m: f"BAK-12{m.group(1)}", raw)
        # MB-60 -> MB60
        norm = norm.replace("MB-60", "MB60")
        # E-series ensure hyphen form
        norm = re.sub(r"^E\s*-?\s*5([A-Z]?)$", lambda m: f"E-5{m.group(1)}", norm)
        norm = re.sub(r"^E\s*-?\s*28([A-Z]?)$", lambda m: f"E-28{m.group(1)}", norm)
        norm = re.sub(r"^E\s*-?\s*32([A-Z]?)$", lambda m: f"E-32{m.group(1)}", norm)
        gtype = ("HOOK " + norm) if hook else norm
        items.append({
            "type": gtype,
            "distances_from_threshold_ft": sorted(set(d_thr)),
            "distances_misc_ft": sorted(set([d for d in d_misc if d not in d_thr])),
            "raw": txt,
        })
    return items


def extract_gear_notes(ts: ET.Element) -> List[str]:
    """Return all note texts on the timeslice that mention arresting gear."""
    notes: List[str] = []
    for note in ts.iter():
        if localname(note.tag) == "note":
            text = (note.text or "").strip()
            if AG_PATTERN.search(text) or GEAR_TYPE_RE.search(text):
                notes.append(text)
    return notes


def index_gear_notes_across(xml_path: str) -> Dict[str, List[str]]:
    """Scan multiple feature TimeSlices and collect gear-related notes per associated airport.

    Looks for descendant tags named one of: associatedAirportHeliport, airportHeliport,
    airportLocation, clientAirport to resolve the airport id. Any descendant <note> text
    that matches AG_PATTERN or GEAR_TYPE_RE is recorded.
    """
    gear_notes: Dict[str, List[str]] = {}
    context = ET.iterparse(xml_path, events=("end",))
    for _event, elem in context:
        tag = localname(elem.tag)
        if not tag.endswith("TimeSlice"):
            elem.clear()
            continue
        airport_ref: Optional[str] = None
        # Try to locate any airport reference
        for child in elem.iter():
            ctag = localname(child.tag)
            if ctag in ("associatedAirportHeliport", "airportHeliport", "airportLocation", "clientAirport"):
                href = child.attrib.get("{http://www.w3.org/1999/xlink}href", "")
                m = re.search(r"@gml:id='([^']+)'", href)
                if m:
                    airport_ref = m.group(1)
                    break
        if not airport_ref:
            elem.clear()
            continue
        # Collect any gear-related notes under this timeslice
        found: List[str] = []
        for sub in elem.iter():
            if localname(sub.tag) == "note":
                text = (sub.text or "").strip()
                if AG_PATTERN.search(text) or GEAR_TYPE_RE.search(text):
                    found.append(text)
        if found:
            gear_notes.setdefault(airport_ref, []).extend(found)
        elem.clear()
    return gear_notes


def find_xml_files(root: str) -> Iterable[str]:
    """Yield XML file paths under root. Prioritize APT_AIXM.xml if present."""
    # First check for the common consolidated airport file
    priority = os.path.join(root, "APT_AIXM.xml")
    if os.path.isfile(priority):
        yield priority
        return
    # Otherwise, walk all .xml files under root
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if fname.lower().endswith(".xml"):
                yield os.path.join(dirpath, fname)


def collect_ag_airfields(root: str) -> List[Tuple[str, str, str, Optional[str]]]:
    """Collect (code, name, source_file, sample_note) for airfields with A-GEAR notes."""
    results: List[Tuple[str, str, str, Optional[str]]] = []
    for xml_path in find_xml_files(root):
        try:
            for ts in iter_airport_timeslices(xml_path):
                if not timeslice_has_gear(ts):
                    continue
                code, name = extract_designator_and_name(ts)
                if not code and not name:
                    continue
                note = sample_gear_note(ts)
                results.append((code or "", name or "", xml_path, note))
        except ET.ParseError as e:
            print(f"Warning: failed to parse {xml_path}: {e}", file=sys.stderr)
    # Deduplicate by (code, name) keeping first occurrence
    seen = set()
    deduped: List[Tuple[str, str, str, Optional[str]]] = []
    for code, name, xml_path, note in results:
        key = (code, name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((code, name, xml_path, note))
    return deduped


def index_airports(xml_path: str) -> Tuple[Dict[str, Dict[str, Optional[str]]], Dict[str, List[str]]]:
    """Parse AirportHeliport features to map id -> core fields and collect gear notes per id.

    Extracts:
      - code, name, icao
      - lat, lon (from ARP ElevatedPoint gml:pos "lon lat")
      - city, state_code, state (when available)

    Attempts to extract ARP coordinates (lon lat) from gml:pos under aixm:ARP ElevatedPoint.
    """
    airports: Dict[str, Dict[str, Optional[str]]] = {}
    gear_notes: Dict[str, List[str]] = {}

    context = ET.iterparse(xml_path, events=("start", "end"))
    cur_airport_id: Optional[str] = None
    for event, elem in context:
        tag = localname(elem.tag)
        if event == "start" and tag == "AirportHeliport":
            cur_airport_id = elem.attrib.get("{http://www.opengis.net/gml/3.2}id")
        elif event == "end" and tag == "AirportHeliportTimeSlice":
            code, name = extract_designator_and_name(elem)
            # Attempt to extract ICAO if present as sibling under timeslice
            icao = None
            lat = None
            lon = None
            city: Optional[str] = None
            state_code: Optional[str] = None
            state_name: Optional[str] = None
            for child in list(elem):
                if localname(child.tag) == "locationIndicatorICAO":
                    icao = (child.text or "").strip() or None
                elif localname(child.tag) == "ARP":
                    # Expect ElevatedPoint/gml:pos with "lon lat"
                    for sub in child.iter():
                        if localname(sub.tag) == "pos":
                            txt = (sub.text or "").strip()
                            try:
                                parts = [float(x) for x in txt.split() if x]
                                if len(parts) >= 2:
                                    lon, lat = parts[0], parts[1]
                            except Exception:
                                pass
                elif localname(child.tag) == "servedCity" and not city:
                    # servedCity/City/name
                    for sub in child.iter():
                        if localname(sub.tag) in ("name", "cityName"):
                            ctxt = (sub.text or "").strip()
                            if ctxt:
                                city = ctxt
                                break
                elif localname(child.tag) == "extension":
                    # FAA-specific extension often contains state info
                    for sub in child.iter():
                        stag = localname(sub.tag)
                        if stag == "countyStatePostOfficeCode" and not state_code:
                            stxt = (sub.text or "").strip()
                            if stxt:
                                state_code = stxt
                        elif stag == "stateName" and not state_name:
                            sntxt = (sub.text or "").strip()
                            if sntxt:
                                state_name = sntxt
                elif localname(child.tag) in ("AirportHeliportResponsibilityOrganisation", "responsibleOrganisation", "contact"):  # org/address holder
                    # Look for address city / administrativeArea and FAA state codes
                    for sub in child.iter():
                        stag = localname(sub.tag)
                        if stag == "address":
                            # descend into address children for city and administrativeArea
                            for addr_part in sub.iter():
                                atag = localname(addr_part.tag)
                                if atag == "city" and not city:
                                    ctxt = (addr_part.text or "").strip()
                                    if ctxt:
                                        city = ctxt
                                elif atag in ("administrativeArea", "stateProvince") and not state_code:
                                    stxt = (addr_part.text or "").strip()
                                    if stxt:
                                        state_code = stxt
                        elif stag == "countyStatePostOfficeCode" and not state_code:
                            # FAA 2-letter state/territory code
                            stxt = (sub.text or "").strip()
                            if stxt:
                                state_code = stxt
                        elif stag == "stateName" and not state_name:
                            sntxt = (sub.text or "").strip()
                            if sntxt:
                                state_name = sntxt
            if cur_airport_id:
                # Normalize simple strings to uppercase where appropriate for display consistency
                c_city = (city or None)
                c_state_code = (state_code or None)
                c_state = (state_name or None)
                airports[cur_airport_id] = {
                    "code": code,
                    "name": name,
                    "icao": icao,
                    "lat": lat,
                    "lon": lon,
                    "city": c_city,
                    "state_code": c_state_code,
                    "state": c_state,
                }
                notes = extract_gear_notes(elem)
                if notes:
                    gear_notes[cur_airport_id] = notes
            elem.clear()
        elif event == "end" and tag == "AirportHeliport":
            cur_airport_id = None
            elem.clear()
    return airports, gear_notes

def index_runways(xml_path: str) -> Dict[str, List[Dict[str, object]]]:
    """Parse Runway and RunwayDirection features and return airport_id -> list of runway ends with lengths.

    - Uses pair RunwayTimeSlice (e.g. 18/36) for base length/width.
    - Uses end RunwayTimeSlice to get end designators (e.g. 18, 36) and airport association.
    - Uses RunwayDirection displacedThresholdLength to reduce landing length per end when available.
    """
    # Maps
    pair_dims: Dict[Tuple[str, str], Tuple[Optional[int], Optional[int]]] = {}  # (airport_id, group_suffix) -> (len,width)
    end_info: Dict[str, Tuple[str, str, str]] = {}  # runway_end_id -> (airport_id, end_designator, group_suffix)
    end_disp: Dict[Tuple[str, str], int] = {}       # (airport_id, end_designator) -> displaced ft

    context = ET.iterparse(xml_path, events=("start", "end"))
    cur_runway_id: Optional[str] = None
    cur_rwy_dir_id: Optional[str] = None
    for event, elem in context:
        tag = localname(elem.tag)
        if event == "start" and tag == "Runway":
            cur_runway_id = elem.attrib.get("{http://www.opengis.net/gml/3.2}id")
        elif event == "end" and tag == "RunwayTimeSlice":
            # Extract details from this timeslice
            designator: Optional[str] = None
            airport_ref: Optional[str] = None
            length_ft: Optional[int] = None
            width_ft: Optional[int] = None
            for child in list(elem):
                ctag = localname(child.tag)
                if ctag == "designator":
                    designator = (child.text or "").strip()
                elif ctag == "associatedAirportHeliport":
                    href = child.attrib.get("{http://www.w3.org/1999/xlink}href", "")
                    m = re.search(r"@gml:id='([^']+)'", href)
                    if m:
                        airport_ref = m.group(1)
                elif ctag == "lengthStrip":
                    try:
                        length_ft = int(float((child.text or "").strip()))
                    except Exception:
                        length_ft = None
                elif ctag == "widthStrip":
                    try:
                        width_ft = int(float((child.text or "").strip()))
                    except Exception:
                        width_ft = None
            if cur_runway_id and airport_ref:
                # Determine if pair or end based on id pattern
                if "_BASE_END_" in cur_runway_id:
                    # Base end runway
                    m = re.match(r"RWY_BASE_END_(.+)", cur_runway_id)
                    group_suffix = m.group(1) if m else cur_runway_id
                    end_info[cur_runway_id] = (airport_ref, designator or "", group_suffix)
                elif "_RECIPROCAL_END_" in cur_runway_id:
                    m = re.match(r"RWY_RECIPROCAL_END_(.+)", cur_runway_id)
                    group_suffix = m.group(1) if m else cur_runway_id
                    end_info[cur_runway_id] = (airport_ref, designator or "", group_suffix)
                else:
                    # Pair runway with dimensions
                    m = re.match(r"RWY_(.+)", cur_runway_id)
                    group_suffix = m.group(1) if m else cur_runway_id
                    pair_dims[(airport_ref, group_suffix)] = (length_ft, width_ft)
            elem.clear()
        elif event == "end" and tag == "Runway":
            cur_runway_id = None
            elem.clear()
        elif event == "start" and tag == "RunwayDirection":
            cur_rwy_dir_id = elem.attrib.get("{http://www.opengis.net/gml/3.2}id")
        elif event == "end" and tag == "RunwayDirectionTimeSlice":
            # Extract displaced threshold length if present
            disp_ft: Optional[int] = None
            for child in elem.iter():
                if localname(child.tag) == "displacedThresholdLength":
                    txt = (child.text or "").strip()
                    if txt:
                        try:
                            disp_ft = int(float(txt))
                        except Exception:
                            pass
            if cur_rwy_dir_id and disp_ft is not None:
                # Map direction id to runway end id by suffix
                m = re.match(r"RWY_DIRECTION_(BASE_END|RECIPROCAL_END)_(.+)", cur_rwy_dir_id)
                if m:
                    kind, suffix = m.groups()
                    end_prefix = "RWY_BASE_END_" if kind == "BASE_END" else "RWY_RECIPROCAL_END_"
                    end_id = end_prefix + suffix
                    if end_id in end_info:
                        airport_ref, designator, _gs = end_info[end_id]
                        end_disp[(airport_ref, designator)] = disp_ft
            elem.clear()
        elif event == "end" and tag == "RunwayDirection":
            cur_rwy_dir_id = None
            elem.clear()

    # Build final list per airport using pair dimensions and end designators
    by_airport: Dict[str, List[Dict[str, object]]] = {}
    # Map group_suffix per airport to pair dims for quick lookup
    for end_id, (airport_ref, end_designator, group_suffix) in end_info.items():
        length_ft, width_ft = pair_dims.get((airport_ref, group_suffix), (None, None))
        # Adjust with displaced threshold per end when available
        disp = end_disp.get((airport_ref, end_designator), 0)
        use_len = None
        if length_ft is not None:
            use_len = max(0, int(length_ft) - int(disp or 0))
        by_airport.setdefault(airport_ref, []).append({
            "designator": end_designator,
            "length_ft": use_len,
            "width_ft": width_ft,
        })

    # If an airport has no end entries (fallback), include pair entries
    for (airport_ref, group_suffix), (length_ft, width_ft) in pair_dims.items():
        if airport_ref not in by_airport:
            # Need a pair designator? Not tracked here; safe fallback uses suffix as id
            by_airport[airport_ref] = [{
                "designator": group_suffix,
                "length_ft": length_ft,
                "width_ft": width_ft,
            }]

    return by_airport


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="List or export airfields with arresting gear from AIXM XML data.")
    p.add_argument("--root", default="data", help="Root folder containing AIXM XML (default: data)")
    p.add_argument("--format", choices=["text", "csv", "codes", "json"], default="text", help="Output format (default: text)")
    p.add_argument("--out", help="When --format json, path to write JSON (defaults to stdout)")
    args = p.parse_args(argv)

    airfields = collect_ag_airfields(args.root)
    if args.format == "csv":
        print("code,name,source,note")
        for code, name, src, note in airfields:
            # Basic CSV escaping for commas/quotes
            def esc(s: Optional[str]) -> str:
                s2 = (s or "")
                if any(c in s2 for c in [",", "\"", "\n"]):
                    return '"' + s2.replace('"', '""') + '"'
                return s2
            print(f"{esc(code)},{esc(name)},{esc(os.path.relpath(src))},{esc(note)}")
    elif args.format == "codes":
        for code, _name, _src, _note in airfields:
            if code:
                print(code)
    elif args.format == "json":
        # For JSON, build richer dataset from the primary APT_AIXM.xml if present
        xml_path = next(iter(find_xml_files(args.root)), None)
        if not xml_path:
            print("No XML files found under root.", file=sys.stderr)
            return 2
        airports, gear_notes = index_airports(xml_path)
        # Augment gear notes by scanning across related feature timeslices
        gear_notes2 = index_gear_notes_across(xml_path)
        runways = index_runways(xml_path)

        dataset: List[Dict[str, object]] = []
        for aid, info in airports.items():
            if aid not in gear_notes and aid not in gear_notes2:
                continue  # only include airfields with gear mentions
            code = info.get("code") or info.get("icao") or ""
            name = info.get("name") or ""
            gear_items: List[Dict[str, object]] = []
            for n in gear_notes.get(aid, []) + gear_notes2.get(aid, []):
                gear_items.extend(parse_gear_from_text(n))
            # Dedup gear items by (type, distances)
            norm = {}
            for gi in gear_items:
                key = (gi.get("type"), tuple(gi.get("distances_from_threshold_ft", [])), tuple(gi.get("distances_misc_ft", [])))
                if key not in norm:
                    norm[key] = gi
            dataset.append({
                "airport_id": aid,
                "code": code,
                "icao": info.get("icao"),
                "name": name,
                "lat": info.get("lat"),
                "lon": info.get("lon"),
                "city": info.get("city"),
                "state_code": info.get("state_code"),
                "state": info.get("state"),
                "runways": runways.get(aid, []),
                "gear": list(norm.values()),
                "source": os.path.relpath(xml_path),
            })

        out_obj = {
            "count": len(dataset),
            "airfields": dataset,
        }
        if args.out:
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(out_obj, f, indent=2)
        else:
            json.dump(out_obj, sys.stdout, indent=2)
    else:
        for code, name, src, note in airfields:
            rel = os.path.relpath(src)
            header = f"{code or '(no-code)'} — {name or '(no-name)'}"
            print(header)
            print(f"  source: {rel}")
            if note:
                print(f"  note:   {note}")
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
