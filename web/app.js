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

const PAGE = 200;
const state = {
  leads: [], byParcel: new Map(), openPermits: [], summary: null, published: null, map: null, layer: null,
  results: [], resultLimit: PAGE, permitLimit: PAGE, permitRoofOnly: false, runId: 0,
};

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
  manifest_cid: "bafybeigzaxey4agd4ble5b555vrcckx7hh3ny4zuiiizijp2r3xpkklshm",
  delta_cid: "bafybeicpymmxwfvseccrt7uy3ebujia4c77joz6edmgs5bcmekfk5ikclu",
};

const IPFS = {
  "summary.json": "https://ipfs.filebase.io/ipfs/bafybeiapsu2hrqxkeb3igyeyfgyeddzlds422mfpko6yyfq5k66luc7chm",
  "leads.json": "https://ipfs.filebase.io/ipfs/bafybeidafqokwa2xgpnsxps4pty72gidlimxbfwe4ehzajodpeg24prw4i",
  "permits.json": "https://ipfs.filebase.io/ipfs/bafybeidbqpmxt4h7mg4wdgyzipjnkllollx63gfhtta7utmn7wwurs2wmu",
  "open_permits.json": "https://ipfs.filebase.io/ipfs/bafybeieqlv2hj6xxg3bxhgbjfkdgywhe3m4guyp4upfbybaaomg5gi7ngm",
  "tiles_index.json": GATEWAY + TILE_INDEX_CID,
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
      <p>Every one of the ${tileTotals().parcels.toLocaleString()} parcels with coordinates is published, and every permit row. The parcel table has ${Number(s.parcels).toLocaleString()} rows. The page loads the ${Object.keys(tileIndex.tiles).length} map tiles around a search instead of the whole county at once.</p>
      <p>Files: ${["summary.json", "leads.json", "permits.json", "open_permits.json", "tiles_index.json"].map((name) => `<a href="${IPFS[name]}" target="_blank" rel="noopener">${name}</a>`).join(" · ")}</p>
      ${manifest}
      ${checks ? `<details class="sources"><summary>Gateway readback checks</summary><ul>${checks}</ul></details>` : ""}
      <p>Year built is filled for ${Number(s.with_year_built).toLocaleString()} parcels. Roof age otherwise uses the latest roof-permit year. Sale history was not submitted because www3.newcastlede.gov/robots.txt disallows /parcel/Details/. BBB ratings were not submitted because www.bbb.org/robots.txt disallows category pages. Any-permit contractor is ${Number(s.with_any_permit_contractor).toLocaleString()} parcels whose latest permit of any type prints a name. Last roof contractor is ${Number(s.with_last_roof_contractor).toLocaleString()} parcels whose latest roof-work permit prints a name, from the closed and new-construction layers. The open-permit layer prints a contractor on only a few rows, so neither count is an open-permit contractor. This run's CAR, summary, and manifest matched on ipfs.filebase.io. ipfs.io, dweb.link, and gateway.pinata.cloud returned 429, so they are not counted as checks.</p>
    </div>`;
}

function search(lat, lon, radius, minAge, openOnly, leads = state.leads) {
  return leads
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

function openPermitFor(prclid, byParcel = state.byParcel) {
  const open = (byParcel.get(prclid) || []).filter((item) => item.permit_status === "open");
  return open.find((item) => item.is_roof) || open[0];
}

function rowHtml(lead) {
  const permit = openPermitFor(lead.prclid);
  return `<tr>
    <td><span class="addr">${escapeHtml(lead.address)}</span><span class="sub">${escapeHtml(lead.city)} · ${lead.distance_miles.toFixed(2)} mi · parcel ${lead.prclid}</span></td>
    <td>${ageCell(lead)}</td>
    <td>${permit ? `<span class="since">Open ${permit.days_open?.toLocaleString() ?? "?"} days</span><span class="sub">${permit.is_roof ? "Roof work" : escapeHtml(permit.aptype || "Other work")}${lead.open_permit_count > 1 ? ` · ${lead.open_permit_count} open` : ""}</span>` : `<span class="none">None open</span>`}</td>
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
  const circle = L.circle([lat, lon], { radius: radius * 1609.344, color: "#0b57d0", weight: 1, fillColor: "#d3e3fd", fillOpacity: 0.25 }).addTo(state.layer);
  const canvas = L.canvas({ padding: 0.5 });
  leads.forEach((lead) => {
    L.circleMarker([lead.lat, lead.lon], { renderer: canvas, radius: 4, color: "#9b72cb", weight: 1, fillOpacity: 0.8 })
      .bindPopup(`${lead.address}, ${lead.city}<br>Roof age ${lead.roof_age_years ?? "unknown"} (${lead.roof_age_basis ?? "no basis"})`)
      .addTo(state.layer);
  });
  state.map.fitBounds(circle.getBounds(), { padding: [24, 24], maxZoom: 14 });
}

