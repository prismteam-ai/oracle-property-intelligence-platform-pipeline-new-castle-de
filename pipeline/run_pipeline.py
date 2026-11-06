"""Seed every New Castle County parcel, then assemble one parcel record at a time.

Seed source: the county parcel-owner CSV (parcel id, ParcelKey, owner, address).
Each seed row is a work item. Coordinates come from the parcel-point shapefile.
Year built, roof material, and permits come from the live county map services
and are attached while walking the seed list. A later run skips a parcel whose
source edit time has not changed.
"""

from __future__ import annotations

import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import duckdb

from arcgis import PERMITS, SSL_CONTEXT, STRUCTURES, iter_pages

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "duckdb" / "newcastle.duckdb"
OWNER_ZIP_URL = (
    "https://gis.nccde.org/agsserver/rest/directories/arcgisoutput/downloads/zipped/Parcel_Owners_CSV.zip"
)
POINT_ZIP_URL = (
    "https://gis.nccde.org/agsserver/rest/directories/arcgisoutput/downloads/zipped/Parcel_Points_SHP.zip"
)
PARCEL_PAGE = "https://www3.newcastlede.gov/parcel/Details/Default.aspx?ParcelKey="

STRUCTURE_FIELDS = [
    "PARCELID",
    "PRCLID",
    "YEAR_BUILT",
    "REMODEL_YEAR",
    "ROOF_TYPE",
    "ROOF_MATERIAL",
    "BLDG_DESIGN",
    "CONDITION",
    "last_edited_date",
]
PERMIT_FIELDS = [
    "PARCELID",
    "PRCLID",
    "APNO",
    "APTYPE",
    "ISSDTTM",
    "COMMENTS",
    "DESCRIPT",
    "CONTRACTORNAME",
]
PERMIT_LAYERS = [
    (0, "open", "open", "1=1"),
    (1, "open_manufactured", "open", "1=1"),
    (2, "expired_roof", "recorded", "UPPER(COMMENTS) LIKE '%ROOF%'"),
    (3, "expired_manufactured_roof", "recorded", "UPPER(COMMENTS) LIKE '%ROOF%'"),
    (4, "new_construction_roof", "recorded", "UPPER(COMMENTS) LIKE '%ROOF%'"),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connect() -> duckdb.DuckDBPyConnection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(DB_PATH))
    connection.execute("LOAD spatial")
    connection.execute("SET geometry_always_xy = true")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_run (
          run_id VARCHAR PRIMARY KEY,
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          seed_rows BIGINT,
          seed_parcels BIGINT,
          assembled BIGINT,
          skipped BIGINT,
          structure_rows BIGINT,
          permit_rows BIGINT,
          with_coordinates BIGINT,
          with_year_built BIGINT,
          roofs_older_than_15 BIGINT,
          open_roof_permits BIGINT,
          note VARCHAR
        );
        CREATE TABLE IF NOT EXISTS extract_marker (
          name VARCHAR PRIMARY KEY,
          row_count BIGINT,
          finished_at TIMESTAMP
        );
        """
    )
    return connection


def download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {destination.name}")
    with urlopen(url, timeout=180, context=SSL_CONTEXT) as response, destination.open("wb") as handle:
        handle.write(response.read())


def ensure_files() -> tuple[Path, Path]:
    owner_zip = RAW / "Parcel_Owners_CSV.zip"
    point_zip = RAW / "Parcel_Points_SHP.zip"
    download(OWNER_ZIP_URL, owner_zip)
    download(POINT_ZIP_URL, point_zip)
    owner_csv = RAW / "PRIMARYADDRPRIMARYOWNER_POLY_static.csv"
    point_shp = RAW / "points" / "parcel_point.shp"
    if not owner_csv.exists():
        with zipfile.ZipFile(owner_zip) as archive:
            archive.extractall(RAW)
    if not point_shp.exists():
        point_shp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(point_zip) as archive:
            archive.extractall(point_shp.parent)
    return owner_csv, point_shp


def marker_done(connection: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = connection.execute(
        "SELECT row_count FROM extract_marker WHERE name = ?", [name]
    ).fetchone()
    return row is not None and row[0] > 0


def mark(connection: duckdb.DuckDBPyConnection, name: str, row_count: int) -> None:
    connection.execute(
        """
        INSERT INTO extract_marker VALUES (?, ?, ?)
        ON CONFLICT (name) DO UPDATE SET row_count = excluded.row_count, finished_at = excluded.finished_at
        """,
        [name, row_count, utcnow()],
    )


def load_seed(connection: duckdb.DuckDBPyConnection, owner_csv: Path) -> None:
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE parcel_seed AS
        WITH ranked AS (
          SELECT
            trim(PRCLID) AS prclid,
            PRCLKEY::BIGINT AS prclkey,
            '{PARCEL_PAGE}' || PRCLKEY::VARCHAR AS parcel_url,
            trim(ADDRESS) AS address,
            trim(PROPCITY) AS city,
            trim(PROPSTATE) AS state,
            trim(PROPZIP) AS zip,
            trim(CNTCTLAST) AS owner_name,
            trim(OWNADDR) AS owner_address,
            trim(OWNCITY) AS owner_city,
            trim(OWNSTATE) AS owner_state,
            trim(OWNZIP) AS owner_zip,
            trim(PROPCLASS) AS property_class,
            trim(SUBDIV) AS subdivision,
            LOTSZ::DOUBLE AS lot_acres,
            coalesce(
              try_strptime(last_edited_date, '%-m/%-d/%Y %H:%M:%S.%f'),
              try_strptime(last_edited_date, '%m/%d/%Y %H:%M:%S.%f'),
              try_strptime(last_edited_date, '%-m/%-d/%Y %H:%M:%S'),
              try_strptime(last_edited_date, '%m/%d/%Y %H:%M:%S')
            ) AS source_edited_at,
            row_number() OVER (
              PARTITION BY trim(PRCLID)
              ORDER BY CASE WHEN PRIMADDR = 'Y' THEN 0 ELSE 1 END, NEW_OID
            ) AS rn
          FROM read_csv('{owner_csv.as_posix()}', header = true, auto_detect = true)
          WHERE PRCLID IS NOT NULL AND trim(PRCLID) <> ''
        )
        SELECT * EXCLUDE (rn) FROM ranked WHERE rn = 1
        """
    )
    count = connection.execute("SELECT count(*) FROM parcel_seed").fetchone()[0]
    print(f"seed parcels {count}")


