const GATEWAY = "https://ipfs.filebase.io/ipfs/";
const TILE_INDEX_CID = "bafybeie6ofxkncvebzek4g6pxuvzzci7fi6qeltxmreknyicsvcikpcivq";
const tileCache = new Map();
let tileIndex = null;

async function loadTileIndex() {
  if (!tileIndex) {
    const response = await fetch(GATEWAY + TILE_INDEX_CID);
    if (!response.ok) throw new Error(`tile index ${response.status}`);
    tileIndex = await response.json();
  }
  return tileIndex;
}

function tileTotals() {
  return Object.values(tileIndex.tiles).reduce(
    (sum, tile) => ({ parcels: sum.parcels + tile.parcels, permits: sum.permits + tile.permits }),
    { parcels: 0, permits: 0 },
  );
}

function toObjects(columns, rows) {
  return rows.map((row) => Object.fromEntries(columns.map((column, i) => [column, row[i]])));
}

function loadTile(key) {
  if (!tileCache.has(key)) {
    const request = fetch(GATEWAY + tileIndex.tiles[key].cid)
      .then((response) => {
        if (!response.ok) throw new Error(`tile ${key} ${response.status}`);
        return response.json();
      })
      .then((tile) => ({
        leads: toObjects(tileIndex.lead_columns, tile.leads),
        permits: toObjects(tileIndex.permit_columns, tile.permits),
      }));
    request.catch(() => tileCache.delete(key));
    tileCache.set(key, request);
  }
  return tileCache.get(key);
}

function tilesNear(lat, lon, radius) {
  const size = tileIndex.tile_degrees;
  const dLat = radius / 69.0;
  const dLon = radius / (69.17 * Math.cos((lat * Math.PI) / 180));
  const keys = [];
  for (let a = Math.floor((lat - dLat) / size); a <= Math.floor((lat + dLat) / size); a++) {
    for (let b = Math.floor((lon - dLon) / size); b <= Math.floor((lon + dLon) / size); b++) {
      if (tileIndex.tiles[`${a}_${b}`]) keys.push(`${a}_${b}`);
    }
  }
  return keys;
}

async function loadArea(lat, lon, radius, onProgress) {
  await loadTileIndex();
  const keys = tilesNear(lat, lon, radius);
  let done = 0;
  const tiles = await Promise.all(keys.map((key) => loadTile(key).then((tile) => {
    done += 1;
    if (onProgress) onProgress(done, keys.length);
    return tile;
  })));
  const byParcel = new Map();
  const leads = [];
  for (const tile of tiles) {
    for (const lead of tile.leads) leads.push(lead);
    for (const permit of tile.permits) {
      if (!byParcel.has(permit.prclid)) byParcel.set(permit.prclid, []);
      byParcel.get(permit.prclid).push(permit);
    }
  }
  return { leads, byParcel, tiles: keys.length };
}