function moreButton(shown, total, name) {
  return shown < total
    ? `<button type="button" class="btn tonal more" data-more="${name}">Show ${Math.min(PAGE, total - shown).toLocaleString()} more</button>`
    : "";
}

function renderSearch() {
  const leads = state.results;
  const shown = Math.min(state.resultLimit, leads.length);
  document.getElementById("search-count").textContent = `${leads.length.toLocaleString()} properties, closest first · showing ${shown.toLocaleString()}`;
  document.getElementById("search-results").innerHTML = leads.length
    ? `<table>
    <thead><tr><th>Property</th><th>Roof age</th><th>Open permit</th><th>Contractor on open permit</th><th>Last roof contractor</th><th>BBB</th></tr></thead>
    <tbody>${leads.slice(0, shown).map(rowHtml).join("")}</tbody>
  </table>${moreButton(shown, leads.length, "search")}`
    : `<p class="empty">No properties match. Try a larger radius or a lower roof age.</p>`;
}

function renderPermits() {
  const open = state.permitRoofOnly ? state.openPermits.filter((permit) => permit.is_roof) : state.openPermits;
  const shown = Math.min(state.permitLimit, open.length);
  const rows = open.slice(0, shown).map((permit) => `<tr>
      <td><span class="since">${permit.days_open?.toLocaleString() ?? "?"} days</span></td>
      <td><span class="addr">${escapeHtml(permit.address ?? permit.prclid)}</span><span class="sub">${escapeHtml(permit.city ?? "")} · parcel ${escapeHtml(permit.prclid)}</span></td>
      <td>${escapeHtml(permit.apno)}<span class="sub">${escapeHtml(permit.aptype ?? "")} · issued ${escapeHtml(permit.issued_on ?? "date not published")}</span></td>
      <td>${permit.is_roof ? `<span class="since">Roof</span> ` : ""}${escapeHtml(permit.comments ?? "")}</td>
      <td>${contractorCell(permit.contractor_name)}</td>
      <td><span class="none" title="bbb.org/robots.txt disallows category pages">Not loaded</span></td>
    </tr>`).join("");
  const roof = state.openPermits.filter((permit) => permit.is_roof).length;
  document.getElementById("permits").innerHTML = `<div class="toolbar"><p>${open.length.toLocaleString()} ${state.permitRoofOnly ? "open roof permits" : `open permits in the county, ${roof.toLocaleString()} of them for roof work`}, longest open first · showing ${shown.toLocaleString()}. Every permit row is in <a href="${IPFS["permits.json"]}" target="_blank" rel="noopener">permits.json</a>.</p>
    <button type="button" class="btn tonal" data-roof-toggle>${state.permitRoofOnly ? "Show all open permits" : "Roof work only"}</button></div>
    <table><thead><tr><th>Open</th><th>Property</th><th>Permit</th><th>Work</th><th>Contractor on open permit</th><th>BBB</th></tr></thead><tbody>${rows}</tbody></table>${moreButton(shown, open.length, "permits")}`;
}

async function answer(question) {
  const text = question.toLowerCase();
  const city = Object.keys(CITIES).find((name) => text.includes(name)) || "wilmington";
  const [lat, lon] = CITIES[city];
  const radius = Number((text.match(/(\d+(?:\.\d+)?)\s*mile/) || [0, 5])[1]);
  const age = Number((text.match(/older than\s+(\d+)/) || text.match(/(\d+)\s*years/) || [0, 15])[1]);
  const openOnly = text.includes("permit") || text.includes("contractor");
  const area = await loadArea(lat, lon, radius);
  const leads = search(lat, lon, radius, openOnly ? null : age, openOnly, area.leads);
  const shown = openOnly ? leads.sort((a, b) => (b.oldest_open_days || 0) - (a.oldest_open_days || 0)) : leads;
  return { city, lat, lon, radius, age, openOnly, leads: shown, byParcel: area.byParcel };
}

