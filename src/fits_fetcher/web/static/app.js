// FITS-fetcher search page. Talks to the local server's /api endpoints.
"use strict";

const $ = (id) => document.getElementById(id);
const state = { info: null, target: null, source: null, sets: [], selected: new Map() };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

const fmt = {
  size(bytes) {
    if (!bytes) return "?";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0, v = bytes;
    while (v >= 1000 && i < units.length - 1) { v /= 1000; i++; }
    return `${v.toFixed(v < 10 && i > 1 ? 1 : 0)} ${units[i]}`;
  },
  um(v) { return v == null ? "?" : v < 1 ? `${Math.round(v * 1000)} nm` : `${+v.toFixed(2)} µm`; },
  exp(s) { return s == null ? "?" : s >= 3600 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s)} s`; },
  deg(ra, dec) { return `RA ${ra.toFixed(5)}°, Dec ${dec >= 0 ? "+" : ""}${dec.toFixed(5)}°`; },
  // Sexagesimal parts, rounded once at the last digit so 59.995 s carries into the minutes.
  sexa(v, unitsPerDeg, digits) {
    const scale = 10 ** digits;
    let t = Math.round(Math.abs(v) * unitsPerDeg * 3600 * scale);
    const frac = t % (60 * scale); t = (t - frac) / (60 * scale);
    return [Math.floor(t / 60), t % 60, (frac / scale).toFixed(digits).padStart(3 + digits, "0")];
  },
  hms(ra) {
    const [h, m, s] = fmt.sexa(((ra % 360) + 360) % 360, 1 / 15, 2);
    return `${String(h % 24).padStart(2, "0")}h ${String(m).padStart(2, "0")}m ${s}s`;
  },
  dms(dec) {
    const [d, m, s] = fmt.sexa(dec, 1, 1);
    return `${dec < 0 ? "-" : "+"}${String(d).padStart(2, "0")}° ${String(m).padStart(2, "0")}′ ${s}″`;
  },
  position(ra, dec) {
    return `RA ${ra.toFixed(5)}° (${fmt.hms(ra)}), Dec ${dec >= 0 ? "+" : ""}${dec.toFixed(5)}° (${fmt.dms(dec)})`;
  },
  offset(arcmin) { return arcmin < 1 ? `${(arcmin * 60).toFixed(1)}″` : `${arcmin.toFixed(2)}′`; },
};

// ---------- startup ----------
async function init() {
  const info = await (await fetch("/api/info")).json();
  state.info = info;
  $("version").textContent = `v${info.version}`;
  $("min-filters").value = info.settings.min_filters;
  $("mix").checked = info.settings.mix_instruments;
  $("hst-mosaics").checked = info.settings.hst_show_mosaics;
  for (const name of [...info.archives, ...info.planned]) {
    const available = info.archives.includes(name);
    $("archive-boxes").append(el("label", { class: "check" + (available ? "" : " unavailable") },
      el("input", { type: "checkbox", value: name, checked: available, disabled: !available }),
      available ? name : `${name} (not built yet)`));
  }
  for (const line of info.emission_lines) {
    $("line-boxes").append(el("label", { class: "check" }, el("input", { type: "checkbox", value: line }), line));
  }
}

// ---------- object resolution (S-10, REQ-18) ----------
$("resolve-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  setTarget(null);
  $("resolve-error").hidden = true;
  $("candidates").hidden = true;
  const q = $("name").value.trim();
  const btn = e.submitter; btn.disabled = true; btn.textContent = "Finding…";
  try {
    const r = await fetch(`/api/resolve?q=${encodeURIComponent(q)}`);
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || "Lookup failed.");
    if (body.targets.length === 1) setTarget(body.targets[0]);
    else showCandidates(body.targets);
  } catch (err) {
    $("resolve-error").textContent = err.message;
    $("resolve-error").hidden = false;
  } finally {
    btn.disabled = false; btn.textContent = "Find object";
  }
});

function showCandidates(targets) {
  const list = $("candidate-list");
  list.replaceChildren(...targets.map((t) => el("li", {},
    el("button", { type: "button", onclick: () => { $("candidates").hidden = true; setTarget(t); } },
      `${t.matched_id}`, el("span", { class: "muted" }, `  ${t.object_type || ""}  ${fmt.deg(t.ra, t.dec)}`)))));
  $("candidates").hidden = false;
}

function setTarget(t) {
  state.target = t;
  $("search").disabled = !t;
  if (!t) { $("target").hidden = true; return; }
  const size = t.size_arcmin ? `, size ≈ ${(+t.size_arcmin).toFixed(1)}′` : "";
  $("target").replaceChildren(
    el("strong", {}, t.matched_id), " ",
    el("span", { class: "muted" }, `${t.object_type ? `(${t.object_type}) ` : ""}${fmt.deg(t.ra, t.dec)}${size}`),
    el("div", { class: "muted" }, `You typed “${t.query}”. Check this is the object you meant before searching.`));
  $("target").hidden = false;
}

// ---------- search (S-07, S-32) ----------
$("search").addEventListener("click", () => {
  const t = state.target; if (!t) return;
  stopSearch();
  state.selected.clear();
  const checked = (sel) => [...document.querySelectorAll(sel)].filter((b) => b.checked).map((b) => b.value);
  const params = new URLSearchParams({
    ra: t.ra, dec: t.dec, matched_id: t.matched_id, query: t.query,
    archives: checked("#archive-boxes input").join(","),
    min_filters: $("min-filters").value, mix_instruments: $("mix").checked,
    band_type: $("band-type").value, lines: checked("#line-boxes input").join(","),
    hst_mosaics: $("hst-mosaics").checked,
  });
  if (t.size_arcmin) params.set("size_arcmin", t.size_arcmin);

  $("archive-status").replaceChildren();
  $("results").replaceChildren();
  $("results-summary").textContent = "Searching…";
  $("results-panel").hidden = false;
  $("cancel").hidden = false;
  $("search").disabled = true;
  updateSelection();

  const src = new EventSource(`/api/search?${params}`);
  state.source = src;
  src.addEventListener("status", (e) => showStatus(JSON.parse(e.data)));
  src.addEventListener("sets", (e) => showSets(JSON.parse(e.data)));
  src.addEventListener("end", () => finishSearch());
  src.onerror = () => { if (state.source) finishSearch("The connection to FITS-fetcher was lost."); };
});

$("cancel").addEventListener("click", () => finishSearch("Search cancelled."));

function stopSearch() { if (state.source) { state.source.close(); state.source = null; } }

function finishSearch(message) {
  stopSearch();
  $("cancel").hidden = true;
  $("search").disabled = !state.target;
  for (const li of document.querySelectorAll("#archive-status li.searching")) {
    li.className = "failed"; li.textContent = `${li.dataset.archive}: stopped.`;
  }
  if (message) $("results-summary").textContent = message;
  else if (!state.sets.length) $("results-summary").textContent =
    "No colour sets found. Try fewer minimum filters, allow mixing instruments, or another archive.";
}

function showStatus(s) {
  let li = document.querySelector(`#archive-status li[data-archive="${s.archive}"]`);
  if (!li) { li = el("li", { "data-archive": s.archive }); $("archive-status").append(li); }
  li.className = s.state;
  li.textContent = {
    searching: `${s.archive}: searching…`,
    done: `${s.archive}: ${s.count} matching image${s.count === 1 ? "" : "s"}.`,
  }[s.state] || s.message;
}

