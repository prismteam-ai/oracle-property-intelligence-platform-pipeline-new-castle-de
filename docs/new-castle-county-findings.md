# New Castle County, DE — source findings

Probed 2026-11-05 from a US egress IP. The kit permit profile for New Castle is `counties/new-castle/permit-profile.mjs`. On 2026-11-06 the same `arcgis-feature-service` adapter returned `ready` for every registered layer: open permits 7,906; expired 2,258; expired manufactured 583,842; new construction 55,092; hold permit 4,742; hold engineering 16,977; hold historical 112; hold sewer 84.

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

Parcel rollup after the current query views: roofs with an age of 15 or more 4,819; any open permit 10,735; open roof permit 114 parcels and 117 permit rows; out-of-area owner 10,542; any-permit contractor 113,046; last roof contractor 2,444. A rooftop HVAC unit and a plumbing permit are not counted as a roof permit. A year-built age is the building year, not a measured roof replacement.

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

## Source access and robots.txt

Each entry says what we tried, what the protocol allows, and whether a submission was made.

**BBB contractor reputation.** Citation: BBB ratings were not submitted. `https://www.bbb.org/robots.txt` disallows `/*?` and `/business-reviews/*`, so no BBB harvest was submitted. The kit command is `elephant-county bbb-harvest`. The official route that robots.txt does not cover is an approved key at `https://developer.bbb.org`. That access has not been requested.

**Parcel sale and deed history (`www3.newcastlede.gov/parcel/Details/`).** We tried to read sale and deed history on this page. The site's `robots.txt` is `Disallow: /` with allow rules only for the search pages, so we could not submit the Details path. The site also serves a bot challenge, which this pipeline does not bypass.

**Delaware contractor licenses (SODA).** `https://data.delaware.gov/robots.txt` was read in full on 2026-11-06. It sets `Crawl-delay: 1` and disallows browse, catalog, and facet query-string filters. It does not disallow `/resource/`. `data.delaware.gov` returns 404 for `m8qx-ubtq`; that id is a Washington L&I dataset, not a Delaware one. The Delaware reads used SODA:

- Business licenses, `5zy2-grhr`: 9,152 resident contractors, 4,943 non-resident contractors, 91 construction managers. Saved at `data/soda/business-contractors.json`.
- Trade licenses, `pjnv-eaih`: 18,690 rows whose license type contains electrician, plumber, or HVAC. Saved at `data/soda/trade-licenses.json`.

The lexicon manifest at `https://lexicon.elephant.xyz/api/manifest` has no `license` class. These rows are not written as a lexicon edge and are not matched to a permit name. Counts are in `data/soda/pull.json`.

**Gridded parcel and permit layers (`gis.nccde.org`).** `robots.txt` returns 404, so there is no file to disallow. The feature services listed above were read through the ArcGIS REST protocol.

## Still out

Delaware corporate registry (required before treating a permit name as a company). BBB, pending the developer API access above. Wilmington permits the county layer does not contain. Recorder images at `https://NewCastle.dts-de.com/PAXWorld` charge per page and stay out of the automated fetch. The live lexicon manifest has County and Property_Improvement data groups, and property, address, parcel, and structure classes. It still has no `license` class, so the Delaware license rows stay unmatched. On 2026-11-06, `elephant-cli` 1.58.1 (`github:elephant-xyz/elephant-cli#main`) validated one real parcel, `0601000028`, from `lexicon-sample/` against `https://lexicon.elephant.xyz/api/manifest`. The run failed, 21 errors, 0 of 1 properties succeeded. The blocking data error is `unnormalized_address.county_jurisdiction`: New Castle is not in the enum. The enum is Florida, Texas, California, and Allegheny. No Delaware county is listed. One relationship schema CID also failed to fetch. `hash`, CAR upload, and an Atlas page were not run, because validate did not pass. The error rows are `lexicon-sample/errors.csv`. `@elephant-xyz/mcp` syncs after an archive is on the global Atlas index. Until then, `pipeline/mcp_server.py` reads the published JSON snapshot in `web/data`, not the internal DuckDB.

## Rebuild

The custom ArcGIS and parcel download scripts are gone. Rebuild permits with the kit runtime, from a checkout that has this profile registered:

```bash
node bin/elephant-county.mjs permit-probe --county new-castle
```

A bounded harvest is `permit-bounded-harvest`. It needs a property parquet and a `--limit`. It does not replace the appraisal transform. DuckDB at `data/duckdb/newcastle.duckdb` is the earlier load. `pipeline/query_layer.py` installs the query views on that file and exports the hosted JSON. `pipeline/mcp_server.py` reads that JSON. It is not `@elephant-xyz/mcp`.

`with_any_permit_contractor` is parcels whose latest permit of any type prints a name. On this export that count is 113,046. `with_last_roof_contractor` is parcels whose latest roof-work permit prints a name, from the closed and new-construction layers. On this export that count is 2,444. The open-permit layer has no contractor field. Two of the 117 open roof permits print a name.

Filebase publication of the query JSON, packed with `ipfs-car@3`, is `pipeline/publish_ipfs.py`. That CAR is the query snapshot. It is not an `elephant-cli export-tables` archive.

Ask on the query page and the CRM retrieves matching rows in the browser, then calls OpenAI `gpt-5-nano` through `/api/ask`. Google AI `gemini-2.5-flash-lite` is the cheaper model, and that key answered HTTP 402 because its prepayment credits are depleted. The OpenAI key is the next account that returned text. The key stays in the server environment. Chunking and retrieval do not use a key.

## Demo

A narrated product walkthrough is still a recording of these two hosted pages. Arcade, Descript, or Guidde can capture the pages and narrate the script in the README. A generated clip that does not drive those pages would not be this product.
