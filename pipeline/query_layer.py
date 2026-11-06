"""DuckDB query surface for the roofing questions.

The views are the model an agent or the CRM reads. Sale history and BBB
ratings are not in the database, so those answers say so.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "duckdb" / "newcastle.duckdb"

LIMITATIONS = [
    "Roof age is the structure year built when the county filled it. Otherwise it is the year of the latest permit whose type or comment mentions roof. Parcels with neither have no roof age.",
    "Open duration is days since the issue timestamp on an open permit layer. The GIS layers do not publish a close date.",
    "Contractor name is the name printed on the permit (CONTNAME or CONTRACTORNAME). It is not matched to a Delaware license or corporate registry.",
    "BBB ratings are not loaded.",
    "Ownership unchanged for 10 years cannot be answered. Sale and deed history are on www3.newcastlede.gov/parcel/Details/. That host's robots.txt is Disallow: / except listed search pages, so the Details path is disallowed. The page also serves a bot challenge, which this pipeline does not bypass. The GIS layers have no sale date.",
    "gis.nccde.org publishes no robots.txt. Parcel, structure, address, unit, permit, appeal, and rollback layers were read from that host.",
]

INSTALL_SQL = """
CREATE OR REPLACE MACRO miles_between(lat1, lon1, lat2, lon2) AS (
  CASE
    WHEN lat1 IS NULL OR lon1 IS NULL OR lat2 IS NULL OR lon2 IS NULL THEN NULL
    ELSE 2 * 3958.7613 * asin(least(1.0, sqrt(
      pow(sin(radians(lat2 - lat1) / 2), 2)
      + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)
    )))
  END
);

CREATE OR REPLACE VIEW lead_property AS
SELECT
  prclid,
  prclkey,
  parcel_url,
  address,
  city,
  state,
  zip,
  lon,
  lat,
  owner_name,
  owner_address,
  owner_city,
  owner_state,
  owner_zip,
  owner_out_of_area,
  property_class,
  subdivision,
  year_built,
  remodel_year,
  roof_type,
  roof_material,
  roof_year,
  roof_age_years,
  roof_age_basis,
  open_permit_count,
  open_roof_permit_count,
  total_permit_count,
  roof_permit_count,
  oldest_open_permit_issued_at,
  oldest_open_roof_permit_issued_at,
  latest_roof_permit_issued_at,
  date_diff('day', oldest_open_roof_permit_issued_at, current_timestamp) AS oldest_open_roof_days,
  contractor_name,
  'name printed on the permit; not reconciled to a state license' AS contractor_basis,
  CAST(NULL AS VARCHAR) AS bbb_rating,
  'not loaded' AS bbb_basis,
  CAST(NULL AS BOOLEAN) AS ownership_unchanged_10_years,
  'sale history is not in the GIS layers; parcel Details is disallowed by robots.txt' AS ownership_basis,
  source_edited_at,
  assembled_at,
  run_id
FROM parcel;

CREATE OR REPLACE VIEW permit_detail AS
SELECT
  prclid,
  source,
  object_id,
  apno,
  aptype,
  issued_at,
  comments,
  contractor_name,
  permit_status,
  is_roof,
  CASE
    WHEN permit_status = 'open' THEN date_diff('day', issued_at, current_timestamp)
  END AS days_open,
  fetched_at,
  'https://gis.nccde.org/agsserver/rest/services/CustomMaps/Permits/MapServer' AS provenance
