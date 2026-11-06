# New Castle County, DE — source findings

Probed 2026-11-05 from a US egress IP. No prior New Castle transform exists in the local Oracle runtime.

## What is loaded

DuckDB file `data/duckdb/newcastle.duckdb`. Query views `lead_property` and `permit_detail` (macro `miles_between`) are installed by `pipeline/query_layer.py`. The MCP server is `pipeline/mcp_server.py`.

| Store | Rows | Source |
|---|---|---|
| `parcel_seed` / `parcel` | 203,882 | Owner CSV dated 2026-11-05. 13 duplicate parcel ids collapsed. |
| Coordinates on `parcel` | 203,855 | Parcel-point shapefile, Delaware State Plane feet, transformed to WGS84. 27 seeds have no point. |
| `county_record` structures | 238,601 | `BaseMaps/Base_Layers` layer 6. Roof material on most buildings. Year built on 4,432 parcels. |
| `county_record` addresses, units, mobile lots | 243,195 / 39,899 / 5,290 | Same service, layers 4, 5, and 7. |
| `county_record` permits | 12 layers, about 701,000 rows | `CustomMaps/Permits` layers 0–11. Keyed by `NEW_OID` because `OBJECTID` repeats. |
| Appeals, rollback, assessment requests | 7 / 1,753 / 2,185 / 496 | `BaseMaps/Assessment` layers 22, 23, 24, 29. |

Parcel rollup after `pipeline/build_parcels.py` run `20261106T163040Z`: roofs with an age of 15 or more 6,043; any open permit 10,735; open roof permit 178; out-of-area owner 10,542; contractor name printed on a permit 113,046. A rooftop HVAC unit and a plumbing permit are not counted as a roof permit. A year-built age is the building year, not a measured roof replacement.

Two pipeline runs are recorded. The second assembled 0 parcels.

## Query answers

- Radius, roof age, open roof permits, and out-of-area owners are answered from `lead_property` and `permit_detail`.
- Contractor name is the string on the permit. It is not a Delaware license match.
- BBB ratings are not loaded.
- “No ownership change in 10 years” is not answered. The GIS layers have no sale date.

## robots.txt

`https://www3.newcastlede.gov/robots.txt` (fetched 2026-11-05):

```
User-agent: *
Allow: /parcel/search/default.aspx
Allow: /permit/search/default.aspx
Allow: /project/search/default.aspx
Allow: /will/search/default.aspx
Allow: /legislation/search/default.aspx
Disallow: /
```

`/parcel/Details/` is not in the allow list, so it is disallowed. That page is also the only place the county publishes deed history, sale date, and assessed value for a parcel. A direct request for a parcel key was redirected, and both curl and a browser received a bot challenge instead of the form. This pipeline does not bypass that challenge.

`https://gis.nccde.org/robots.txt` returns 404. The feature services below were read in full.

- https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer
- https://gis.nccde.org/agsserver/rest/services/CustomMaps/Permits/MapServer
- https://gis.nccde.org/agsserver/rest/services/BaseMaps/Assessment/MapServer

## Still out

Delaware corporate registry and contractor-license snapshot (required before treating a permit name as a company). BBB. Wilmington permits the county layer does not contain. Recorder images at `https://NewCastle.dts-de.com/PAXWorld` charge per page and stay out of the automated fetch.
