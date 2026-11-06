"""Rebuild the parcel table from the full county GIS record.

Inputs are the seed (parcel_seed, from the owner CSV), coordinates (parcel_point),
and county_record (every published attribute, stored as JSON per source row).
Output is one row per seed parcel with roof and permit rollups derived from all
permit layers. Full attributes stay in county_record and can be queried by JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "duckdb" / "newcastle.duckdb"

PARCEL_DDL = """
CREATE OR REPLACE TABLE parcel (
  prclid VARCHAR PRIMARY KEY,
  prclkey BIGINT,
  parcel_url VARCHAR,
  address VARCHAR,
  city VARCHAR,
  state VARCHAR,
  zip VARCHAR,
  lon DOUBLE,
  lat DOUBLE,
  owner_name VARCHAR,
  owner_address VARCHAR,
  owner_city VARCHAR,
  owner_state VARCHAR,
  owner_zip VARCHAR,
  owner_out_of_area BOOLEAN,
  property_class VARCHAR,
  subdivision VARCHAR,
  year_built INTEGER,
  remodel_year INTEGER,
  roof_type VARCHAR,
  roof_material VARCHAR,
  roof_year INTEGER,
  roof_age_years INTEGER,
  roof_age_basis VARCHAR,
  open_permit_count INTEGER,
  open_roof_permit_count INTEGER,
  total_permit_count INTEGER,
  roof_permit_count INTEGER,
  oldest_open_permit_issued_at TIMESTAMP,
  oldest_open_roof_permit_issued_at TIMESTAMP,
  latest_roof_permit_issued_at TIMESTAMP,
  contractor_name VARCHAR,
  source_edited_at TIMESTAMP,
  assembled_at TIMESTAMP,
  run_id VARCHAR
)
"""


def main() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    connection = duckdb.connect(str(DB_PATH))

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE bldg AS
        SELECT prclid, year_built, remodel_year, roof_type, roof_material FROM (
          SELECT
            prclid,
            CASE WHEN try_cast(json_extract_string(attrs, '$.YEAR_BUILT') AS INTEGER) BETWEEN 1700 AND year(current_date)
                 THEN try_cast(json_extract_string(attrs, '$.YEAR_BUILT') AS INTEGER) END AS year_built,
            CASE WHEN try_cast(json_extract_string(attrs, '$.REMODEL_YEAR') AS INTEGER) BETWEEN 1700 AND year(current_date)
                 THEN try_cast(json_extract_string(attrs, '$.REMODEL_YEAR') AS INTEGER) END AS remodel_year,
            json_extract_string(attrs, '$.ROOF_TYPE') AS roof_type,
            json_extract_string(attrs, '$.ROOF_MATERIAL') AS roof_material,
            row_number() OVER (
              PARTITION BY prclid
              ORDER BY try_cast(json_extract_string(attrs, '$.YEAR_BUILT') AS INTEGER) NULLS LAST, object_id
            ) AS rn
          FROM county_record
          WHERE source = 'structures' AND prclid IS NOT NULL
        ) WHERE rn = 1
        """
    )

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE permit_all AS
        WITH base AS (
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
            ) AS contractor,
            source LIKE 'permits_open%' AS is_open
          FROM county_record
          WHERE source LIKE 'permits_%' AND prclid IS NOT NULL
        )
        SELECT * EXCLUDE (dup_rank)
        FROM (
          SELECT *,
            (
              regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
              OR regexp_replace(upper(coalesce(aptype, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
            )
            AND (
              upper(coalesce(aptype, '')) NOT IN ('HVAC', 'PLUMBING')
              OR regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g')
                 SIMILAR TO '%(ROOFING|SHINGLE|RE-ROOF|REROOF|SHEATHING)%'
            ) AS is_roof,
            row_number() OVER (
              PARTITION BY prclid, coalesce(apno, source || ':' || object_id::VARCHAR)
              ORDER BY CASE WHEN is_open THEN 0 ELSE 1 END, source, object_id
            ) AS dup_rank
          FROM base
        )
        WHERE dup_rank = 1
        """
    )

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE permit_roll AS
        SELECT
          prclid,
          count(*) AS total_permit_count,
          count(*) FILTER (WHERE is_open) AS open_permit_count,
          count(*) FILTER (WHERE is_open AND is_roof) AS open_roof_permit_count,
          count(*) FILTER (WHERE is_roof) AS roof_permit_count,
          min(issued_at) FILTER (WHERE is_open) AS oldest_open_permit_issued_at,
          min(issued_at) FILTER (WHERE is_open AND is_roof) AS oldest_open_roof_permit_issued_at,
          max(issued_at) FILTER (WHERE is_roof) AS latest_roof_permit_issued_at
        FROM permit_all
        GROUP BY prclid
        """
    )

    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE contractor AS
        SELECT prclid, contractor FROM (
          SELECT
            prclid,
            contractor,
            row_number() OVER (
              PARTITION BY prclid
              ORDER BY is_open DESC, issued_at DESC NULLS LAST
            ) AS rn
          FROM permit_all
          WHERE contractor IS NOT NULL
        ) WHERE rn = 1
        """
    )

    connection.execute(PARCEL_DDL)
    connection.execute(
        """
        INSERT INTO parcel
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
          s.owner_state IS NOT NULL
            AND s.owner_state <> ''
            AND upper(s.owner_state) NOT IN ('DE', 'DELAWARE') AS owner_out_of_area,
          s.property_class,
          s.subdivision,
          b.year_built,
          b.remodel_year,
          b.roof_type,
          b.roof_material,
          coalesce(b.year_built, year(r.latest_roof_permit_issued_at)) AS roof_year,
          year(current_date) - coalesce(b.year_built, year(r.latest_roof_permit_issued_at)) AS roof_age_years,
          CASE
            WHEN b.year_built IS NOT NULL THEN 'structure.year_built'
            WHEN r.latest_roof_permit_issued_at IS NOT NULL THEN 'latest_roof_permit'
            ELSE NULL
          END AS roof_age_basis,
          coalesce(r.open_permit_count, 0),
          coalesce(r.open_roof_permit_count, 0),
          coalesce(r.total_permit_count, 0),
          coalesce(r.roof_permit_count, 0),
          r.oldest_open_permit_issued_at,
          r.oldest_open_roof_permit_issued_at,
          r.latest_roof_permit_issued_at,
          c.contractor,
          s.source_edited_at,
          now() AS assembled_at,
          ? AS run_id
        FROM parcel_seed s
        LEFT JOIN parcel_point p ON p.prclid = s.prclid
        LEFT JOIN bldg b ON b.prclid = s.prclid
        LEFT JOIN permit_roll r ON r.prclid = s.prclid
        LEFT JOIN contractor c ON c.prclid = s.prclid
        """,
        [run_id],
    )

    connection.execute("DELETE FROM seed_status")
    connection.execute(
        """
        INSERT INTO seed_status
        SELECT prclid, 'assembled', ?, now(), source_edited_at FROM parcel_seed
        """,
        [run_id],
    )

    stats = connection.execute(
        """
        SELECT
          count(*),
          count(*) FILTER (WHERE lon IS NOT NULL),
          count(*) FILTER (WHERE year_built IS NOT NULL),
          count(*) FILTER (WHERE roof_material IS NOT NULL),
          count(*) FILTER (WHERE roof_age_years >= 15),
          count(*) FILTER (WHERE open_permit_count > 0),
          count(*) FILTER (WHERE open_roof_permit_count > 0),
          count(*) FILTER (WHERE owner_out_of_area),
          count(*) FILTER (WHERE contractor_name IS NOT NULL)
        FROM parcel
        """
    ).fetchone()
    print(
        f"run {run_id} parcels {stats[0]} coords {stats[1]} year_built {stats[2]} "
        f"roof_material {stats[3]} roof_age_15plus {stats[4]} any_open_permit {stats[5]} "
        f"open_roof_permit {stats[6]} out_of_area_owner {stats[7]} contractor {stats[8]}"
    )
    connection.close()


if __name__ == "__main__":
    main()
