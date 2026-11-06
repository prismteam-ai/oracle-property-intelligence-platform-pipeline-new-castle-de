const CITIES = {
  wilmington: [39.739072, -75.539787],
  newark: [39.683723, -75.749657],
  hockessin: [39.790669, -75.704647],
  middletown: [39.449556, -75.716321],
  bear: [39.629279, -75.658261],
  "new castle": [39.662039, -75.566313],
};

const state = { leads: [], permits: [], summary: null, published: null, map: null, layer: null };

function miles(lat1, lon1, lat2, lon2) {
  const r = 3958.7613;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dlat = ((lat2 - lat1) * Math.PI) / 180;
  const dlon = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dlat / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dlon / 2) ** 2;
  return 2 * r * Math.asin(Math.min(1, Math.sqrt(a)));
}

const PUBLISHED = {
  manifest_cid: "bafybeiapogy36guzgizt2teewa6ywddgtucu3vbdavpog4xum7qyg7rfom",
  delta_cid: "bafybeihf3sayrfzaebakgcw3wn3gckkl6fi4o3hr6asyh5sj7yrqjh3zmi",
};

const IPFS = {
  "summary.json": "https://ipfs.filebase.io/ipfs/bafybeiegnguttuuodmalnqat5nsqy5ikxxi5x5cxe2xb2l6pnvqxpgwniu",
  "leads.json": "https://ipfs.filebase.io/ipfs/bafybeif7pt7mppcl2vzfekhcmt3locjegapjwvpmjb4azl3mn5avzwdxky",
  "permits.json": "https://ipfs.filebase.io/ipfs/bafybeiarmwqsbi2z2hexbdtf7qq62scakz464uduyqv33im4cfegthapdi",
  "published.json": "https://ipfs.filebase.io/ipfs/bafybeiapogy36guzgizt2teewa6ywddgtucu3vbdavpog4xum7qyg7rfom",
};

async function loadJson(name) {
  const local = await fetch(`./data/${name}`).catch(() => null);
  if (local && local.ok) return local.json();
  const remote = await fetch(IPFS[name]);
  if (!remote.ok) throw new Error(name);
  return remote.json();
}

function show(id) {
  for (const section of document.querySelectorAll("main section")) section.hidden = section.id !== id;
  for (const button of document.querySelectorAll("nav button")) {
    button.classList.toggle("active", button.dataset.panel === id);
  }
  if (id === "search" && state.map) setTimeout(() => state.map.invalidateSize(), 0);
}

function renderSummary() {
  const s = state.summary;
  const pub = state.published;
  const cards = [
    ["Parcels", s.parcels],
    ["With coordinates", s.with_coordinates],
    ["Year built", s.with_year_built],
    ["Roofs 15+", s.roofs_15_or_older],
    ["Parcels with an open roof permit", s.open_roof_permit],
    ["Out-of-area owners", s.out_of_area_owner],
  ];
  const manifest = pub
    ? `<p>Manifest CID <code>${pub.manifest_cid}</code></p><p>Later publish CID <code>${pub.delta_cid}</code>. The first CID is unchanged.</p>`
    : "<p>IPFS manifest is not in this copy yet.</p>";
  const checks = (pub?.gateway_checks || [])
    .map((check) => `<li>${check.match ? "match" : "no match"} ${check.status ?? ""} ${check.url}</li>`)
    .join("");
  document.getElementById("summary").innerHTML = `
    <div class="cards">${cards.map(([label, value]) => `<div class="card"><span>${label}</span><strong>${Number(value).toLocaleString()}</strong></div>`).join("")}</div>
    <div class="note">
      <p>The hosted search set is the ${state.leads.length.toLocaleString()} parcels with a roof age of at least 15 years or an open roof permit. The full parcel table is ${Number(s.parcels).toLocaleString()} rows in DuckDB.</p>
      ${manifest}
      <ul>${checks}</ul>
      <p>Year built is filled for ${Number(s.with_year_built).toLocaleString()} parcels. Roof age otherwise uses the latest roof-permit year. Sale history and BBB ratings are not loaded. Contractor names are the text printed on the permit. ipfs.io and dweb.link returned a Cloudflare challenge from the publisher, so the digest check that succeeded is on ipfs.filebase.io.</p>
    </div>`;
}

function search(lat, lon, radius, minAge, openOnly) {
  return state.leads
    .map((lead) => ({ ...lead, distance_miles: miles(lat, lon, lead.lat, lead.lon) }))
    .filter((lead) => lead.distance_miles <= radius)
    .filter((lead) => minAge == null || (lead.roof_age_years != null && lead.roof_age_years >= minAge))
    .filter((lead) => !openOnly || lead.open_roof_permit_count > 0)
    .sort((a, b) => a.distance_miles - b.distance_miles);
}

function rowHtml(lead) {
  const permit = state.permits.find((item) => item.prclid === lead.prclid);
  return `<tr>
    <td>${lead.distance_miles.toFixed(2)}</td>
    <td>${lead.address}<br>${lead.city}</td>
    <td>${lead.roof_age_years ?? "—"}<br><span>${lead.roof_age_basis ?? ""}</span></td>
    <td>${lead.open_roof_permit_count}</td>
    <td>${permit ? `${permit.days_open ?? "—"} days` : "—"}</td>
    <td>${lead.contractor_name ?? permit?.contractor_name ?? "—"}<br><span>BBB not loaded</span></td>
  </tr>`;
}

