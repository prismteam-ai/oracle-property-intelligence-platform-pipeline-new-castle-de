const CITIES = {
  wilmington: [39.739072, -75.539787],
  newark: [39.683723, -75.749657],
  hockessin: [39.790669, -75.704647],
  middletown: [39.449556, -75.716321],
  bear: [39.629279, -75.658261],
  "new castle": [39.662039, -75.566313],
};

const BASIS = {
  "structure.year_built": "from year built",
  latest_roof_permit: "from last roof permit",
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
  manifest_cid: "bafybeifxiwxgcuetw3ahmpeq6nf5gklyl77m7q2xnyae3uu5cddsi4sedm",
  delta_cid: "bafybeic7urhozu6bxwm5zfgjhyw7rxfhnvsg3gh674clj3w7vhtk5vmtqm",
};

const IPFS = {
  "summary.json": "https://ipfs.filebase.io/ipfs/bafybeihtldyxm2remb7boip3e7w6tvfllpxg2nazuectwhyyxzefzcjibe",
  "leads.json": "https://ipfs.filebase.io/ipfs/bafybeihkejjprhb44k2432wohtkyveuslwpbc6yh7yrzooipeyil4wyqyy",
  "permits.json": "https://ipfs.filebase.io/ipfs/bafybeih5jfqg6a4llcjvjzxpdzd2pkev6afvfxpfgl6o2hh22qk474ibt4",
  "manifest.json": `https://ipfs.filebase.io/ipfs/${PUBLISHED.manifest_cid}`,
};

