"""Paged reads from the New Castle County ArcGIS map services.

Every read asks for all attributes (outFields=*) so no county field is dropped.
Pages are ordered by OBJECTID so offsets are stable across the walk.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request

SSL_CONTEXT = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
PAGE = 1000
PAUSE_SECONDS = 0.15  # be polite to a county server

BASE_LAYERS = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer"
ASSESSMENT = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Assessment/MapServer"
PERMITS = "https://gis.nccde.org/agsserver/rest/services/CustomMaps/Permits/MapServer"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120, context=SSL_CONTEXT) as response:
        return json.load(response)


def object_id_field(layer_url: str) -> str:
    payload = get_json(f"{layer_url}?f=json")
    names = [field["name"] for field in payload.get("fields") or []]
    for name in ("NEW_OID", "OBJECTID", "ESRI_OID"):
        if name in names:
            return name
    raise RuntimeError(f"no object id field on {layer_url}")


def iter_pages(layer_url: str, where: str = "1=1", order_field: str | None = None):
    """Yield lists of attribute dicts, one list per page of up to 1,000 rows."""
    order_field = order_field or object_id_field(layer_url)
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "false",
            "orderByFields": order_field,
            "resultOffset": str(offset),
            "resultRecordCount": str(PAGE),
            "f": "json",
        }
        payload = get_json(f"{layer_url}/query?{urllib.parse.urlencode(params)}")
        if "error" in payload:
            raise RuntimeError(f"{layer_url} where={where}: {payload['error']}")
        features = payload.get("features", [])
        if not features:
            break
        yield [feature["attributes"] for feature in features]
        offset += len(features)
        if len(features) < PAGE and not payload.get("exceededTransferLimit"):
            break
        time.sleep(PAUSE_SECONDS)
