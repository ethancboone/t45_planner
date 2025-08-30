import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests
from lxml import etree

FAA_INDEX = "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/"
NFDC_BASE = "https://nfdc.faa.gov/webContent/28DaySub/{date}/aixm5.1.zip"

HDRS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/127.0 Safari/537.36"
}

def latest_cycle_date(index_url=FAA_INDEX):
    """
    Parse the NASR Subscription index page and return the most recent YYYY-MM-DD
    that appears in 'Preview' or 'Current' sections.
    """
    r = requests.get(index_url, headers=HDRS, timeout=30)
    r.raise_for_status()
    # Look for "Subscription effective <Month DD, YYYY>" OR yyyy-mm-dd in hrefs.
    # The cycle pages use /NASR_Subscription/YYYY-MM-DD/
    dates = re.findall(r"/NASR_Subscription/(\d{4}-\d{2}-\d{2})/?", r.text)
    if dates:
        # The first occurrence on this page is the most recent
        return dates[0]
    # Fallback: search for ISO dates in the page body
    iso_dates = re.findall(r"(\d{4}-\d{2}-\d{2})", r.text)
    if iso_dates:
        return sorted(set(iso_dates), reverse=True)[0]
    raise RuntimeError("Couldn't find a cycle date on the NASR Subscription page")

def download_aixm_bundle(cycle_date, outdir="nasr_aixm"):
    """
    Download the combined AIXM 5.1 bundle (aixm5.1.zip) for the given cycle_date.
    Returns a ZipFile object in memory.
    """
    url = NFDC_BASE.format(date=cycle_date)
    resp = requests.get(url, headers=HDRS, timeout=120)
    resp.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(resp.content)), url

def extract_nested_aixm(zf, want=("APT_AIXM", "RWY_AIXM")):
    """
    From the top-level aixm5.1.zip, find nested *AIXM.zip archives, then
    extract their XML/GML members into memory and return file-like objects.
    """
    blobs = {k: [] for k in want}
    for name in zf.namelist():
        lower = name.lower()
        if lower.endswith(".zip") and any(tag.lower() in lower for tag in (w.lower() for w in want)):
            with zf.open(name) as nested_file:
                nested_bytes = nested_file.read()
            with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
                for inner in nested.namelist():
                    if inner.lower().endswith((".xml", ".gml")):
                        blobs_key = next((w for w in want if w.lower() in lower), None)
                        if blobs_key:
                            blobs[blobs_key].append((inner, nested.read(inner)))
    return blobs

NS = {
    "aixm": "http://www.aixm.aero/schema/5.1",
    "gml": "http://www.opengis.net/gml/3.2",
    "xlink": "http://www.w3.org/1999/xlink",
}

def parse_airports(xml_bytes_list):
    rows = []
    for fname, data in xml_bytes_list:
        tree = etree.fromstring(data)
        for ah in tree.xpath("//aixm:AirportHeliport", namespaces=NS):
            ident = ah.xpath("string(aixm:timeSlice/aixm:AirportHeliportTimeSlice/aixm:designator)", namespaces=NS)
            name  = ah.xpath("string(aixm:timeSlice/aixm:AirportHeliportTimeSlice/aixm:name)", namespaces=NS)
            pos   = ah.xpath("aixm:timeSlice/aixm:AirportHeliportTimeSlice/aixm:ARP/aixm:ElevatedPoint/gml:pos/text()", namespaces=NS)
            lat, lon = (pos[0].split() if pos else (None, None))
            elev_uom = ah.xpath("string(aixm:timeSlice/aixm:AirportHeliportTimeSlice/aixm:ARP/aixm:ElevatedPoint/aixm:elevation/@uom)", namespaces=NS)
            elev_val = ah.xpath("string(aixm:timeSlice/aixm:AirportHeliportTimeSlice/aixm:ARP/aixm:ElevatedPoint/aixm:elevation/text())", namespaces=NS)
            rows.append({"ident": ident, "name": name, "lat": lat, "lon": lon,
                         "elev": elev_val or None, "elev_uom": elev_uom or None, "source": fname})
    return pd.DataFrame(rows)

def parse_runways(xml_bytes_list):
    rows = []
    for fname, data in xml_bytes_list:
        tree = etree.fromstring(data)
        for rw in tree.xpath("//aixm:Runway", namespaces=NS):
            rw_id      = rw.xpath("string(@gml:id)", namespaces=NS)
            designator = rw.xpath("string(aixm:timeSlice/aixm:RunwayTimeSlice/aixm:designator)", namespaces=NS)
            length     = rw.xpath("string(.//aixm:surfaceCharacteristics/aixm:length/aixm:value)", namespaces=NS)
            width      = rw.xpath("string(.//aixm:surfaceCharacteristics/aixm:width/aixm:value)", namespaces=NS)
            surf_href  = rw.xpath("string(.//aixm:surfaceCharacteristics/aixm:surfaceType/@xlink:href)", namespaces=NS)
            rows.append({"runway_id": rw_id, "designator": designator,
                         "length": length or None, "width": width or None,
                         "surface_href": surf_href or None, "source": fname})
    return pd.DataFrame(rows)

def main(cycle_date=None, outdir="nasr_aixm"):
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    if not cycle_date:
        cycle_date = latest_cycle_date()
        print("Latest cycle:", cycle_date)

    zf, url = download_aixm_bundle(cycle_date)
    print("Downloaded:", url)

    blobs = extract_nested_aixm(zf, want=("APT_AIXM", "RWY_AIXM"))
    if not any(blobs.values()):
        raise RuntimeError("AIXM inner zips not found in bundle. Try a different cycle_date or check contents.")

    df_airports = parse_airports(blobs.get("APT_AIXM", []))
    df_runways  = parse_runways(blobs.get("RWY_AIXM", []))

    df_airports.to_csv(out/"airports_from_aixm.csv", index=False)
    df_runways.to_csv(out/"runways_from_aixm.csv", index=False)

    print("Airports parsed:", len(df_airports), "| Runways parsed:", len(df_runways))
    return df_airports, df_runways

if __name__ == "__main__":
    main()