async function runSearch(lat, lon, radius, minAge, openOnly) {
  const status = document.getElementById("search-count");
  if (![lat, lon, radius].every(Number.isFinite) || radius <= 0) {
    status.textContent = "Enter a latitude, longitude, and a radius above 0.";
    return;
  }
  const id = ++state.runId;
  const results = document.getElementById("search-results");
  results.classList.add("busy");
  status.textContent = `Loading parcels within ${radius} miles…`;
  try {
    const area = await loadArea(lat, lon, radius, (done, total) => {
      if (id === state.runId) status.textContent = `Loading map tiles ${done} of ${total}…`;
    });
    if (id !== state.runId) return;
    state.leads = area.leads;
    state.byParcel = area.byParcel;
  } catch (error) {
    if (id === state.runId) status.textContent = `Published data did not load (${error.message}).`;
    return;
  } finally {
    results.classList.remove("busy");
  }
  state.results = search(lat, lon, radius, openOnly ? null : minAge, openOnly);
  state.resultLimit = PAGE;
  draw(state.results, lat, lon, radius);
  renderSearch();
}

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-roof-toggle]")) {
    state.permitRoofOnly = !state.permitRoofOnly;
    state.permitLimit = PAGE;
    renderPermits();
    return;
  }
  const more = event.target.closest("[data-more]");
  if (!more) return;
  if (more.dataset.more === "search") {
    state.resultLimit += PAGE;
    renderSearch();
  } else {
    state.permitLimit += PAGE;
    renderPermits();
  }
});

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
  runSearch(lat, lon, radius, minAge, openOnly);
});

const CITATIONS = [
  "BBB ratings were not submitted. https://www.bbb.org/robots.txt disallows /*? and /business-reviews/*, so no BBB harvest was submitted.",
  "Delaware contractor business licenses were read through SODA dataset 5zy2-grhr. Electrical, plumbing, and HVACR licenses were read through SODA dataset pjnv-eaih. The lexicon manifest has no license class, so those rows are not matched to a permit name.",
  "Sale history is not available. www3.newcastlede.gov/robots.txt disallows /parcel/Details/, so a 10-year ownership question cannot be answered.",
  "The open-permit layer prints a contractor on only a few rows. last_roof_contractor_name is the name on the latest closed or new-construction roof permit.",
];

document.getElementById("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.getElementById("question").value.trim();
  if (!question) return;
  const box = document.getElementById("answer");
  const send = document.querySelector("#ask-form .send");
  send.disabled = true;
  box.innerHTML = `<div class="response thinking"><span class="spark"></span><div><p class="response-body">Loading published parcels for this question…</p></div></div>`;
  let result;
  try {
    result = await answer(question);
  } catch (error) {
    box.innerHTML = `<div class="response"><span class="spark"></span><div><p class="response-body">Published data did not load (${escapeHtml(error.message)}).</p></div></div>`;
    send.disabled = false;
    return;
  }
  const rows = result.leads.slice(0, 8).map((lead) => {
    const permit = openPermitFor(lead.prclid, result.byParcel);
    return {
      source: "published-lead",
      prclid: lead.prclid,
      address: lead.address,
      city: lead.city,
      distance_miles: Number(lead.distance_miles.toFixed(2)),
      roof_age_years: lead.roof_age_years,
      roof_age_basis: lead.roof_age_basis,
      permit: permit
        ? { apno: permit.apno, issued_on: permit.issued_on, days_open: permit.days_open, is_roof: permit.is_roof, contractor_name: permit.contractor_name, aptype: permit.aptype, comments: permit.comments }
        : null,
      open_permit_count: lead.open_permit_count,
      last_roof_contractor_name: lead.last_roof_contractor_name,
      last_roof_contractor_basis: lead.last_roof_contractor_name ? "closed or new-construction roof permit, not the open permit" : null,
    };
  });
  const parcels = rows.map((lead) => `<li>${lead.address}, ${lead.city} · parcel ${lead.prclid}</li>`).join("");
  const sources = (open) => `<details class="sources"${open ? " open" : ""}><summary>Sources and limits</summary><ul>${parcels}</ul>${CITATIONS.map((text) => `<p>${text}</p>`).join("")}</details>`;
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

Promise.all([loadJson("summary.json"), loadTileIndex(), loadJson("manifest.json").catch(() => null)])
  .then(([summary, _index, manifest]) => {
    state.summary = summary;
    state.published = { manifest_cid: PUBLISHED.manifest_cid, delta_cid: PUBLISHED.delta_cid, manifest, gateway_checks: [] };
    const totals = tileTotals();
    document.getElementById("status").textContent = `${totals.parcels.toLocaleString()} parcels · published on IPFS`;
    renderSummary();
    runSearch(39.739072, -75.539787, 5, 15, false);
    return loadJson("open_permits.json").then((permits) => {
      state.openPermits = [...permits].sort((a, b) => (b.days_open ?? -1) - (a.days_open ?? -1));
      renderPermits();
    });
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
