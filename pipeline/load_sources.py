"""Rebuild the parcel table from the sources already on disk.

Seed is the parcel-owner CSV. Coordinates are the parcel-point shapefile.
Year built and roof material are the structures layer in county_record.
Permit counts come from the permit layers in county_record. Those layers
were read from gis.nccde.org, which publishes no robots.txt.

Raw files stay in data/raw and are not committed. This command is the
rebuild:

    python pipeline/load_sources.py files
    python pipeline/load_sources.py assemble
    python pipeline/query_layer.py install
    python pipeline/query_layer.py export
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import duckdb

import query_layer

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OWNER_CSV = RAW / "PRIMARYADDRPRIMARYOWNER_POLY_static.csv"
POINT_SHP = RAW / "points" / "parcel_point.shp"

ASSEMBLE_SQL = """
CREATE OR REPLACE TABLE parcel AS
WITH structures AS (
  SELECT
    prclid,
    max(try_cast(json_extract_string(attrs, '$.YEAR_BUILT') AS INTEGER)) AS year_built,
    max(try_cast(json_extract_string(attrs, '$.REMODEL_YEAR') AS INTEGER)) AS remodel_year,
    arg_max(json_extract_string(attrs, '$.ROOF_TYPE'), object_id) AS roof_type,
    arg_max(json_extract_string(attrs, '$.ROOF_MATERIAL'), object_id) AS roof_material
  FROM county_record
  WHERE source = 'structures' AND prclid IS NOT NULL
  GROUP BY prclid
),
permits AS (
  SELECT
    prclid,
    count(*) FILTER (WHERE source LIKE 'permits_open%') AS open_permit_count,
    count(*) AS total_permit_count,
    min(to_timestamp(try_cast(json_extract_string(attrs, '$.ISSDTTM') AS BIGINT) / 1000))
      FILTER (WHERE source LIKE 'permits_open%') AS oldest_open_permit_issued_at,
    arg_max(
      coalesce(
        nullif(trim(json_extract_string(attrs, '$.CONTNAME')), ''),
        nullif(trim(json_extract_string(attrs, '$.CONTRACTORNAME')), '')
      ),
      to_timestamp(try_cast(json_extract_string(attrs, '$.ISSDTTM') AS BIGINT) / 1000)
    ) AS contractor_name
  FROM county_record
  WHERE source LIKE 'permits_%' AND prclid IS NOT NULL
  GROUP BY prclid
)
SELECT
  s.prclid,
  s.prclkey,
  s.parcel_url,
  s.address,
  s.city,
  s.state,
  s.zip,
  p.lon,
  p.lat,
  s.owner_name,
  s.owner_address,
  s.owner_city,
  s.owner_state,
  s.owner_zip,
  CASE WHEN s.owner_state IS NULL OR s.owner_state = 'DE' THEN false ELSE true END AS owner_out_of_area,
  s.property_class,
  s.subdivision,
  nullif(st.year_built, 0) AS year_built,
  nullif(st.remodel_year, 0) AS remodel_year,
  st.roof_type,
  st.roof_material,
  CAST(NULL AS INTEGER) AS roof_year,
  CAST(NULL AS INTEGER) AS roof_age_years,
  CAST(NULL AS VARCHAR) AS roof_age_basis,
  coalesce(pm.open_permit_count, 0) AS open_permit_count,
  CAST(0 AS INTEGER) AS open_roof_permit_count,
  coalesce(pm.total_permit_count, 0) AS total_permit_count,
  CAST(0 AS INTEGER) AS roof_permit_count,
  pm.oldest_open_permit_issued_at,
  CAST(NULL AS TIMESTAMP) AS oldest_open_roof_permit_issued_at,
  CAST(NULL AS TIMESTAMP) AS latest_roof_permit_issued_at,
  pm.contractor_name,
  s.source_edited_at,
  ? AS assembled_at,
  ? AS run_id
FROM parcel_seed AS s
LEFT JOIN parcel_point AS p USING (prclid)
LEFT JOIN structures AS st USING (prclid)
LEFT JOIN permits AS pm USING (prclid)
"""


def connect() -> duckdb.DuckDBPyConnection:
    return query_layer.connect()


def load_files(connection: duckdb.DuckDBPyConnection) -> dict:
    """Load the owner CSV and the parcel-point shapefile. Does not fetch GIS layers."""
    if not OWNER_CSV.exists() or not POINT_SHP.exists():
        raise FileNotFoundError(f"Need {OWNER_CSV} and {POINT_SHP}. Those files are local and are not in git.")
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE parcel_seed AS
        SELECT
          PRCLID AS prclid,
          try_cast(PRCLKEY AS BIGINT) AS prclkey,
          'https://www3.newcastlede.gov/parcel/Details/?parcel=' || PRCLID AS parcel_url,
          ADDRESS AS address,
          PROPCITY AS city,
          PROPSTATE AS state,
          PROPZIP AS zip,
          trim(CNTCTLAST) AS owner_name,
          OWNADDR AS owner_address,
          OWNCITY AS owner_city,
          OWNSTATE AS owner_state,
          OWNZIP AS owner_zip,
          PROPCLASS AS property_class,
          SUBDIV AS subdivision,
          try_cast(AREA AS DOUBLE) AS lot_acres,
          try_cast(last_edited_date AS TIMESTAMP) AS source_edited_at
        FROM read_csv('{OWNER_CSV.as_posix()}', header = true, auto_detect = true)
        WHERE PRCLID IS NOT NULL
        """
    )
    connection.execute("INSTALL spatial")
    connection.execute("LOAD spatial")
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE parcel_point AS
        SELECT
          PRCLID AS prclid,
          ST_X(ST_Transform(geom, 'EPSG:2235', 'EPSG:4326')) AS lon,
          ST_Y(ST_Transform(geom, 'EPSG:2235', 'EPSG:4326')) AS lat
        FROM st_read('{POINT_SHP.as_posix()}')
        WHERE PRCLID IS NOT NULL
        """
    )
    seed = connection.execute("SELECT count(*) FROM parcel_seed").fetchone()[0]
    points = connection.execute("SELECT count(*) FROM parcel_point").fetchone()[0]
    return {"parcel_seed": seed, "parcel_point": points}


def assemble(connection: duckdb.DuckDBPyConnection, run_id: str | None = None) -> dict:
    """Build parcel from parcel_seed, parcel_point, and county_record."""
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    assembled_at = datetime.now(timezone.utc)
    connection.execute(ASSEMBLE_SQL, [assembled_at, run_id])
    count = connection.execute("SELECT count(*) FROM parcel").fetchone()[0]
    return {"parcels": count, "run_id": run_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="Load New Castle sources into DuckDB")
    parser.add_argument("command", choices=("files", "assemble"))
    args = parser.parse_args()
    connection = connect()
    if args.command == "files":
        print(load_files(connection))
    else:
        print(assemble(connection))
    connection.close()


if __name__ == "__main__":
    main()