function draw(leads, lat, lon, radius) {
  if (!state.map) {
    state.map = L.map("map").setView([lat, lon], 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap" }).addTo(state.map);
  }
  if (state.layer) state.layer.remove();
  state.layer = L.layerGroup().addTo(state.map);
  L.circle([lat, lon], { radius: radius * 1609.344, color: "#1c1915", weight: 1 }).addTo(state.layer);
  leads.slice(0, 200).forEach((lead) => {
    L.circleMarker([lead.lat, lead.lon], { radius: 4, color: "#8a3b12" })
      .bindPopup(`${lead.address}, ${lead.city}<br>Roof age ${lead.roof_age_years ?? "unknown"} (${lead.roof_age_basis ?? "no basis"})`)
      .addTo(state.layer);
  });
  state.map.setView([lat, lon], 12);
}

function renderSearch(leads) {
  document.getElementById("search-count").textContent = `${leads.length} properties`;
  document.getElementById("search-results").innerHTML = `<table>
    <thead><tr><th>Miles</th><th>Address</th><th>Roof age</th><th>Open roof</th><th>Days open</th><th>Contractor</th></tr></thead>
    <tbody>${leads.slice(0, 50).map(rowHtml).join("")}</tbody>
  </table>`;
}

function renderPermits() {
  const rows = state.permits.slice(0, 40).map((permit) => {
    const lead = state.leads.find((item) => item.prclid === permit.prclid);
    return `<tr>
      <td>${permit.days_open ?? "—"}</td>
      <td>${lead ? `${lead.address}, ${lead.city}` : permit.prclid}</td>
      <td>${permit.apno}<br>${permit.aptype ?? ""}</td>
      <td>${permit.issued_at ?? ""}</td>
      <td>${permit.comments ?? ""}</td>
      <td>${permit.contractor_name ?? "—"}<br><span>BBB not loaded</span></td>
    </tr>`;
  }).join("");
  document.getElementById("permits").innerHTML = `<p>${state.permits.length} open roof-permit rows, longest open first. ${state.summary.open_roof_permit.toLocaleString()} parcels in the owner seed have at least one. Five other permit ids are four condo units and one id the seed does not contain. HVAC rooftop units and plumbing permits are left out. A year-built age is the building year, not a measured roof replacement.</p>
    <table><thead><tr><th>Days</th><th>Address</th><th>Permit</th><th>Issued</th><th>Comment</th><th>Contractor</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function answer(question) {
  const text = question.toLowerCase();
  const city = Object.keys(CITIES).find((name) => text.includes(name)) || "wilmington";
  const [lat, lon] = CITIES[city];
  const radius = Number((text.match(/(\d+(?:\.\d+)?)\s*mile/) || [0, 5])[1]);
  const age = Number((text.match(/older than\s+(\d+)/) || text.match(/(\d+)\s*years/) || [0, 15])[1]);
  const openOnly = text.includes("permit") || text.includes("contractor");
  const leads = search(lat, lon, radius, openOnly ? null : age, openOnly);
  const shown = openOnly ? leads.sort((a, b) => (b.oldest_open_roof_days || 0) - (a.oldest_open_roof_days || 0)) : leads;
  return { city, lat, lon, radius, age, openOnly, leads: shown };
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => show(button.dataset.panel));
});

document.getElementById("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const lat = Number(document.getElementById("lat").value);
  const lon = Number(document.getElementById("lon").value);
  const radius = Number(document.getElementById("miles").value);
  const minAge = Number(document.getElementById("min-age").value);
  const openOnly = document.getElementById("open-only").checked;
  const leads = search(lat, lon, radius, openOnly ? null : minAge, openOnly);
  draw(leads, lat, lon, radius);
  renderSearch(leads);
});

document.getElementById("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const result = answer(document.getElementById("question").value);
  const sample = result.leads.slice(0, 8).map((lead) => {
    const permit = state.permits.find((item) => item.prclid === lead.prclid);
    return `<li>${lead.address}, ${lead.city} — ${lead.distance_miles.toFixed(2)} mi, roof age ${lead.roof_age_years ?? "unknown"} (${lead.roof_age_basis ?? "none"})${permit ? `, permit ${permit.apno}, ${permit.days_open} days, ${permit.contractor_name ?? "no contractor"}` : ""}</li>`;
  }).join("");
  document.getElementById("answer").innerHTML = `
    <div class="note">
      <p>I read the published lead set. Center is ${result.city} (${result.lat}, ${result.lon}), radius ${result.radius} miles. ${result.openOnly ? "Filtered to open roof permits, longest open first." : `Kept roofs aged at least ${result.age} years.`} ${result.leads.length} matches.</p>
      <ul>${sample}</ul>
      <p>BBB is not loaded. A contractor name is the text on the permit. Most parcels have no year built, so a blank roof age is missing data, not a new roof. Sale history is not available, so a 10-year ownership question cannot be answered.</p>
    </div>`;
});

Promise.all([loadJson("summary.json"), loadJson("leads.json"), loadJson("permits.json"), loadJson("published.json").catch(() => null)])
  .then(([summary, leads, permits, published]) => {
    state.summary = summary;
    state.leads = leads;
    state.permits = permits;
    state.published = published && published.manifest_cid ? published : PUBLISHED;
    document.getElementById("status").textContent = `${leads.length.toLocaleString()} lead parcels loaded.`;
    renderSummary();
    renderPermits();
    const initial = search(39.739072, -75.539787, 5, 15, false);
    draw(initial, 39.739072, -75.539787, 5);
    renderSearch(initial);
  })
  .catch((error) => {
    document.getElementById("status").textContent = `Could not load data: ${error.message}`;
  });