FROM (
  SELECT
    prclid,
    source,
    object_id,
    json_extract_string(attrs, '$.APNO') AS apno,
    json_extract_string(attrs, '$.APTYPE') AS aptype,
    to_timestamp(try_cast(json_extract_string(attrs, '$.ISSDTTM') AS BIGINT) / 1000) AS issued_at,
    json_extract_string(attrs, '$.COMMENTS') AS comments,
    coalesce(
      nullif(trim(json_extract_string(attrs, '$.CONTNAME')), ''),
      nullif(trim(json_extract_string(attrs, '$.CONTRACTORNAME')), '')
    ) AS contractor_name,
    CASE
      WHEN source LIKE 'permits_open%' THEN 'open'
      WHEN source LIKE 'permits_expired%' THEN 'expired'
      WHEN source LIKE 'permits_hold%' THEN 'hold'
      WHEN source = 'permits_released' THEN 'released'
      WHEN source = 'permits_new_construction' THEN 'new_construction'
      WHEN source = 'permits_adu' THEN 'adu'
      ELSE source
    END AS permit_status,
    (
      upper(coalesce(json_extract_string(attrs, '$.COMMENTS'), '')) LIKE '%ROOF%'
      OR upper(coalesce(json_extract_string(attrs, '$.APTYPE'), '')) LIKE '%ROOF%'
    ) AS is_roof,
    fetched_at,
    row_number() OVER (
      PARTITION BY prclid, coalesce(json_extract_string(attrs, '$.APNO'), source || ':' || object_id::VARCHAR)
      ORDER BY CASE WHEN source LIKE 'permits_open%' THEN 0 ELSE 1 END, source, object_id
    ) AS dup_rank
  FROM county_record
  WHERE source LIKE 'permits_%' AND prclid IS NOT NULL
) AS p
WHERE p.dup_rank = 1;
"""


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def install() -> None:
    connection = connect()
    connection.execute(INSTALL_SQL)
    connection.close()


def _rows(cursor: duckdb.DuckDBPyConnection) -> list[dict]:
    columns = [item[0] for item in cursor.description]
    rows = []
    for record in cursor.fetchall():
        row = {}
        for name, value in zip(columns, record):
            if hasattr(value, "isoformat"):
                value = value.isoformat(sep=" ", timespec="seconds")
            row[name] = value
        rows.append(row)
    return rows


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def source_summary() -> dict:
    connection = connect(read_only=True)
    coverage = _rows(
        connection.execute(
            """
            SELECT
              count(*) AS parcels,
              count(*) FILTER (WHERE lon IS NOT NULL) AS with_coordinates,
              count(*) FILTER (WHERE year_built IS NOT NULL) AS with_year_built,
              count(*) FILTER (WHERE roof_age_years >= 15) AS roofs_15_or_older,
              count(*) FILTER (WHERE open_permit_count > 0) AS any_open_permit,
              count(*) FILTER (WHERE open_roof_permit_count > 0) AS open_roof_permit,
              count(*) FILTER (WHERE owner_out_of_area) AS out_of_area_owner,
              count(*) FILTER (WHERE contractor_name IS NOT NULL) AS with_contractor_name
            FROM lead_property
            """
        )
    )
    sources = _rows(
        connection.execute(
            "SELECT source, row_count, finished_at FROM county_record_marker ORDER BY source"
        )
    )
    runs = _rows(
        connection.execute(
            """
            SELECT run_id, started_at, finished_at, assembled, skipped, note
            FROM pipeline_run
            ORDER BY started_at
            """
        )
    )
    connection.close()
    return {
        "county": "New Castle County, DE",
        "database": "duckdb",
        "query_views": ["lead_property", "permit_detail"],
        "coverage": coverage[0] if coverage else {},
        "sources": sources,
        "runs": runs,
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
    connection = connect(read_only=True)
    rows = _rows(
        connection.execute(
            """
            SELECT
              prclid, address, city, state, zip, lon, lat,
              miles_between($lat, $lon, lat, lon) AS distance_miles,
              owner_name, owner_out_of_area,
              year_built, roof_material, roof_age_years, roof_age_basis,
              open_permit_count, open_roof_permit_count,
              oldest_open_roof_permit_issued_at, oldest_open_roof_days,
              contractor_name, contractor_basis, bbb_rating, bbb_basis,
              ownership_unchanged_10_years, ownership_basis,
              run_id
            FROM lead_property
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
    connection = connect(read_only=True)
    near = _rows(
        connection.execute(
            """
            SELECT prclid, miles_between($lat, $lon, lat, lon) AS distance_miles
            FROM lead_property
            WHERE lat IS NOT NULL
              AND open_roof_permit_count > 0
              AND miles_between($lat, $lon, lat, lon) <= $miles
            """,
            {"lat": latitude, "lon": longitude, "miles": radius_miles},
        )
    )
    if not near:
        connection.close()
        return {
            "center": {"latitude": latitude, "longitude": longitude},
            "radius_miles": radius_miles,
            "returned": 0,
            "permits": [],
            "limitations": LIMITATIONS,
        }
    distances = {row["prclid"]: row["distance_miles"] for row in near}
    placeholders = ", ".join(["?"] * len(distances))
    permits = _rows(
        connection.execute(
            f"""
            SELECT * EXCLUDE (rn) FROM (
              SELECT
                p.prclid, l.address, l.city, l.zip, l.lon, l.lat,
                p.apno, p.aptype, p.permit_status, p.issued_at, p.days_open,
                p.comments, p.contractor_name, p.source, p.provenance,
                l.bbb_rating, l.bbb_basis,
                row_number() OVER (
                  PARTITION BY p.prclid, coalesce(p.apno, p.source || ':' || cast(p.object_id AS VARCHAR))
                  ORDER BY (p.contractor_name IS NOT NULL) DESC, p.source DESC
                ) AS rn
              FROM permit_detail p
              JOIN lead_property l ON l.prclid = p.prclid
              WHERE p.prclid IN ({placeholders})
                AND p.is_roof
                AND p.permit_status = 'open'
                AND (? IS NULL OR p.days_open >= ?)
            )
            WHERE rn = 1
            ORDER BY days_open DESC NULLS LAST
            LIMIT ?
            """,
            [*distances.keys(), min_days_open, min_days_open, limit],
        )
    )
    connection.close()
    for permit in permits:
        permit["distance_miles"] = distances.get(permit["prclid"])
    return {
        "center": {"latitude": latitude, "longitude": longitude},
        "radius_miles": radius_miles,
        "min_days_open": min_days_open,
        "returned": len(permits),
        "permits": permits,
        "limitations": LIMITATIONS,
    }


