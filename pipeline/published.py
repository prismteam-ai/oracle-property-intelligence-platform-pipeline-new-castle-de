"""Query the published JSON snapshot.

The hosted files are every parcel with coordinates and every permit row.
This module does not open
the internal DuckDB. Elephant MCP syncs only after an Atlas lexicon archive
exists, so this server is the public query surface until that archive is merged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb

from query_layer import INSTALL_SQL, LIMITATIONS, _clamp, _rows

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "data"
MILES_SQL = INSTALL_SQL.split("CREATE OR REPLACE VIEW")[0]

PUBLISHED_NOTE = (
    "Rows come from the published JSON snapshot: every parcel with coordinates, and every permit row."
)


def connect() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute(MILES_SQL)
    for name in ("leads", "permits", "summary"):
        path = str(DATA / f"{name}.json").replace("'", "''")
        connection.execute(
            f"CREATE VIEW {name} AS SELECT * FROM read_json_auto('{path}')"
        )
    return connection


def source_summary() -> dict:
    summary = json.loads((DATA / "summary.json").read_text())
    published = json.loads((DATA / "published.json").read_text()) if (DATA / "published.json").exists() else {}
    connection = connect()
    counts = _rows(
        connection.execute(
            """
            SELECT
              (SELECT count(*) FROM leads) AS published_leads,
              (SELECT count(*) FROM permits) AS published_open_roof_permits,
              (SELECT count(*) FROM leads WHERE last_roof_contractor_name IS NOT NULL) AS published_with_last_roof_contractor
            """
        )
    )[0]
    connection.close()
    return {
        "county": "New Castle County, DE",
        "source": "published-json",
        "files": ["summary.json", "leads.json", "permits.json"],
        "manifest_cid": published.get("manifest_cid"),
        "coverage": summary,
        "published_counts": counts,
        "note": PUBLISHED_NOTE,
        "limitations": LIMITATIONS,
    }


def radius_search(
    latitude: float,
    longitude: float,
    radius_miles: float = 5,
    min_roof_age_years: int | None = 15,
    open_roof_permits_only: bool = False,
    min_days_open: int | None = None,
    out_of_area_owner: bool = False,
    limit: int = 25,
) -> dict:
    radius_miles = float(radius_miles)
    if radius_miles <= 0 or radius_miles > 50:
        raise ValueError("radius_miles must be between 0 and 50")
    limit = _clamp(limit, 1, 100)
    connection = connect()
    rows = _rows(
        connection.execute(
            """
            SELECT
              prclid, address, city, zip, lon, lat,
              miles_between($lat, $lon, lat, lon) AS distance_miles,
              roof_age_years, roof_age_basis, year_built, roof_material,
              open_permit_count, open_roof_permit_count, oldest_open_roof_days,
              contractor_name, owner_out_of_area,
              last_roof_contractor_name, last_roof_contractor_issued_at
            FROM leads
            WHERE lat IS NOT NULL
              AND miles_between($lat, $lon, lat, lon) <= $miles
              AND ($min_age IS NULL OR roof_age_years >= $min_age)
              AND (NOT $open_roof OR open_roof_permit_count > 0)
              AND ($min_days IS NULL OR oldest_open_roof_days >= $min_days)
              AND (NOT $out_of_area OR owner_out_of_area)
            ORDER BY distance_miles
            LIMIT $limit
            """,
            {
                "lat": latitude,
                "lon": longitude,
                "miles": radius_miles,
                "min_age": min_roof_age_years,
                "open_roof": open_roof_permits_only,
                "min_days": min_days_open,
                "out_of_area": out_of_area_owner,
                "limit": limit,
            },
        )
    )
    connection.close()
    return {
        "center": {"latitude": latitude, "longitude": longitude},
        "radius_miles": radius_miles,
        "filters": {
            "min_roof_age_years": min_roof_age_years,
            "open_roof_permits_only": open_roof_permits_only,
            "min_days_open": min_days_open,
            "out_of_area_owner": out_of_area_owner,
        },
        "returned": len(rows),
        "limit": limit,
        "properties": rows,
        "source": "published-json",
        "note": PUBLISHED_NOTE,
        "limitations": LIMITATIONS,
    }


def open_roof_permits(
    latitude: float,
    longitude: float,
    radius_miles: float = 5,
    min_days_open: int | None = None,
    limit: int = 25,
) -> dict:
    radius_miles = float(radius_miles)
    if radius_miles <= 0 or radius_miles > 50:
        raise ValueError("radius_miles must be between 0 and 50")
    limit = _clamp(limit, 1, 100)
    connection = connect()
    permits = _rows(
        connection.execute(
            """
            SELECT
              p.prclid, l.address, l.city, l.zip, l.lon, l.lat,
              miles_between($lat, $lon, l.lat, l.lon) AS distance_miles,
              p.apno, p.aptype, p.issued_at, p.days_open, p.comments, p.contractor_name,
              l.last_roof_contractor_name
            FROM permits p
            JOIN leads l ON l.prclid = p.prclid
            WHERE l.lat IS NOT NULL
              AND p.permit_status = 'open'
              AND p.is_roof
              AND miles_between($lat, $lon, l.lat, l.lon) <= $miles
              AND ($min_days IS NULL OR p.days_open >= $min_days)
            ORDER BY p.days_open DESC NULLS LAST
            LIMIT $limit
            """,
            {
                "lat": latitude,
                "lon": longitude,
                "miles": radius_miles,
                "min_days": min_days_open,
                "limit": limit,
            },
        )
    )
    connection.close()
    return {
        "center": {"latitude": latitude, "longitude": longitude},
        "radius_miles": radius_miles,
        "min_days_open": min_days_open,
        "returned": len(permits),
        "permits": permits,
        "source": "published-json",
        "note": PUBLISHED_NOTE,
        "limitations": LIMITATIONS,
    }


def property_record(prclid: str) -> dict:
    parcel_id = prclid.strip()
    connection = connect()
    parcel = _rows(connection.execute("SELECT * FROM leads WHERE prclid = ?", [parcel_id]))
    permits = _rows(
        connection.execute(
            """
            SELECT apno, aptype, issued_at, days_open, comments, contractor_name
            FROM permits
            WHERE prclid = ?
            ORDER BY days_open DESC NULLS LAST
            """,
            [parcel_id],
        )
    )
    connection.close()
    return {
        "prclid": parcel_id,
        "property": parcel[0] if parcel else None,
        "permits": permits,
        "source": "published-json",
        "note": PUBLISHED_NOTE,
        "limitations": LIMITATIONS,
    }


def ownership_exchange(min_years: int = 10) -> dict:
    return {
        "answered": False,
        "min_years": min_years,
        "reason": LIMITATIONS[4],
        "properties": [],
    }


def query_select(sql: str, limit: int = 100) -> dict:
    text = sql.strip().rstrip(";").strip()
    if ";" in text or not re.match(r"(?is)^(select|with)\b", text):
        raise ValueError("read-only SELECT only")
    limit = _clamp(limit, 1, 200)
    connection = connect()
    rows = _rows(connection.execute(f"SELECT * FROM ({text}) AS q LIMIT {limit}"))
    connection.close()
    return {
        "returned": len(rows),
        "limit": limit,
        "rows": rows,
        "tables": ["leads", "permits", "summary"],
        "source": "published-json",
        "note": PUBLISHED_NOTE,
        "limitations": LIMITATIONS,
    }
