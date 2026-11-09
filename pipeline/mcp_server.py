"""MCP server over the published New Castle County JSON snapshot.

Run: .venv/bin/python pipeline/mcp_server.py
Transport is stdio. Tools read web/data/leads.json, permits.json, and
summary.json. They do not open the internal DuckDB and they do not fetch the
county site. @elephant-xyz/mcp is the Atlas server and starts only after a
lexicon archive is on the global Atlas index.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from published import (
    open_roof_permits,
    ownership_exchange,
    property_record,
    query_select,
    radius_search,
    source_summary,
)
from query_layer import LIMITATIONS

server = MCPServer(
    "newcastle-county",
    instructions=(
        "Read-only New Castle County, Delaware property and permit data from the published JSON snapshot. "
        "Use radius_search and open_roof_permits for roofing leads. "
        "The snapshot is parcels with a roof age of at least 15 years or an open roof permit. "
        "Roof age is missing for most parcels. Sale history is not loaded. "
        "BBB ratings were not submitted because www.bbb.org/robots.txt disallows category pages. "
        "last_roof_contractor_name is the name on the latest closed or new-construction roof permit. "
        "The open-permit layer prints a contractor on only a few rows. "
        "license_* fields are an exact name match to the Delaware business contractor licenses; a match does not confirm the contractor's identity. "
        "This server is not @elephant-xyz/mcp. "
        + " ".join(LIMITATIONS)
    ),
)


@server.tool()
def county_source_summary() -> dict:
    """Record counts and source limitations for the published New Castle County, DE snapshot."""
    return source_summary()


@server.tool()
def county_radius_search(
    latitude: float,
    longitude: float,
    radius_miles: float = 5,
    min_roof_age_years: int | None = 15,
    open_roof_permits_only: bool = False,
    min_days_open: int | None = None,
    out_of_area_owner: bool = False,
    limit: int = 25,
) -> dict:
    """Properties in the published snapshot within radius_miles of a pin."""
    return radius_search(
        latitude,
        longitude,
        radius_miles,
        min_roof_age_years,
        open_roof_permits_only,
        min_days_open,
        out_of_area_owner,
        limit,
    )


@server.tool()
def county_open_roof_permits(
    latitude: float,
    longitude: float,
    radius_miles: float = 5,
    min_days_open: int | None = None,
    limit: int = 25,
) -> dict:
    """Open roof permits in the published snapshot, longest open first."""
    return open_roof_permits(latitude, longitude, radius_miles, min_days_open, limit)


@server.tool()
def county_property_record(prclid: str) -> dict:
    """One published parcel by county parcel id, plus its open roof-permit rows."""
    return property_record(prclid)


@server.tool()
def county_ownership_exchange(min_years: int = 10) -> dict:
    """Whether ownership has stayed with the same owner for min_years. This source cannot answer it."""
    return ownership_exchange(min_years)


@server.tool()
def county_query_select(sql: str, limit: int = 100) -> dict:
    """One read-only SELECT against the published tables leads, permits, and summary."""
    return query_select(sql, limit)


if __name__ == "__main__":
    server.run(transport="stdio")
