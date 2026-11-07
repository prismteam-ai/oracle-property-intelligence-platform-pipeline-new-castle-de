/** New Castle County permit sources for the kit arcgis-feature-service adapter.
 * Every layer is the same MapServer. Each layer is an adapter route, not a new client.
 * Open permits (layer 0) has no contractor name and no close date.
 * Contractor text is on the manufactured and new-construction layers.
 * Hold layers have no application number. The adapter uses OBJECTID as the stable key.
 */
const LAYER_ROOT =
  "https://gis.nccde.org/agsserver/rest/services/CustomMaps/Permits/MapServer";

function layerUrl(id) {
  return `${LAYER_ROOT}/${id}`;
}

function route(key, layerId, sourceSystem, parcelField, fieldMap, fingerprint) {
  const url = layerUrl(layerId);
  return {
    key,
    adapterKey: "arcgis-feature-service",
    adapterConfig: {
      sourceSystem,
      baseUrl: url,
      layerUrl: url,
      objectIdField: "OBJECTID",
      parcelField,
      fieldMap,
      bulkPageSize: 1000,
      bulkConcurrency: 1,
      maximumResultRecords: 2000,
      minimumDelayMs: 500,
      detailFingerprintVersion: fingerprint,
    },
  };
}

function source(key, layerId, routeKey, boundary, contractorDetailCapability) {
  return {
    key,
    url: layerUrl(layerId),
    role: "historical-search",
    access: "public",
    historicalBoundary: boundary,
    contractorDetailCapability,
    adapterKey: "arcgis-feature-service",
    adapterRouteKey: routeKey,
    enumerationStatus: "bounded-only",
    anonymousAccess: true,
  };
}

const openRoute = route(
  "open-permits",
  0,
  "new_castle_county_permits",
  "PRCLID",
  {
    permitNumber: "APNO",
    permitType: "APTYPE",
    description: "COMMENTS",
    parcelIdentifier: "PRCLID",
    issuedAt: "ISSDTTM",
  },
  "ncc-open-permits-v1",
);

export const newCastlePermitProfileInput = {
  countyKey: "new-castle",
  countyName: "New Castle",
  stateCode: "DE",
  countyFips: "10003",
  parcelIdentifierPattern: "^.+$",
  parcelIdentifierFormat: "source-specific",
  defaultRoutingPolicy: "fallback",
  publication: {
    bucket: "new-castle-county",
    propertyQueryTableIpnsLabel: "new-castle-property",
    permitTableIpnsLabel: "new-castle-permits",
    coverageIpnsLabel: "new-castle-coverage",
  },
  jurisdictions: [
    {
      key: "new-castle-county",
      name: "New Castle County",
      routingCities: [
        "WILMINGTON",
        "NEWARK",
        "NEW CASTLE",
        "BEAR",
        "MIDDLETOWN",
        "HOCKESSIN",
      ],
      defaultForUnmatchedCity: true,
      status: "supported",
      historicalRecords: true,
      adapterKey: openRoute.adapterKey,
      adapterConfig: openRoute.adapterConfig,
      adapterRoutes: [
        route(
          "expired-permits",
          2,
          "new_castle_expired_permits",
          "PRCLKY",
          {
            permitNumber: "APNO",
            permitType: "APTYPE",
            parcelIdentifier: "PRCLKY",
            issuedAt: "ISSDTTM",
            description: "DESCRIPTION",
          },
          "ncc-expired-permits-v1",
        ),
        route(
          "expired-manufactured",
          3,
          "new_castle_expired_manufactured_permits",
          "PRCLID",
          {
            permitNumber: "APNO",
            permitType: "APTYPE",
            description: "COMMENTS",
            address: "ADDRESS",
            parcelIdentifier: "PRCLID",
            issuedAt: "ISSDTTM",
            contractorName: "CONTNAME",
            contractorLicense: "CONTID",
          },
          "ncc-expired-manufactured-v1",
        ),
        route(
          "new-construction",
          4,
          "new_castle_new_construction_permits",
          "PRCLID",
          {
            permitNumber: "APNO",
            permitType: "APTYPE",
            description: "COMMENTS",
            parcelIdentifier: "PRCLID",
            issuedAt: "ISSDTTM",
            contractorName: "CONTRACTORNAME",
            contractorLicense: "CONTID",
          },
          "ncc-new-construction-v1",
        ),
        route(
          "hold-permit",
          6,
          "new_castle_hold_permit_permits",
          "PRCLKY",
          {
            status: "HOLDPRM",
            description: "DESCRIPTION",
            parcelIdentifier: "PRCLKY",
          },
          "ncc-hold-permit-v1",
        ),
        route(
          "hold-engineering",
          7,
          "new_castle_hold_engineering_permits",
          "PRCLKY",
          {
            status: "ENGREL",
            description: "DESCRIPTION",
            parcelIdentifier: "PRCLKY",
          },
          "ncc-hold-engineering-v1",
        ),
        route(
          "hold-historical",
          8,
          "new_castle_hold_historical_permits",
          "PRCLKY",
          {
            status: "HISTFLAG",
            description: "DESCRIPTION",
            parcelIdentifier: "PRCLKY",
          },
          "ncc-hold-historical-v1",
        ),
        route(
          "hold-sewer",
          9,
          "new_castle_hold_sewer_permits",
          "PRCLKY",
          {
            status: "SEWERREL",
            description: "DESCRIPTION",
            parcelIdentifier: "PRCLKY",
          },
          "ncc-hold-sewer-v1",
        ),
      ],
      parcelSearchFormat: "source-specific",
      sources: [
        source(
          "open-permits",
          0,
          "primary",
          "County open-permits feature layer. gis.nccde.org publishes no robots.txt. This layer has no close date and no contractor name.",
          "not-exposed",
        ),
        source(
          "expired-permits",
          2,
          "expired-permits",
          "Expired permits layer. Parcel key on this layer is PRCLKY. No contractor name and no close date.",
          "not-exposed",
        ),
        source(
          "expired-manufactured",
          3,
          "expired-manufactured",
          "Expired manufactured permits. Contractor text is CONTNAME. No close date.",
          "public-detail",
        ),
        source(
          "new-construction",
          4,
          "new-construction",
          "New construction permits. Contractor text is CONTRACTORNAME. No close date.",
          "public-detail",
        ),
        source(
          "hold-permit",
          6,
          "hold-permit",
          "Hold-permit checkbox layer. No application number. The stable key is OBJECTID.",
          "not-exposed",
        ),
        source(
          "hold-engineering",
          7,
          "hold-engineering",
          "Hold for engineering review. No application number. The stable key is OBJECTID.",
          "not-exposed",
        ),
        source(
          "hold-historical",
          8,
          "hold-historical",
          "Hold for historical review. No application number. The stable key is OBJECTID.",
          "not-exposed",
        ),
        source(
          "hold-sewer",
          9,
          "hold-sewer",
          "Hold for sewer capacity. No application number. The stable key is OBJECTID.",
          "not-exposed",
        ),
      ],
      recordsRequest: null,
    },
  ],
};