// ---------- results (S-05, S-06, S-17, S-21, REQ-27, REQ-53) ----------
function showSets(data) {
  state.sets = data.sets;
  $("results-summary").textContent = `${data.sets.length} colour set${data.sets.length === 1 ? "" : "s"} from ` +
    `${data.products_found} matching images for ${data.target.matched_id || data.target.query}.`;
  $("results").replaceChildren(...data.sets.map(renderSet));
  updateSelection();
}

// Matched grid groups (REQ-60) cycle through the --grid-N colours in style.css.
const GRID_COLOURS = 6;
const gridStyle = (i) => `--gc: var(--grid-${i % GRID_COLOURS})`;

function renderSet(set) {
  const allBtn = el("button", { type: "button", class: "secondary", onclick: (e) => { e.preventDefault(); selectWholeSet(set); } },
    "Select deepest in every filter");
  const gridOf = new Map();
  set.grids.forEach((g, i) => { for (const k of g.product_keys) gridOf.set(k, { ...g, i }); });
  const legend = set.grids.length ? el("div", { class: "grids" }, set.grids.map((g, i) =>
    el("div", { class: "grid-line", style: gridStyle(i) },
      el("span", { class: "chip grid" }, `Grid ${g.label}`),
      el("span", {}, `${g.filters.join(", ")} · ${g.grid} · same pixel grid, stacks without registration`),
      el("button", { type: "button", class: "secondary small", onclick: () => selectGrid(set, g) }, "Select")))) : null;
  const body = el("tbody");
  for (const row of set.rows) {
    const line = row.line ? ` · ${row.line}` : "";
    body.append(el("tr", { class: "filter-row" },
      el("td", { colspan: 9 }, `${row.filter} — ${fmt.um(row.wavelength_um)} · ${row.band_type}band${line}`,
        el("span", { class: "muted" }, `  (${row.products.length} image${row.products.length === 1 ? "" : "s"})`))));
    for (const p of row.products) body.append(...renderProduct(p, gridOf.get(p.key)));
  }
  return el("details", { class: "set", open: true },
    el("summary", {}, el("span", { class: "set-name" }, set.name.replaceAll("_", " · ")),
      el("span", { class: "muted" }, set.readiness), allBtn),
    ...set.warnings.map((w) => el("p", { class: "warning" }, `⚠ ${w}`)),
    legend,
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ["", "Preview", "Filter", "Archive / instrument", "Exposure", "Pixel scale", "Download", "Date", ""]
        .map((h) => el("th", {}, h)))),
      body)));
}

