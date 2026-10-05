(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const fmt = (n, d = 0) => Number(n).toLocaleString("en-IN", { maximumFractionDigits: d });

  // colours -------------------------------------------------------------------
  const SUN = ["#fff4c2", "#fbd25b", "#f5a31a", "#e0620f", "#b8350d"];
  const VIO = ["#efeaf8", "#c9bce8", "#9078cf", "#5e3da8", "#3b1f7a"];
  const BIVAR = [  // [need 0..2][solar 0..2]
    ["#eaeaf0", "#f8e2a0", "#f5b82e"],
    ["#c3b8e0", "#cfa97a", "#d58a1e"],
    ["#9a86d0", "#8a5a9a", "#6d1f6b"],
  ];
  const PROGRAM_COLORS = {
    "Owner rooftop subsidy": "#178f7e",
    "Landlord incentive / community solar": "#f2a71b",
    "Commercial PPA / RESCO": "#5c667a",
    "Public-building rooftop programme": "#3b1f7a",
  };
  const NO_PV = "#c4c9d4";

  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  function ramp(stops, t) {
    t = Math.min(1, Math.max(0, t));
    const x = t * (stops.length - 1), i = Math.min(Math.floor(x), stops.length - 2), f = x - i;
    const a = hex(stops[i]), b = hex(stops[i + 1]);
    return "#" + a.map((v, k) => Math.round(v + (b[k] - v) * f).toString(16).padStart(2, "0")).join("");
  }
  const norm = (v, lo, hi) => (hi > lo ? (v - lo) / (hi - lo) : 0);

  // state ------------------------------------------------------------------------
  const S = { zone: "class", roof: "irr", tracts: null, blds: null, meta: null,
              bLayer: null, tLayer: null, labLayer: null, byId: {}, tRange: {} };

  const map = L.map("map", { zoomControl: true, preferCanvas: false });
  // Base maps that need NO API key.
  const street = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19 }).addTo(map);
  const satellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics", maxZoom: 19 });
  L.control.layers({ "Street map": street, "Satellite": satellite }, null, { position: "topright" }).addTo(map);
  map.createPane("zones").style.zIndex = 350;
  map.createPane("roofs").style.zIndex = 450;
  map.createPane("labHighlight").style.zIndex = 550;

  // styles -----------------------------------------------------------------------
  function zoneColor(p) {
    const r = S.tRange;
    switch (S.zone) {
      case "class": return BIVAR[p.need_tercile][p.pot_tercile];
      case "need": return ramp(VIO, p.need_index);
      case "pot": return ramp(SUN, norm(p.solar_kwh_per_hh, r.potMin, r.potMax));
      case "income": return ramp(VIO, 1 - norm(p.median_income_inr, r.incMin, r.incMax));
    }
  }
  const zoneStyle = (f) => ({ pane: "zones", fillColor: zoneColor(f.properties), fillOpacity: 0.62,
                              color: "#ffffff", weight: 1.5 });

  function roofColor(p) {
    if (p.capacity_kwp <= 0) return NO_PV;
    const m = S.meta;
    switch (S.roof) {
      case "irr": return ramp(SUN, norm(p.mean_irr_kwh_m2, m.irr_min, m.irr_max));
      case "score": return ramp(VIO, p.priority_score);
      case "program": return PROGRAM_COLORS[p.program] || NO_PV;
    }
  }
  const roofStyle = (f) => ({ pane: "roofs", fillColor: roofColor(f.properties), fillOpacity: 0.95,
                              color: f.properties.is_priority ? "#1a0f3d" : "#ffffff",
                              weight: f.properties.is_priority ? 2.4 : 0.8 });

  // legends ----------------------------------------------------------------------
  function rampBar(stops, lo, hi) {
    return `<div class="ramp" style="background:linear-gradient(90deg,${stops.join(",")})"></div>
            <div class="ramp-labels"><span>${lo}</span><span>${hi}</span></div>`;
  }
  function zoneLegend() {
    const r = S.tRange;
    const el = $("#zoneLegend");
    if (S.zone === "class") {
      const cells = [2, 1, 0].map((n) => BIVAR[n].map((c) => `<i style="background:${c}"></i>`).join("")).join("");
      el.innerHTML = `<div class="bivar-wrap"><div class="bivar">${cells}</div>
        <div>Darker purple: more need (low income, high bills).<br>Warmer gold: more solar per home.<br>
        Deep magenta is where both are high.</div></div>`;
    } else if (S.zone === "need") el.innerHTML = rampBar(VIO, "Lower need", "Higher need");
    else if (S.zone === "pot") el.innerHTML = rampBar(SUN, `${fmt(r.potMin)} kWh per home`, `${fmt(r.potMax)} kWh per home`);
    else el.innerHTML = rampBar(VIO, `Rs ${fmt(r.incMax)} a year`, `Rs ${fmt(r.incMin)} a year`);
  }
  function roofLegend() {
    const el = $("#roofLegend"), m = S.meta;
    let html = "";
    if (S.roof === "irr") html = rampBar(SUN, `${fmt(m.irr_min)} kWh/m\u00b2 a year`, `${fmt(m.irr_max)} kWh/m\u00b2 a year`);
    else if (S.roof === "score") html = rampBar(VIO, "Lower priority", "Higher priority");
    else html = "<ul>" + Object.entries(PROGRAM_COLORS)
      .map(([k, c]) => `<li><span class="swatch" style="background:${c}"></span>${k}</li>`).join("") + "</ul>";
    html += `<div style="margin-top:6px"><span class="swatch" style="background:${NO_PV}"></span>No usable roof area
             &nbsp; <span class="swatch" style="background:#fff;border:2px solid #1a0f3d"></span>Priority roof</div>`;
    el.innerHTML = html;
  }

  // popups ------------------------------------------------------------------------
  function roofPopup(p) {
    const own = p.use_type === "residential" ? (p.owner_occ ? "Owner-occupied" : "Rented") : p.use_type;
    return `<div class="pop">${p.is_priority ? '<span class="tag">Priority roof #' + p.priority_rank + "</span>" : ""}
      <h3>Building ${p.building_id}</h3>
      <table>
        <tr><td>Type</td><td>${p.use_type}, ${p.floors} floors</td></tr>
        <tr><td>Occupancy</td><td>${own}</td></tr>
        <tr><td>Sunlight on roof</td><td>${fmt(p.mean_irr_kwh_m2)} kWh/m\u00b2</td></tr>
        <tr><td>Usable roof</td><td>${fmt(p.suitable_pct)} %</td></tr>
        <tr><td>System size</td><td>${fmt(p.capacity_kwp, 1)} kWp</td></tr>
        <tr><td>Yearly output</td><td>${fmt(p.annual_kwh)} kWh</td></tr>
        <tr><td>Homes it could power</td><td>${fmt(p.households_powered, 1)}</td></tr>
        <tr><td>Zone income</td><td>Rs ${fmt(p.median_income_inr)}</td></tr>
        <tr><td>Suggested route</td><td>${p.program}</td></tr>
      </table></div>`;
  }
  function zoneTip(p) {
    return `<b>${p.name}</b><br>Income Rs ${fmt(p.median_income_inr)} a year<br>Energy bills ${fmt(p.energy_burden_pct, 1)} % of income
      <br>Owners ${fmt(p.owner_rate * 100)} %<br>Solar covers ${fmt(p.demand_met_pct)} % of home demand<br><i>${p.tract_class}</i>`;
  }

  // layers -------------------------------------------------------------------------
  function drawZones() {
    if (S.tLayer) S.tLayer.remove();
    S.tLayer = L.geoJSON(S.tracts, { style: zoneStyle,
      onEachFeature: (f, l) => l.bindTooltip(zoneTip(f.properties), { sticky: true }) }).addTo(map);
    zoneLegend();
  }
  function passes(p) {
    const use = $("#fUse").value, own = $("#fOwner").value;
    if (use !== "all" && p.use_type !== use) return false;
    if (own !== "all" && String(p.owner_occ) !== own) return false;
    if (p.capacity_kwp < Number($("#fKwp").value)) return false;
    if ($("#fPrio").checked && !p.is_priority) return false;
    return true;
  }
  function drawRoofs() {
    if (S.bLayer) S.bLayer.remove();
    S.byId = {};
    S.bLayer = L.geoJSON(S.blds, { style: roofStyle, filter: (f) => passes(f.properties),
      onEachFeature: (f, l) => { l.bindPopup(roofPopup(f.properties), { maxWidth: 300 }); S.byId[f.properties.building_id] = l; } })
      .addTo(map);
    roofLegend();
  }

  // panel --------------------------------------------------------------------------
  function facts(s) {
    const items = [
      ["Solar capacity", `${fmt(s.total_capacity_mwp, 1)} MWp`],
      ["Yearly electricity", `${fmt(s.annual_gwh, 1)} GWh`],
      ["Homes' worth of power", fmt(s.households_powered)],
      ["Typical yield", `${fmt(s.avg_specific_yield_kwh_kwp)} kWh per kWp`],
      ["Priority roofs", fmt(s.n_priority_buildings), true],
      ["Their yearly output", `${fmt(s.priority_gwh, 1)} GWh`, true],
    ];
    $("#facts").innerHTML = items.map(([k, v, a]) => `<div class="${a ? "accent" : ""}"><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  }
  async function topList() {
    const rows = await (await fetch("/api/priority?limit=12")).json();
    $("#topList").innerHTML = rows.map((r) => `<li><button data-id="${r.building_id}" data-lat="${r.lat}" data-lon="${r.lon}">
        <span class="t">#${r.priority_rank} &middot; Building ${r.building_id}</span><span class="v">${fmt(r.capacity_kwp, 1)} kWp</span>
        <span class="m">${r.program}</span><span class="m" style="text-align:right">${fmt(r.annual_kwh)} kWh a year</span></button></li>`).join("");
    document.querySelectorAll("#topList button").forEach((b) => b.addEventListener("click", () => {
      map.flyTo([+b.dataset.lat, +b.dataset.lon], 19, { duration: 0.8 });
      const l = S.byId[b.dataset.id];
      if (l) setTimeout(() => l.openPopup(), 850);
    }));
  }
  function bindSegmented(id, key, redraw) {
    const group = $(id);
    group.addEventListener("click", (e) => {
      const btn = e.target.closest("button"); if (!btn) return;
      group.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b === btn)));
      S[key] = btn.dataset.v; redraw();
    });
  }

  // Spatial Operations Lab Visualization -----------------------------------------
  async function runSpatialLabOp() {
    const opVal = $("#labOpSelect").value;
    const box = $("#labResultBox");
    box.style.display = "block";
    box.textContent = "Executing spatial query on MongoDB Atlas...";

    if (S.labLayer) S.labLayer.remove();

    try {
      const res = await (await fetch(`/api/lab/execute?op=${opVal}`)).json();
      box.textContent = JSON.stringify(res, null, 2);

      const features = [];
      if (res.results && Array.isArray(res.results)) {
        res.results.forEach((r) => {
          if (r.geometry) {
            features.push({ type: "Feature", geometry: r.geometry, properties: r.properties || r });
          } else if (r.type === "Feature") {
            features.push(r);
          }
        });
      }
      if (res.merged_geometry) features.push({ type: "Feature", geometry: res.merged_geometry, properties: { name: "Merged Boundary (Polygon Union)" } });
      if (res.buffer_geometry) features.push({ type: "Feature", geometry: res.buffer_geometry, properties: { name: "Substation Service Buffer Surface" } });
      if (res.road_line_geometry) features.push({ type: "Feature", geometry: res.road_line_geometry, properties: { name: "Grid Transmission Line" } });
      if (res.centroid_geojson) features.push({ type: "Feature", geometry: res.centroid_geojson, properties: { name: "Centroid Location" } });
      if (res.found_entity && res.found_entity.geometry) features.push({ type: "Feature", geometry: res.found_entity.geometry, properties: res.found_entity });

      if (features.length > 0) {
        S.labLayer = L.geoJSON({ type: "FeatureCollection", features }, {
          pane: "labHighlight",
          style: (f) => {
            const name = (f.properties && f.properties.name) ? f.properties.name : "";
            if (name.includes("Buffer") || name.includes("Union") || name.includes("Zone")) {
              return { color: "#8a2be2", fillColor: "#da70d6", fillOpacity: 0.35, weight: 2.5, dashArray: "5,5" };
            }
            if (f.geometry.type === "LineString") {
              return { color: "#e0620f", weight: 5, opacity: 0.9 };
            }
            return { color: "#1a0f3d", fillColor: "#ffaa00", fillOpacity: 0.95, weight: 3 };
          },
          pointToLayer: (f, latlng) => {
            const name = (f.properties && f.properties.name) ? f.properties.name : "";
            const isCentroid = name.includes("Centroid") || name.includes("Substation") || name.includes("Site");
            return L.circleMarker(latlng, {
              radius: isCentroid ? 11 : 8,
              fillColor: isCentroid ? "#e0620f" : "#ffea00",
              color: "#ffffff",
              weight: 2.5,
              fillOpacity: 1.0
            });
          },
          onEachFeature: (f, layer) => {
            const p = f.properties || {};
            const title = p.name || p.operation || `Solar Building #${p.building_id || ""}`;
            let popupContent = `<div class="pop"><h3>${title}</h3>`;
            if (p.use_type) popupContent += `<b>Type:</b> ${p.use_type}, ${p.floors || 1} floors<br>`;
            if (p.capacity_kwp) popupContent += `<b>Solar System Size:</b> ${p.capacity_kwp} kWp<br>`;
            if (p.annual_kwh) popupContent += `<b>Yearly Output:</b> ${p.annual_kwh.toLocaleString()} kWh<br>`;
            if (p.distance_km) popupContent += `<b>Distance:</b> ${p.distance_km.toFixed(2)} km<br>`;
            if (p.distance_m) popupContent += `<b>Distance:</b> ${p.distance_m.toFixed(1)} m<br>`;
            if (p.building_height_m) popupContent += `<b>Building Height:</b> ${p.building_height_m} m<br>`;
            if (p.program) popupContent += `<b>Program:</b> ${p.program}<br>`;
            popupContent += `</div>`;
            layer.bindPopup(popupContent);
            layer.bindTooltip(title, { sticky: true });
          }
        }).addTo(map);

        // Intelligently zoom to building rooftops if present, otherwise fit bounds with maxZoom
        const bldFeatures = features.filter((f) => f.geometry.type === "Polygon" && (!f.properties.name || !f.properties.name.includes("Zone")));
        if (bldFeatures.length > 0) {
          const bldLayer = L.geoJSON({ type: "FeatureCollection", features: bldFeatures });
          map.flyToBounds(bldLayer.getBounds(), { maxZoom: 18.5, duration: 1.0, padding: [40, 40] });
        } else {
          map.flyToBounds(S.labLayer.getBounds(), { maxZoom: 18, duration: 1.0, padding: [30, 30] });
        }

        // Open popup automatically on first highlighted feature
        setTimeout(() => {
          S.labLayer.eachLayer((l) => {
            if (l.openPopup) { l.openPopup(); return; }
          });
        }, 1100);
      }
    } catch (err) {
      box.textContent = "Error executing query: " + err.message;
    }
  }

  // boot ------------------------------------------------------------------------------
  async function init() {
    const [meta, tracts, blds] = await Promise.all(
      ["/api/meta", "/api/tracts", "/api/buildings"].map((u) => fetch(u).then((r) => r.json())));
    S.meta = meta; S.tracts = tracts; S.blds = blds;
    const pv = tracts.features.map((f) => f.properties);
    S.tRange = { potMin: Math.min(...pv.map((p) => p.solar_kwh_per_hh)), potMax: Math.max(...pv.map((p) => p.solar_kwh_per_hh)),
                 incMin: Math.min(...pv.map((p) => p.median_income_inr)), incMax: Math.max(...pv.map((p) => p.median_income_inr)) };
    map.fitBounds(meta.bounds, { padding: [20, 20] });
    facts(meta.summary); drawZones(); drawRoofs(); topList();

    bindSegmented("#zoneView", "zone", drawZones);
    bindSegmented("#roofView", "roof", drawRoofs);
    ["#fUse", "#fOwner", "#fPrio"].forEach((id) => $(id).addEventListener("change", drawRoofs));
    $("#fKwp").addEventListener("input", () => { $("#kwpOut").textContent = $("#fKwp").value + " kWp"; });
    $("#fKwp").addEventListener("change", drawRoofs);

    // Bind Spatial Lab Execute button
    const btn = $("#btnRunLabOp");
    if (btn) btn.addEventListener("click", runSpatialLabOp);
  }
  init().catch((e) => { $("#facts").innerHTML = `<dd>Could not load data: ${e.message}. Run the analysis first.</dd>`; });
})();