def load_points(connection: duckdb.DuckDBPyConnection, point_shp: Path) -> None:
    if marker_done(connection, "parcel_point"):
        print("parcel points already loaded")
        return
    print("loading parcel point coordinates")
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE parcel_point AS
        SELECT trim(PARCELID) AS prclid,
               avg(ST_X(ST_Transform(geom, 'EPSG:4326'))) AS lon,
               avg(ST_Y(ST_Transform(geom, 'EPSG:4326'))) AS lat
        FROM st_read('{point_shp.as_posix()}')
        WHERE PARCELID IS NOT NULL AND trim(PARCELID) <> ''
        GROUP BY 1
        """
    )
    count = connection.execute("SELECT count(*) FROM parcel_point").fetchone()[0]
    mark(connection, "parcel_point", count)
    print(f"parcel points {count}")


def year_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    year = int(value)
    if year < 1700 or year > utcnow().year:
        return None
    return year


def epoch_or_none(value):
    if value is None or value == "":
        return None
    return datetime.fromtimestamp(float(value) / 1000, timezone.utc)


def load_structures(connection: duckdb.DuckDBPyConnection, refresh: bool) -> None:
    if marker_done(connection, "structure") and not refresh:
        print("structures already loaded")
        return
    connection.execute(
        """
        CREATE OR REPLACE TABLE structure (
          prclid VARCHAR,
          year_built INTEGER,
          remodel_year INTEGER,
          roof_type VARCHAR,
          roof_material VARCHAR,
          building_design VARCHAR,
          condition VARCHAR,
          source_edited_at TIMESTAMP
        )
        """
    )
    total = 0
    for page_number, page in enumerate(
        iter_pages(STRUCTURES, STRUCTURE_FIELDS), start=1
    ):
        rows = []
        for item in page:
            prclid = (item.get("PRCLID") or item.get("PARCELID") or "").strip()
            if not prclid:
                continue
            rows.append(
                (
                    prclid,
                    year_or_none(item.get("YEAR_BUILT")),
                    year_or_none(item.get("REMODEL_YEAR")),
                    (item.get("ROOF_TYPE") or "").strip() or None,
                    (item.get("ROOF_MATERIAL") or "").strip() or None,
                    (item.get("BLDG_DESIGN") or "").strip() or None,
                    (item.get("CONDITION") or "").strip() or None,
                    epoch_or_none(item.get("last_edited_date")),
                )
            )
        connection.executemany("INSERT INTO structure VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        total += len(rows)
        if page_number % 25 == 0:
            print(f"structures {total}")
    connection.execute("CREATE INDEX IF NOT EXISTS structure_prclid ON structure(prclid)")
    mark(connection, "structure", total)
    print(f"structures {total}")


def load_permits(connection: duckdb.DuckDBPyConnection, refresh: bool) -> None:
    if marker_done(connection, "permit") and not refresh:
        print("permits already loaded")
        return
    connection.execute(
        """
        CREATE OR REPLACE TABLE permit (
          prclid VARCHAR,
          apno VARCHAR,
          aptype VARCHAR,
          issued_at TIMESTAMP,
          comments VARCHAR,
          contractor_name VARCHAR,
          layer_name VARCHAR,
          status VARCHAR
        )
        """
    )
    total = 0
    for layer_id, layer_name, status, where in PERMIT_LAYERS:
        layer_url = f"{PERMITS}/{layer_id}"
        print(f"permits {layer_name}")
        try:
            pages = iter_pages(layer_url, PERMIT_FIELDS, where)
            for page in pages:
                rows = []
                for item in page:
                    prclid = (item.get("PRCLID") or item.get("PARCELID") or "").strip()
                    if not prclid:
                        continue
                    rows.append(
                        (
                            prclid,
                            (item.get("APNO") or "").strip() or None,
                            (item.get("APTYPE") or "").strip() or None,
                            epoch_or_none(item.get("ISSDTTM")),
                            (item.get("COMMENTS") or "").strip() or None,
                            (item.get("CONTRACTORNAME") or "").strip() or None,
                            layer_name,
                            status,
                        )
                    )
                if rows:
                    connection.executemany(
                        "INSERT INTO permit VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
                    )
                    total += len(rows)
        except RuntimeError as error:
            print(f"skipped {layer_name}: {error}")
    connection.execute("CREATE INDEX IF NOT EXISTS permit_prclid ON permit(prclid)")
    mark(connection, "permit", total)
    print(f"permits {total}")


def ensure_parcel_table(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS parcel (
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
          oldest_open_permit_issued_at TIMESTAMP,
          oldest_open_roof_permit_issued_at TIMESTAMP,
          latest_roof_permit_issued_at TIMESTAMP,
          contractor_name VARCHAR,
          source_edited_at TIMESTAMP,
          assembled_at TIMESTAMP,
          run_id VARCHAR
        );
        CREATE TABLE IF NOT EXISTS seed_status (
          prclid VARCHAR PRIMARY KEY,
          status VARCHAR,
          run_id VARCHAR,
          assembled_at TIMESTAMP,
          source_edited_at TIMESTAMP
        );
        """
    )