function renderProduct(p, grid) {
  const mark = grid ? { class: "on-grid", style: gridStyle(grid.i) } : {};
  const box = el("input", { type: "checkbox", "data-key": p.key, checked: state.selected.has(p.key),
    onchange: (e) => { toggle(p, e.target.checked); } });
  const thumb = p.thumbnail_url
    ? el("img", { class: "thumb", src: p.thumbnail_url, loading: "lazy", alt: `${p.filter} preview` })
    : el("div", { class: "thumb", title: "No preview yet; one is made after download." });
  const centre = p.centre_ra != null && p.centre_dec != null
    ? el("div", {}, `${p.is_mosaic ? "Mosaic" : "Image"} centre: ${fmt.position(p.centre_ra, p.centre_dec)}` +
      (p.offset_arcmin != null ? ` · Object is ${fmt.offset(p.offset_arcmin)} from centre` : ""))
    : null;
  const details = el("tr", { ...mark, hidden: true }, el("td", {}), el("td", { class: "details-cell", colspan: 8 },
    `Telescope: ${p.telescope} · Bandwidth: ${fmt.um(p.bandwidth_um)} · Product: ${p.product_level} · ` +
    `Observation: ${p.obs_id}${p.is_mosaic ? " · Cut around the object from a multi-visit mosaic" : ""}`, centre));
  const more = el("button", { type: "button", class: "secondary", onclick: () => { details.hidden = !details.hidden; } }, "Details");
  return [el("tr", mark,
    el("td", {}, box), el("td", {}, thumb),
    el("td", {}, p.filter, " ", el("span", { class: "chip" }, p.band_type),
      grid ? el("div", {}, el("span", { class: "chip grid", title: `Same pixel grid as the other Grid ${grid.label} images` },
        `Grid ${grid.label}`)) : null),
    el("td", {}, `${p.archive} · ${p.instrument}`, p.is_mosaic ? el("div", {}, el("span", { class: "chip" }, "mosaic")) : null),
    el("td", {}, fmt.exp(p.exptime_s)),
    el("td", {}, p.pixel_scale_arcsec ? `${p.pixel_scale_arcsec}″` : "?"),
    el("td", {}, fmt.size(p.size_bytes)),
    el("td", {}, p.obs_date || "?"),
    el("td", {}, more)), details];
}

function toggle(p, on) {
  if (on) state.selected.set(p.key, p); else state.selected.delete(p.key);
  for (const b of document.querySelectorAll(`input[data-key="${CSS.escape(p.key)}"]`)) b.checked = on;
  updateSelection();
}

function selectWholeSet(set) {
  for (const row of set.rows) if (row.products.length) toggle(row.products[0], true);  // deepest first (REQ-53)
}

function selectGrid(set, grid) {
  const keys = new Set(grid.product_keys);
  for (const row of set.rows) for (const p of row.products) if (keys.has(p.key)) toggle(p, true);
}

function updateSelection() {
  const items = [...state.selected.values()];
  const total = items.reduce((s, p) => s + (p.size_bytes || 0), 0);
  const limit = (state.info?.settings.size_warning_gb || 5) * 1e9;
  $("selection-summary").textContent = items.length
    ? `${items.length} image${items.length === 1 ? "" : "s"} selected, about ${fmt.size(total)} to download.` +
      (total > limit ? ` ⚠ Over your ${fmt.size(limit)} warning limit.` : "")
    : "Nothing selected.";
  $("selection-summary").className = total > limit ? "warning" : "muted";
}

// ---------- quit (S-36) ----------
$("quit").addEventListener("click", async () => {
  stopSearch();
  try { await fetch("/api/quit", { method: "POST" }); } catch (_) { /* server already gone */ }
  document.body.replaceChildren(el("main", {}, el("section", { class: "panel" },
    el("h2", {}, "FITS-fetcher has stopped."), el("p", { class: "muted" }, "You can close this tab."))));
});

init();
