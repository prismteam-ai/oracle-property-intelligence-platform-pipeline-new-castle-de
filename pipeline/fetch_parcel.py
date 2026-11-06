"""Fetch one New Castle County parcel by parcel id or ParcelKey.

The official page is
https://www3.newcastlede.gov/parcel/Details/Default.aspx?ParcelKey=<PRCLKEY>
Year built and roof fields come from the county structures layer for that
same parcel. Deed history on the HTML page is a later step.
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.parse
import urllib.request

SSL_CONTEXT = ssl.create_default_context(cafile="/etc/ssl/cert.pem")

PARCELS = (
    "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/0/query"
)
STRUCTURES = (
    "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/6/query"
)
OPEN_PERMITS = (
    "https://gis.nccde.org/agsserver/rest/services/CustomMaps/Permits/MapServer/0/query"
)
PARCEL_PAGE = (
    "https://www3.newcastlede.gov/parcel/Details/Default.aspx?ParcelKey={key}"
)


def query(url: str, where: str, fields: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "where": where,
            "outFields": fields,
            "returnGeometry": "false",
            "f": "json",
        }
    )
    with urllib.request.urlopen(f"{url}?{params}", timeout=40, context=SSL_CONTEXT) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return [row["attributes"] for row in payload.get("features", [])]


def fetch(parcel_id: str) -> dict:
    parcel_id = parcel_id.strip()
    parcels = query(
        PARCELS,
        f"PRCLID='{parcel_id}' OR PRCLKEY={parcel_id}",
        "PRCLID,PRCLKEY,ADDRESS,PROPCITY,PROPZIP,CNTCTLAST,OWNADDR,OWNCITY,OWNSTATE,OWNZIP,PROPCLASS,SUBDIV,last_edited_date",
    )
    if not parcels:
        raise SystemExit(f"no parcel for {parcel_id}")
    parcel = parcels[0]
    parcel_id = parcel["PRCLID"].strip()
    structures = query(
        STRUCTURES,
        f"PARCELID='{parcel_id}' OR PRCLID='{parcel_id}'",
        "PARCELID,PRCLID,YEAR_BUILT,REMODEL_YEAR,ROOF_TYPE,ROOF_MATERIAL,BLDG_DESIGN,CONDITION,last_edited_date",
    )
    permits = query(
        OPEN_PERMITS,
        f"PARCELID='{parcel_id}' OR PRCLID='{parcel_id}'",
        "PARCELID,PRCLID,APNO,APTYPE,ISSDTTM,COMMENTS,DESCRIPT",
    )
    return {
        "parcel_url": PARCEL_PAGE.format(key=parcel["PRCLKEY"]),
        "parcel": parcel,
        "structures": structures,
        "open_permits": permits,
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "0801240099"
    json.dump(fetch(target), sys.stdout, indent=2)
    sys.stdout.write("\n")