// Every count on the page comes from the published CIDs, not from a bundled copy.
async function loadJson(name) {
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
    ["Any-permit contractor", s.with_any_permit_contractor],
    ["Last roof contractor", s.with_last_roof_contractor],
  ];
  const prior = (pub?.manifest?.prior_cids || []).join(", ") || "none";
  const car = pub?.manifest?.car?.cid || "not in this copy";
  const manifest = pub
    ? `<p>Manifest CID <code>${pub.manifest_cid}</code></p><p>Prior manifest <code>${prior}</code></p><p>CAR <code>${car}</code></p>`
    : "<p>IPFS manifest is not in this copy yet.</p>";
  const checks = (pub?.gateway_checks || [])
    .map((check) => `<li>${check.match ? "match" : "no match"} ${check.status ?? ""} ${check.url}</li>`)
    .join("");
  document.getElementById("summary").innerHTML = `
    <div class="cards">${cards.map(([label, value]) => `<div class="card"><span>${label}</span><strong>${Number(value).toLocaleString()}</strong></div>`).join("")}</div>
    <div class="note">
      <p>The hosted search set is the ${state.leads.length.toLocaleString()} parcels with a roof age of at least 15 years or an open roof permit. The full parcel table is ${Number(s.parcels).toLocaleString()} rows in DuckDB.</p>
      ${manifest}
      ${checks ? `<details class="sources"><summary>Gateway readback checks</summary><ul>${checks}</ul></details>` : ""}
      <p>Year built is filled for ${Number(s.with_year_built).toLocaleString()} parcels. Roof age otherwise uses the latest roof-permit year. Sale history was not submitted because www3.newcastlede.gov/robots.txt disallows /parcel/Details/. BBB ratings were not submitted because www.bbb.org/robots.txt disallows category pages. ${escapeHtml(s.contractor_count_note || "")} This run's summary matched on ipfs.filebase.io. The manifest matched on ipfs.filebase.io and 4everland.io. The CAR matched on ipfs.filebase.io and gateway.pinata.cloud. ipfs.io and dweb.link returned 429.</p>
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

function ageCell(lead) {
  if (lead.roof_age_years == null) return `<span class="none">Unknown</span>`;
  return `<span class="age${lead.roof_age_years >= 30 ? " old" : ""}">${lead.roof_age_years}</span><span class="sub">${BASIS[lead.roof_age_basis] ?? ""}</span>`;
}

function contractorCell(name) {
  return name ? `<span class="who">${escapeHtml(name)}</span>` : `<span class="none">Not printed on permit</span>`;
}

function lastRoofCell(lead) {
  if (!lead?.last_roof_contractor_name) return `<span class="none">None on a closed roof permit</span>`;
  const year = String(lead.last_roof_contractor_issued_at || "").slice(0, 4);
  return `<span class="who">${escapeHtml(lead.last_roof_contractor_name)}</span><span class="sub">Closed roof permit${year ? ` · ${year}` : ""}</span>`;
}

function rowHtml(lead) {
  const permit = state.permits.find((item) => item.prclid === lead.prclid);
  return `<tr>
    <td><span class="addr">${escapeHtml(lead.address.replace(/\s+/g, " "))}</span><span class="sub">${escapeHtml(lead.city)} · ${lead.distance_miles.toFixed(2)} mi · parcel ${lead.prclid}</span></td>
    <td>${ageCell(lead)}</td>
    <td>${permit ? `<span class="since">Open ${permit.days_open?.toLocaleString() ?? "?"} days</span>` : `<span class="none">None open</span>`}</td>
    <td>${permit ? contractorCell(permit.contractor_name) : `<span class="none">—</span>`}</td>
    <td>${lastRoofCell(lead)}</td>
    <td><span class="none" title="bbb.org/robots.txt disallows category pages">Not loaded</span></td>
  </tr>`;
}

function draw(leads, lat, lon, radius) {
  if (!state.map) {
    state.map = L.map("map").setView([lat, lon], 12);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
      attribution: "Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors", maxZoom: 16,
    }).addTo(state.map);
  }
  if (state.layer) state.layer.remove();
  state.layer = L.layerGroup().addTo(state.map);
  L.circle([lat, lon], { radius: radius * 1609.344, color: "#0b57d0", weight: 1, fillColor: "#d3e3fd", fillOpacity: 0.25 }).addTo(state.layer);
  leads.slice(0, 200).forEach((lead) => {
    L.circleMarker([lead.lat, lead.lon], { radius: 4, color: "#9b72cb", weight: 1, fillOpacity: 0.8 })
      .bindPopup(`${lead.address}, ${lead.city}<br>Roof age ${lead.roof_age_years ?? "unknown"} (${lead.roof_age_basis ?? "no basis"})`)
      .addTo(state.layer);
  });
  state.map.setView([lat, lon], 12);
}

function renderSearch(leads) {
  document.getElementById("search-count").textContent = `${leads.length.toLocaleString()} properties · showing ${Math.min(50, leads.length)} closest`;
  document.getElementById("search-results").innerHTML = `<table>
    <thead><tr><th>Property</th><th>Roof age</th><th>Open roof permit</th><th>Contractor on open permit</th><th>Last roof contractor</th><th>BBB</th></tr></thead>
    <tbody>${leads.slice(0, 50).map(rowHtml).join("")}</tbody>
  </table>`;
}

function renderPermits() {
  const rows = state.permits.slice(0, 40).map((permit) => {
    const lead = state.leads.find((item) => item.prclid === permit.prclid);
    return `<tr>
      <td><span class="since">${permit.days_open?.toLocaleString() ?? "?"} days</span></td>
      <td><span class="addr">${lead ? escapeHtml(lead.address.replace(/\s+/g, " ")) : permit.prclid}</span><span class="sub">${lead ? escapeHtml(lead.city) : ""}</span></td>
      <td>${escapeHtml(permit.apno)}<span class="sub">${escapeHtml(permit.aptype ?? "")} · issued ${escapeHtml((permit.issued_at ?? "").slice(0, 10))}</span></td>
      <td>${escapeHtml(permit.comments ?? "")}</td>
      <td>${contractorCell(permit.contractor_name)}</td>
      <td>${lastRoofCell(lead)}</td>
      <td><span class="none" title="bbb.org/robots.txt disallows category pages">Not loaded</span></td>
    </tr>`;
  }).join("");
  document.getElementById("permits").innerHTML = `<p>${state.permits.length} open roof-permit rows, longest open first. ${state.summary.open_roof_permit.toLocaleString()} parcels have at least one. HVAC rooftop units, plumbing, and porch, solar, and waterproofing work are left out. A year-built age is the building year, not a measured roof replacement.</p>
    <table><thead><tr><th>Open</th><th>Property</th><th>Permit</th><th>Work</th><th>Contractor on open permit</th><th>Last roof contractor</th><th>BBB</th></tr></thead><tbody>${rows}</tbody></table>`;
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

const CITATIONS = [
  "BBB ratings were not submitted. https://www.bbb.org/robots.txt disallows /*? and /business-reviews/*, so no BBB harvest was submitted.",
  "Delaware contractor business licenses were read through SODA dataset 5zy2-grhr. Electrical, plumbing, and HVACR licenses were read through SODA dataset pjnv-eaih. The lexicon manifest has no license class, so those rows are not matched to a permit name.",
  "Sale history is not available. www3.newcastlede.gov/robots.txt disallows /parcel/Details/, so a 10-year ownership question cannot be answered.",
  "The open-permit layer has no contractor field. last_roof_contractor_name is the name on the latest closed or new-construction roof permit.",
];

document.getElementById("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.getElementById("question").value;
  const result = answer(question);
  const rows = result.leads.slice(0, 8).map((lead) => {
    const permit = state.permits.find((item) => item.prclid === lead.prclid);
    return {
      source: "published-lead",
      prclid: lead.prclid,
      address: lead.address,
      city: lead.city,
      distance_miles: Number(lead.distance_miles.toFixed(2)),
      roof_age_years: lead.roof_age_years,
      roof_age_basis: lead.roof_age_basis,
      permit: permit
        ? { apno: permit.apno, days_open: permit.days_open, contractor_name: permit.contractor_name, aptype: permit.aptype }
        : null,
      last_roof_contractor_name: lead.last_roof_contractor_name,
      last_roof_contractor_basis: lead.last_roof_contractor_name ? "closed or new-construction roof permit, not the open permit" : null,
    };
  });
  const parcels = rows.map((lead) => `<li>${lead.address}, ${lead.city} · parcel ${lead.prclid}</li>`).join("");
  const sources = (open) => `<details class="sources"${open ? " open" : ""}><summary>Sources and limits</summary><ul>${parcels}</ul>${CITATIONS.map((text) => `<p>${text}</p>`).join("")}</details>`;
  const box = document.getElementById("answer");
  const send = document.querySelector("#ask-form .send");
  send.disabled = true;
  box.innerHTML = `<div class="response thinking"><span class="spark"></span><div><p class="response-body">Reading ${result.leads.length} matching parcels within ${result.radius} miles of ${result.city}…</p></div></div>`;
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        evidence: [
          { source: "retrieval", city: result.city, radius_miles: result.radius, match_count: result.leads.length },
          ...rows,
          ...CITATIONS.map((text) => ({ source: "citation", text })),
        ],
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The model request failed.");
    const text = escapeHtml(payload.answer).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    box.innerHTML = `<div class="response"><span class="spark"></span><div>
      <p class="response-body">${text}</p>
      <p class="response-meta">Answered from ${result.leads.length} published parcels within ${result.radius} miles of ${result.city} · ${payload.model}</p>
      ${sources(false)}</div></div>`;
  } catch (error) {
    box.innerHTML = `<div class="response"><span class="spark"></span><div>
      <p class="response-body">The model call failed (${escapeHtml(error.message)}). The parcels it would have used are listed below.</p>
      ${sources(true)}</div></div>`;
  } finally {
    send.disabled = false;
  }
});

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

document.querySelectorAll("[data-prompt]").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.getElementById("question").value = chip.dataset.prompt;
    document.getElementById("ask-form").requestSubmit();
  });
});

function focusAsk() {
  show("ask");
  const box = document.getElementById("question");
  box.focus();
  box.select();
}
document.getElementById("open-ask").addEventListener("click", focusAsk);
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    focusAsk();
  }
});

document.getElementById("question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.getElementById("ask-form").requestSubmit();
  }
});

Promise.all([loadJson("summary.json"), loadJson("leads.json"), loadJson("permits.json"), loadJson("manifest.json").catch(() => null)])
  .then(([summary, leads, permits, manifest]) => {
    state.summary = summary;
    state.leads = leads;
    state.permits = permits;
    state.published = { manifest_cid: PUBLISHED.manifest_cid, delta_cid: PUBLISHED.delta_cid, manifest, gateway_checks: [] };
    document.getElementById("status").textContent = `${leads.length.toLocaleString()} lead parcels · published on IPFS`;
    renderSummary();
    renderPermits();
    const initial = search(39.739072, -75.539787, 5, 15, false);
    draw(initial, 39.739072, -75.539787, 5);
    renderSearch(initial);
  })
  .catch((error) => {
    document.getElementById("status").textContent = `Could not load data: ${error.message}`;
  });

const appsButton = document.querySelector(".apps-button");
const appsMenu = document.getElementById("apps-menu");
appsMenu.querySelectorAll("a").forEach((link) => {
  if (link.dataset.app === document.body.dataset.app) link.setAttribute("aria-current", "page");
});
appsButton.addEventListener("click", (event) => {
  event.stopPropagation();
  const open = appsMenu.hidden;
  appsMenu.hidden = !open;
  appsButton.setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".apps")) {
    appsMenu.hidden = true;
    appsButton.setAttribute("aria-expanded", "false");
  }
});
