"""MCP server over the New Castle County DuckDB query views.

Run: .venv/bin/python pipeline/mcp_server.py
Transport is stdio. Tools read lead_property and permit_detail. They do not
fetch the county site.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from query_layer import (
    LIMITATIONS,
    install,
    open_roof_permits,
    ownership_exchange,
    property_record,
    query_select,
    radius_search,
    source_summary,
)

install()

server = MCPServer(
    "newcastle-county",
    instructions=(
        "Read-only New Castle County, Delaware property and permit data in DuckDB. "
        "Use radius_search and open_roof_permits for roofing leads. "
        "Roof age is missing for most parcels. Sale history and BBB ratings are not loaded. "
        + " ".join(LIMITATIONS)
    ),
)


@server.tool()
def county_source_summary() -> dict:
    """Record counts, pipeline runs, and source limitations for New Castle County, DE."""
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
    """Properties within radius_miles of a pin. Default roof age threshold is 15 years."""
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
    """Open permits whose type or comment mentions roof, longest open first, with the contractor name printed on the permit."""
    return open_roof_permits(latitude, longitude, radius_miles, min_days_open, limit)


@server.tool()
def county_property_record(prclid: str) -> dict:
    """One parcel by county parcel id, plus its permit rows."""
    return property_record(prclid)


@server.tool()
def county_ownership_exchange(min_years: int = 10) -> dict:
    """Whether ownership has stayed with the same owner for min_years. This source cannot answer it."""
    return ownership_exchange(min_years)


@server.tool()
def county_query_select(sql: str, limit: int = 100) -> dict:
    """One read-only SELECT against the DuckDB views (lead_property, permit_detail) and loaded tables."""
    return query_select(sql, limit)


if __name__ == "__main__":
    server.run(transport="stdio")