def assemble_batch(connection: duckdb.DuckDBPyConnection, run_id: str, batch: int) -> int:
    pending = connection.execute(
        """
        SELECT s.prclid
        FROM parcel_seed s
        LEFT JOIN seed_status t ON t.prclid = s.prclid
        WHERE t.prclid IS NULL
           OR t.source_edited_at IS DISTINCT FROM s.source_edited_at
        ORDER BY s.prclid
        LIMIT ?
        """,
        [batch],
    ).fetchall()
    if not pending:
        return 0
    connection.execute("CREATE OR REPLACE TEMP TABLE walk_batch (prclid VARCHAR)")
    connection.executemany("INSERT INTO walk_batch VALUES (?)", pending)
    connection.execute("BEGIN")
    connection.execute(
        """
        DELETE FROM parcel WHERE prclid IN (SELECT prclid FROM walk_batch);
        INSERT INTO parcel
        WITH building AS (
          SELECT * EXCLUDE (rn) FROM (
            SELECT
              prclid, year_built, remodel_year, roof_type, roof_material,
              row_number() OVER (
                PARTITION BY prclid
                ORDER BY year_built IS NULL, year_built, roof_material IS NULL
              ) AS rn
            FROM structure
            WHERE prclid IN (SELECT prclid FROM walk_batch)
          )
          WHERE rn = 1
        ),
        permit_roll AS (
          SELECT
            prclid,
            count(*) FILTER (WHERE status = 'open') AS open_permit_count,
            count(*) FILTER (
              WHERE status = 'open'
                AND (
                  regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
                  OR regexp_replace(upper(coalesce(aptype, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
                )
                AND (
                  upper(coalesce(aptype, '')) NOT IN ('HVAC', 'PLUMBING')
                  OR regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g')
                     SIMILAR TO '%(ROOFING|SHINGLE|RE-ROOF|REROOF|SHEATHING)%'
                )
            ) AS open_roof_permit_count,
            min(issued_at) FILTER (WHERE status = 'open') AS oldest_open_permit_issued_at,
            min(issued_at) FILTER (
              WHERE status = 'open'
                AND (
                  regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
                  OR regexp_replace(upper(coalesce(aptype, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
                )
                AND (
                  upper(coalesce(aptype, '')) NOT IN ('HVAC', 'PLUMBING')
                  OR regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g')
                     SIMILAR TO '%(ROOFING|SHINGLE|RE-ROOF|REROOF|SHEATHING)%'
                )
            ) AS oldest_open_roof_permit_issued_at,
            max(issued_at) FILTER (
              WHERE (
                regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
                OR regexp_replace(upper(coalesce(aptype, '')), 'ROOF[ -]?TOP', ' ', 'g') LIKE '%ROOF%'
              )
              AND (
                upper(coalesce(aptype, '')) NOT IN ('HVAC', 'PLUMBING')
                OR regexp_replace(upper(coalesce(comments, '')), 'ROOF[ -]?TOP', ' ', 'g')
                   SIMILAR TO '%(ROOFING|SHINGLE|RE-ROOF|REROOF|SHEATHING)%'
              )
            ) AS latest_roof_permit_issued_at
          FROM permit
          WHERE prclid IN (SELECT prclid FROM walk_batch)
          GROUP BY prclid
        ),
        contractor AS (
          SELECT prclid, contractor_name FROM (
            SELECT
              prclid,
              contractor_name,
              row_number() OVER (
                PARTITION BY prclid
                ORDER BY CASE WHEN status = 'open' THEN 0 ELSE 1 END, issued_at DESC NULLS LAST
              ) AS rn
            FROM permit
            WHERE contractor_name IS NOT NULL
              AND prclid IN (SELECT prclid FROM walk_batch)
          )
          WHERE rn = 1
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
          r.oldest_open_permit_issued_at,
          r.oldest_open_roof_permit_issued_at,
          r.latest_roof_permit_issued_at,
          c.contractor_name,
          s.source_edited_at,
          ? AS assembled_at,
          ? AS run_id
        FROM parcel_seed s
        JOIN walk_batch w ON w.prclid = s.prclid
        LEFT JOIN parcel_point p ON p.prclid = s.prclid
        LEFT JOIN building b ON b.prclid = s.prclid
        LEFT JOIN permit_roll r ON r.prclid = s.prclid
        LEFT JOIN contractor c ON c.prclid = s.prclid
        """,
        [utcnow(), run_id],
    )
    connection.execute(
        """
        DELETE FROM seed_status WHERE prclid IN (SELECT prclid FROM walk_batch);
        INSERT INTO seed_status
        SELECT s.prclid, 'assembled', ?, ?, s.source_edited_at
        FROM parcel_seed s
        JOIN walk_batch w ON w.prclid = s.prclid
        """,
        [run_id, utcnow()],
    )
    connection.execute("COMMIT")
    return len(pending)


