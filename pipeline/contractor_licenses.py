"""Match permit contractor names to the Delaware business contractor licenses.

Source: Delaware Division of Revenue business licenses, SODA dataset 5zy2-grhr,
saved by the SODA pull at data/soda/business-contractors.json. Only the
contractor categories are read. Trade licenses (pjnv-eaih) are issued to people,
so they are not matched to company names on permits.

A match is exact after case, ampersand, punctuation, and spacing normalization.
It is a name match. It does not confirm that the permit contractor is the
licensee, or that the license class covers the permitted work.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
LICENSE_PATH = ROOT / "data" / "soda" / "business-contractors.json"


def license_path() -> Path:
    """The SODA license file. NEW_CASTLE_LICENSES overrides it, so tests can supply a fixture."""
    override = os.environ.get("NEW_CASTLE_LICENSES")
    return Path(override) if override else LICENSE_PATH
SOURCE = "Delaware Business Licenses, SODA 5zy2-grhr (contractor categories)"
CONTRACTOR_CATEGORIES = {"RESIDENT CONTRACTOR", "NON-RESIDENT CONTRACTOR", "CONSTRUCTION MANAGER"}

# Permit rows that print a placeholder instead of a company. They never match a license.
PLACEHOLDER_NAMES = {"HOMEOWNER PERMIT", "OWNER", "HOMEOWNER", "NONE", "N/A"}

MATCH_BASIS = "exact name after case and punctuation normalization"

TABLE_SQL = """
CREATE OR REPLACE TABLE contractor_license_match (
  contractor_name VARCHAR,
  license_name VARCHAR,
  license_category VARCHAR,
  license_valid_to DATE,
  license_city VARCHAR,
  license_state VARCHAR,
  license_number VARCHAR,
  license_records INTEGER,
  license_match_basis VARCHAR,
  license_source VARCHAR
)
"""


def name_key(value: str | None) -> str:
    """Upper-case, ampersand as AND, punctuation removed, single spaces."""
    text = (value or "").upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return " ".join(text.split())


def _valid_to(record: dict) -> date | None:
    raw = record.get("current_license_valid_to")
    if not raw:
        return None
    return date.fromisoformat(raw[:10])


def _is_active(record: dict, today: date) -> bool:
    valid_to = _valid_to(record)
    return valid_to is not None and valid_to >= today


def load_licenses(path: Path | None = None) -> list[dict]:
    records = json.loads((path or license_path()).read_text())
    return [r for r in records if r.get("category") in CONTRACTOR_CATEGORIES]


def build_matches(
    permit_names: Iterable[str],
    licenses: list[dict],
    today: date | None = None,
) -> list[dict]:
    """Return one match row per permit contractor name that exactly matches a license name.

    When several license records share a name, prefer an active one, then a
    Delaware address, then the latest expiration date.
    """
    today = today or date.today()
    index: dict[str, list[dict]] = defaultdict(list)
    for record in licenses:
        for field in ("business_name", "trade_name"):
            key = name_key(record.get(field))
            if key:
                index[key].append(record)

    rows = []
    for raw in sorted({n.strip() for n in permit_names if n and n.strip()}):
        key = name_key(raw)
        if not key or key in PLACEHOLDER_NAMES:
            continue
        hits = index.get(key)
        if not hits:
            continue
        # Dedupe the same license record that matched on both business and trade name.
        unique = {id(h): h for h in hits}.values()
        best = min(
            unique,
            key=lambda h: (
                0 if _is_active(h, today) else 1,
                0 if (h.get("state") or "").upper() == "DE" else 1,
                -(_valid_to(h) or date.min).toordinal(),
            ),
        )
        rows.append(
            {
                "contractor_name": raw,
                "license_name": best.get("business_name") or best.get("trade_name"),
                "license_category": best.get("category"),
                "license_valid_to": _valid_to(best),
                "license_city": best.get("city"),
                "license_state": (best.get("state") or None),
                "license_number": best.get("license_number"),
                "license_records": len({id(h) for h in unique}),
                "license_match_basis": MATCH_BASIS,
                "license_source": SOURCE,
            }
        )
    return rows


def install(connection, path: Path | None = None, today: date | None = None) -> dict:
    """Rebuild contractor_license_match from the distinct permit contractor names in the database."""
    names = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT contractor_name FROM permit_base WHERE contractor_name IS NOT NULL"
        ).fetchall()
    ]
    licenses = load_licenses(path)
    matches = build_matches(names, licenses, today=today)
    connection.execute(TABLE_SQL)
    if matches:
        columns = list(matches[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        connection.executemany(
            f"INSERT INTO contractor_license_match ({', '.join(columns)}) VALUES ({placeholders})",
            [tuple(row[c] for c in columns) for row in matches],
        )
    return {"permit_names": len(names), "license_records": len(licenses), "matched_names": len(matches)}
