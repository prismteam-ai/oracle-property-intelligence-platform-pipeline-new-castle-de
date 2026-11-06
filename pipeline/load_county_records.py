"""Store every attribute the county publishes on its parcel and permit services.

Plain HTTP against the county GIS map services. One row per source feature,
all fields kept in attrs. Rows that carry a parcel id are keyed back to the seed.
The parcel HTML page is not requested: robots.txt disallows /parcel/Details/.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from arcgis import ASSESSMENT, BASE_LAYERS, PERMITS, iter_pages

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "duckdb" / "newcastle.duckdb"

# Published feature layers that carry a parcel id or a permit record.
LAYERS = [
    (BASE_LAYERS, 6, "structures"),
    (BASE_LAYERS, 4, "addresses"),
    (BASE_LAYERS, 5, "units"),
    (BASE_LAYERS, 7, "mobile_lots"),
    (PERMITS, 0, "permits_open"),
    (PERMITS, 1, "permits_open_manufactured"),
    (PERMITS, 2, "permits_expired"),
    (PERMITS, 3, "permits_expired_manufactured"),
    (PERMITS, 4, "permits_new_construction"),
    (PERMITS, 5, "permits_adu"),
    (PERMITS, 6, "permits_hold_checkbox"),
    (PERMITS, 7, "permits_hold_engineering"),
    (PERMITS, 8, "permits_hold_historical"),
    (PERMITS, 9, "permits_hold_sewer"),
    (PERMITS, 10, "permits_released"),
    (PERMITS, 11, "permits_open_commercial"),
    (ASSESSMENT, 22, "appeals_active"),
    (ASSESSMENT, 23, "appeals_closed"),
    (ASSESSMENT, 24, "rollback_parcels"),
    (ASSESSMENT, 29, "assessment_requests_over_3_years"),
]


def parcel_id(attrs: dict) -> str | None:
    for key in ("PRCLID", "PARCELID"):
        value = attrs.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def object_id(attrs: dict):
    for key in ("NEW_OID", "OBJECTID", "ESRI_OID"):
        if attrs.get(key) is not None:
            return int(attrs[key])
    return None


def main() -> None:
    connection = duckdb.connect(str(DB_PATH))
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS county_record (
          source VARCHAR,
          object_id BIGINT,
          prclid VARCHAR,
          attrs JSON,
          fetched_at TIMESTAMP,
          PRIMARY KEY (source, object_id)
        );
        CREATE TABLE IF NOT EXISTS county_record_marker (
          source VARCHAR PRIMARY KEY,
          row_count BIGINT,
          finished_at TIMESTAMP
        );
        """
    )
    for service, layer_id, name in LAYERS:
        done = connection.execute(
            "SELECT row_count FROM county_record_marker WHERE source = ?",
            [name],
        ).fetchone()
        if done and done[0] > 0:
            print(f"skip {name} ({done[0]})")
            continue
        print(f"loading {name}")
        total = 0
        fetched_at = datetime.now(timezone.utc)
        try:
            for page in iter_pages(f"{service}/{layer_id}"):
                rows = []
                for attrs in page:
                    oid = object_id(attrs)
                    if oid is None:
                        continue
                    rows.append((name, oid, parcel_id(attrs), json.dumps(attrs), fetched_at))
                if rows:
                    connection.executemany(
                        "INSERT OR REPLACE INTO county_record VALUES (?, ?, ?, ?, ?)",
                        rows,
                    )
                    total += len(rows)
                if total and total % 25000 == 0:
                    print(f"  {name} {total}")
        except RuntimeError as error:
            print(f"stopped {name}: {error}")
            continue
        connection.execute(
            """
            INSERT INTO county_record_marker VALUES (?, ?, ?)
            ON CONFLICT (source) DO UPDATE SET
              row_count = excluded.row_count,
              finished_at = excluded.finished_at
            """,
            [name, total, fetched_at],
        )
        print(f"  {name} {total}")
    print(connection.execute(
        "SELECT source, count(*) FROM county_record GROUP BY 1 ORDER BY 1"
    ).fetchall())


if __name__ == "__main__":
    main()
