/**
 * One kit permit read for New Castle, through the bundled arcgis adapter.
 *
 * The full Atlas ingest cannot finish: the live lexicon enum has no New Castle
 * county. This command still runs the kit adapter against the open-permit layer
 * and prints the count the adapter returns. Set ORACLE_RUNTIME to the
 * use-oracle runtime directory when it is not the default checkout.
 */
import { pathToFileURL } from "node:url";
import { newCastlePermitProfileInput } from "../counties/new-castle/permit-profile.mjs";

const runtime =
  process.env.ORACLE_RUNTIME ||
  "/Users/adamkalamchi/.cursor/plugins/cache/prismteam-ai-cursor-marketplace/soofi-xyz-team-kit/59238b63931be0c34b93c37f76ebfa0da98a44e4/skills/use-oracle/runtime";

const adapterUrl = pathToFileURL(`${runtime}/src/permits/adapters/arcgis-feature-service.mjs`);
const { createArcgisFeatureServiceAdapter } = await import(adapterUrl.href);

const jurisdiction = newCastlePermitProfileInput.jurisdictions[0];
const adapter = createArcgisFeatureServiceAdapter(jurisdiction, {
  countyKey: "new-castle",
  countyName: "New Castle",
  maxAttempts: 3,
});
const probe = await adapter.probe();
console.log(JSON.stringify({
  county: "new-castle",
  adapter: "arcgis-feature-service",
  layer: jurisdiction.adapterConfig.layerUrl,
  status: probe.status,
  open_permit_count: probe.count,
  atlas: "blocked: lexicon county_jurisdiction has no New Castle value",
}));