def property_record(prclid: str) -> dict:
    parcel_id = prclid.strip()
    connection = connect(read_only=True)
    parcel = _rows(
        connection.execute("SELECT * FROM lead_property WHERE prclid = ?", [parcel_id])
    )
    permits = _rows(
        connection.execute(
            """
            SELECT apno, aptype, permit_status, issued_at, days_open, is_roof,
                   comments, contractor_name, source, provenance
            FROM permit_detail
            WHERE prclid = ?
            ORDER BY issued_at DESC NULLS LAST
            LIMIT 50
            """,
            [parcel_id],
        )
    )
    connection.close()
    return {
        "prclid": parcel_id,
        "property": parcel[0] if parcel else None,
        "permits": permits,
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
    connection = connect(read_only=True)
    rows = _rows(connection.execute(f"SELECT * FROM ({text}) AS q LIMIT {limit}"))
    connection.close()
    return {"returned": len(rows), "limit": limit, "rows": rows, "limitations": LIMITATIONS}


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the New Castle County DuckDB")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install")
    sub.add_parser("summary")
    radius = sub.add_parser("radius")
    radius.add_argument("latitude", type=float)
    radius.add_argument("longitude", type=float)
    radius.add_argument("radius_miles", type=float)
    radius.add_argument("--min-age", type=int, default=15)
    radius.add_argument("--open-roof", action="store_true")
    radius.add_argument("--limit", type=int, default=10)
    roofs = sub.add_parser("open-roof")
    roofs.add_argument("latitude", type=float)
    roofs.add_argument("longitude", type=float)
    roofs.add_argument("radius_miles", type=float)
    roofs.add_argument("--min-days", type=int)
    roofs.add_argument("--limit", type=int, default=10)
    record = sub.add_parser("property")
    record.add_argument("prclid")
    sub.add_parser("ownership")
    args = parser.parse_args()

    if args.command == "install":
        install()
        print("installed lead_property, permit_detail, miles_between")
        return
    install()
    if args.command == "summary":
        payload = source_summary()
    elif args.command == "radius":
        payload = radius_search(
            args.latitude,
            args.longitude,
            args.radius_miles,
            min_roof_age_years=args.min_age,
            open_roof_permits_only=args.open_roof,
            limit=args.limit,
        )
    elif args.command == "open-roof":
        payload = open_roof_permits(
            args.latitude,
            args.longitude,
            args.radius_miles,
            min_days_open=args.min_days,
            limit=args.limit,
        )
    elif args.command == "property":
        payload = property_record(args.prclid)
    else:
        payload = ownership_exchange()
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