def walk_seeds(connection: duckdb.DuckDBPyConnection, run_id: str, batch: int, limit: int | None) -> int:
    ensure_parcel_table(connection)
    assembled = 0
    while limit is None or assembled < limit:
        this_batch = batch if limit is None else min(batch, limit - assembled)
        count = assemble_batch(connection, run_id, this_batch)
        if count == 0:
            break
        assembled += count
        print(f"assembled {assembled}")
    return assembled


def summarize(connection: duckdb.DuckDBPyConnection, run_id: str, started_at: datetime, assembled: int) -> None:
    seed_parcels = connection.execute("SELECT count(*) FROM parcel_seed").fetchone()[0]
    skipped = seed_parcels - assembled
    stats = connection.execute(
        """
        SELECT
          (SELECT count(*) FROM structure),
          (SELECT count(*) FROM permit),
          (SELECT count(*) FROM parcel WHERE lon IS NOT NULL),
          (SELECT count(*) FROM parcel WHERE year_built IS NOT NULL),
          (SELECT count(*) FROM parcel WHERE roof_age_years >= 15),
          (SELECT count(*) FROM parcel WHERE open_roof_permit_count > 0)
        """
    ).fetchone()
    note = (
        "Seed is the parcel-owner CSV. Coordinates are the parcel-point shapefile. "
        "Year built and roof material are the structures layer. "
        "Deed sale dates are still only on the parcel HTML page."
    )
    connection.execute(
        """
        INSERT INTO pipeline_run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            started_at,
            utcnow(),
            seed_parcels,
            seed_parcels,
            assembled,
            skipped,
            stats[0],
            stats[1],
            stats[2],
            stats[3],
            stats[4],
            stats[5],
            note,
        ],
    )
    print(
        "run",
        run_id,
        "assembled",
        assembled,
        "already current",
        skipped,
        "with coordinates",
        stats[2],
        "with year built",
        stats[3],
        "roofs older than 15",
        stats[4],
        "open roof permits",
        stats[5],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-county", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch", type=int, default=2000)
    args = parser.parse_args()

    owner_csv, point_shp = ensure_files()
    connection = connect()
    started_at = utcnow()
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    load_seed(connection, owner_csv)
    load_points(connection, point_shp)
    load_structures(connection, args.refresh_county)
    load_permits(connection, args.refresh_county)
    assembled = walk_seeds(connection, run_id, args.batch, args.limit)
    summarize(connection, run_id, started_at, assembled)


if __name__ == "__main__":
    main()
