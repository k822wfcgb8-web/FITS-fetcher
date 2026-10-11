// FITS-fetcher search page. Talks to the local server's /api endpoints.
"use strict";

const $ = (id) => document.getElementById(id);
const state = { info: null, target: null, source: null, sets: [], elsewhere: [], selected: new Map(),
  job: null, jobSource: null, dl: new Map() /* key → item status from the running or last download */ };

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
  cover(f) {
    if (f == null) return "—";
    if (f >= 0.995) return "100%";
    if (f > 0 && f < 0.001) return "<0.1%";
    return f < 0.1 ? `${(Math.floor(f * 1000) / 10).toFixed(1)}%` : `${Math.floor(f * 100)}%`;
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
  $("opt-repair").checked = info.settings.star_repair;   // REQ-61: pre-set from the saved settings
  $("opt-cutout").checked = info.settings.cutout;
  buildSettingsForm();
  for (const name of [...info.archives, ...info.planned]) {
    const available = info.archives.includes(name);
    $("archive-boxes").append(el("label", { class: "check" + (available ? "" : " unavailable") },
      el("input", { type: "checkbox", value: name, checked: available, disabled: !available }),
      available ? name : `${name} (not built yet)`));
  }
  buildTelescopeBoxes();
  for (const line of info.emission_lines) {
    $("line-boxes").append(el("label", { class: "check" }, el("input", { type: "checkbox", value: line }), line));
  }
}

// ---------- telescopes (REQ-72–74) ----------
// A tick box per MAST telescope, shown while MAST is ticked. The name beside each box opens its fact sheet.
function buildTelescopeBoxes() {
  const box = $("telescope-boxes"), mast = document.querySelector('#archive-boxes input[value="MAST"]');
  if (!mast || !state.info.mast_telescopes.length) return;
  box.append(el("span", { class: "lead" }, "MAST telescopes:"),
    ...state.info.mast_telescopes.map((c) => el("span", { class: "check" },
      el("input", { type: "checkbox", value: c, checked: true, "aria-label": `Search ${telescopeName(c)}` }),
      telLink(c))));
  const show = () => { box.hidden = !mast.checked; };
  mast.addEventListener("change", show);
  show();
}

const telescopeName = (collection) => state.info.telescopes[collection]?.name || collection;

// The telescope's name as a link to its fact sheet; plain text if there is none.
function telLink(collection) {
  const t = state.info.telescopes[collection];
  if (!t) return collection;
  return el("a", { class: "tel", href: "#", title: `About ${t.full_name}`,
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); showTelescope(collection); } }, t.name);
}

// "MAST · Hubble" for an archive and collection; the archive alone if the collection is unknown.
const source = (archive, collection) => collection ? [`${archive} · `, telLink(collection)] : [archive];

function showTelescope(collection) {
  const t = state.info.telescopes[collection];
  $("telescope-title").textContent = t.full_name;
  $("telescope-facts").replaceChildren(...t.facts.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  $("telescope-artifacts").replaceChildren(...t.artifacts.map((a) => el("li", {}, a)));
  $("telescope-link").href = t.link;
  $("telescope-dialog").showModal();
}
$("telescope-close").addEventListener("click", () => $("telescope-dialog").close());
$("telescope-dialog").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });

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
    el("div", { class: "muted" }, `You typed “${t.query}”. Check this is the object you meant before searching.`),
    t.note ? el("div", { class: "warning target-note" }, `⚠ ${t.note}`) : null);
  $("target").hidden = false;
  $("opt-cutout-label").textContent = `Cut around the object (${cutoutBox(t).toFixed(1)}′ box)`;
}

// REQ-25/REQ-58: 2× the object's size, or the default box when the size is unknown.
function cutoutBox(t) { return t.size_arcmin ? 2 * t.size_arcmin : state.info.settings.cutout_default_arcmin; }

// ---------- search (S-07, S-32) ----------
$("search").addEventListener("click", () => {
  const t = state.target; if (!t) return;
  stopSearch();
  state.selected.clear();
  if (!downloading()) state.dl.clear();
  const checked = (sel) => [...document.querySelectorAll(sel)].filter((b) => b.checked).map((b) => b.value);
  const params = new URLSearchParams({
    ra: t.ra, dec: t.dec, matched_id: t.matched_id, query: t.query,
    archives: checked("#archive-boxes input").join(","),
    min_filters: $("min-filters").value, mix_instruments: $("mix").checked,
    band_type: $("band-type").value, lines: checked("#line-boxes input").join(","),
    hst_mosaics: $("hst-mosaics").checked,
  });
  if (!$("telescope-boxes").hidden) params.set("telescopes", checked("#telescope-boxes input").join(","));
  if (t.size_arcmin) params.set("size_arcmin", t.size_arcmin);

  $("archive-status").replaceChildren();
  $("results").replaceChildren();
  state.sets = []; state.elsewhere = [];
  $("elsewhere").replaceChildren();
  $("elsewhere").hidden = true;
  $("inside").replaceChildren();
  $("inside").hidden = true;
  $("results-summary").textContent = "Searching…";
  $("results-panel").hidden = false;
  $("cancel").hidden = false;
  $("search").disabled = true;
  updateSelection();

  const src = new EventSource(`/api/search?${params}`);
  state.source = src;
  src.addEventListener("status", (e) => showStatus(JSON.parse(e.data)));
  src.addEventListener("sets", (e) => showSets(JSON.parse(e.data)));
  src.addEventListener("elsewhere", (e) => showElsewhere(JSON.parse(e.data)));
  src.addEventListener("inside", (e) => showInside(JSON.parse(e.data)));
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
  else if (!state.sets.length) $("results-summary").textContent = state.elsewhere.length
    ? `No colour sets contain the centre of ${objectName()}; see the sets elsewhere in it below.`
    : "No colour sets found. Try fewer minimum filters, allow mixing instruments, or another archive.";
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

// ---------- coverage of the object (REQ-69) ----------
function objectName() { return state.target ? state.target.matched_id || state.target.query : "the object"; }

function coverageTitle() {
  return state.target?.size_arcmin ? `Share of ${objectName()} (${(+state.target.size_arcmin).toFixed(1)}′ across) inside this image`
    : "The object's size is unknown, so coverage can't be measured.";
}

function setCoverage(set) {
  if (set.coverage == null) return null;
  const whole = set.coverage >= 0.995;
  return el("span", { class: `chip ${whole ? "whole" : ""}`, title: "Lowest coverage over the filters, taking the best image in each" },
    whole ? `whole ${objectName()} in every filter`
      : set.coverage > 0 && set.coverage < 0.001 ? `under 0.1% of ${objectName()} in every filter`
      : `at least ${fmt.cover(set.coverage)} of ${objectName()} in every filter`);
}

// ---------- same-grid sets away from the centre (REQ-71) ----------
function showElsewhere(data) {
  const box = $("elsewhere");
  if (data.state === "searching") {
    box.replaceChildren(el("p", { class: "muted" }, `Looking for colour sets elsewhere in ${objectName()}…`));
    box.hidden = false;
    return;
  }
  state.elsewhere = data.sets;
  const failed = data.failed?.length ? el("p", { class: "muted" }, `Couldn't look everywhere: ${data.failed.join(", ")}.`) : null;
  if (!data.sets.length) {
    box.replaceChildren(...(failed ? [failed] : []));
    box.hidden = !failed;
    return;
  }
  box.replaceChildren(el("h3", {}, `Elsewhere in ${objectName()}`),
    el("p", { class: "muted" }, `Images that miss the centre, where filters on one pixel grid share an area. ` +
      `Each image is cut to the area all filters of its set share, so the set stacks without registration.`),
    ...(failed ? [failed] : []), ...data.sets.map(renderSet));
  box.hidden = false;
  updateSelection();
}

function setPosition(set) {
  if (!set.position) return null;
  const p = set.position;
  return el("span", { class: "chip", title: `Shared area centred at ${fmt.position(p.ra, p.dec)}` },
    `${fmt.offset(p.offset_arcmin)} ${p.direction} of centre · ${p.area_arcmin2.toFixed(1)} arcmin²`);
}

// ---------- other objects inside (REQ-70) ----------
function showInside(data) {
  const box = $("inside");
  if (data.state === "searching") {
    box.replaceChildren(el("p", { class: "muted" }, `Looking for other objects with colour sets inside ${objectName()}…`));
    box.hidden = false;
    return;
  }
  if (!data.objects.length) {
    box.replaceChildren(...(data.failed?.length ? [el("p", { class: "muted" }, `Couldn't look for other objects inside ${objectName()}.`)] : []));
    box.hidden = !data.failed?.length;
    return;
  }
  box.replaceChildren(el("h3", {}, `Also inside ${objectName()}`),
    el("ul", { class: "inside-list" }, data.objects.map((o) => el("li", {},
      el("div", { class: "inside-head" },
        el("button", { type: "button", class: "secondary small", onclick: () => searchInside(o) }, "Search"),
        el("strong", {}, o.name), el("span", { class: "muted" }, `${fmt.offset(o.offset_arcmin)} from the centre`)),
      ...o.sets.map((s) => el("div", { class: "muted inside-set" }, ...source(s.archive, s.collection),
        ` · ${s.instrument} · ${s.filters.length} filters (${s.filters.join(", ")})`))))));
  box.hidden = false;
}

async function searchInside(o) {
  // The resolver's own entry gives the object's size; if that lookup fails, search at its position.
  let target = { query: o.name, matched_id: o.name, ra: o.ra, dec: o.dec, object_type: "", size_arcmin: null };
  try {
    const r = await fetch(`/api/resolve?q=${encodeURIComponent(o.name)}`);
    if (r.ok) {
      const found = (await r.json()).targets;
      const near = (t) => Math.hypot((t.ra - o.ra) * Math.cos(o.dec * Math.PI / 180), t.dec - o.dec);
      const best = found.sort((a, b) => near(a) - near(b))[0];
      if (best && near(best) < 0.1) target = best;
    }
  } catch (_) { /* fall back to the position */ }
  $("name").value = o.name;
  setTarget(target);
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("search").click();
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
      el("td", { colspan: 10 }, `${row.filter} — ${fmt.um(row.wavelength_um)} · ${row.band_type}band${line}`,
        el("span", { class: "muted" }, `  (${row.products.length} image${row.products.length === 1 ? "" : "s"})`))));
    for (const p of row.products) body.append(...renderProduct(p, gridOf.get(p.key)));
  }
  // REQ-73: the archive and telescope of every image in the set, e.g. "MAST · Pan-STARRS1".
  const sources = new Map();
  for (const row of set.rows) for (const p of row.products) sources.set(`${p.archive}|${p.collection}`, p);
  const heading = [...sources.values()].flatMap((p, i) => [i ? " + " : "", ...source(p.archive, p.collection)]);
  return el("details", { class: "set", open: true },
    // An off-centre set's folder name ends in its position, which the position chip shows instead.
    el("summary", {}, el("span", { class: "set-name" }, ...heading, " · ",
      (set.position ? set.name.split("_").slice(0, -1).join("_") : set.name).replaceAll("_", " · ")),
      el("span", { class: "muted" }, set.readiness), setPosition(set), setCoverage(set), allBtn),
    ...set.warnings.map((w) => el("p", { class: "warning" }, `⚠ ${w}`)),
    legend,
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, ["", "Preview", "Filter", "Archive · telescope · instrument", "Exposure", "Covers", "Pixel scale", "Download", "Date", ""]
        .map((h) => el("th", {}, h)))),
      body)));
}

function renderProduct(p, grid) {
  const mark = grid ? { class: "on-grid", style: gridStyle(grid.i) } : {};
  const box = el("input", { type: "checkbox", "data-key": p.key, checked: state.selected.has(p.key),
    onchange: (e) => { toggle(p, e.target.checked); } });
  const thumb = p.thumbnail_url
    ? el("img", { class: "thumb", src: p.thumbnail_url, loading: "lazy", alt: `${p.filter} preview` })
    : el("div", { class: "thumb", "data-thumb-key": p.key, title: "No preview yet; one is made after download." });
  const centre = p.centre_ra != null && p.centre_dec != null
    ? el("div", {}, `${p.is_mosaic ? "Mosaic" : "Image"} centre: ${fmt.position(p.centre_ra, p.centre_dec)}` +
      (p.offset_arcmin != null ? ` · Object is ${fmt.offset(p.offset_arcmin)} from centre` : ""))
    : null;
  const details = el("tr", { ...mark, hidden: true }, el("td", {}), el("td", { class: "details-cell", colspan: 9 },
    `Telescope: ${p.telescope} · Bandwidth: ${fmt.um(p.bandwidth_um)} · Product: ${p.product_level} · ` +
    `Observation: ${p.obs_id}` + (p.cut?.length ? ` · Cut to the area all filters of its set share${p.is_mosaic ? ", from a multi-visit mosaic" : ""}`
      : p.is_mosaic ? " · Cut around the object from a multi-visit mosaic" : ""), centre));
  const more = el("button", { type: "button", class: "secondary", onclick: () => { details.hidden = !details.hidden; } }, "Details");
  return [el("tr", mark,
    el("td", {}, box), el("td", {}, thumb),
    el("td", {}, p.filter, " ", el("span", { class: "chip" }, p.band_type),
      grid ? el("div", {}, el("span", { class: "chip grid", title: `Same pixel grid as the other Grid ${grid.label} images` },
        `Grid ${grid.label}`)) : null),
    el("td", {}, ...source(p.archive, p.collection), ` · ${p.instrument}`, p.is_mosaic ? el("div", {}, el("span", { class: "chip" }, "mosaic")) : null),
    el("td", {}, fmt.exp(p.exptime_s)),
    el("td", { title: coverageTitle() }, fmt.cover(p.coverage)),
    el("td", {}, p.pixel_scale_arcsec ? `${p.pixel_scale_arcsec}″` : "?"),
    el("td", {}, fmt.size(p.size_bytes), statusLine(p.key)),
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
  $("download").disabled = !items.length || downloading();
  $("selection-summary").textContent = items.length
    ? `${items.length} image${items.length === 1 ? "" : "s"} selected, about ${fmt.size(total)} to download.` +
      (total > limit ? ` ⚠ Over your ${fmt.size(limit)} warning limit.` : "")
    : "Nothing selected.";
  $("selection-summary").className = total > limit ? "warning" : "muted";
}

// ---------- download (S-07, S-26, REQ-61–63) ----------
const downloading = () => !!state.job && !state.job.finished;

const STATUS = {
  queued: () => "Waiting",
  downloading: (it) => it.total ? `Downloading ${Math.floor(100 * it.done / it.total)}%` : "Downloading…",
  processing: (it) => it.message || "Processing…",
  saved: (it) => "Saved ✓" + (it.message ? ` ⚠ ${it.message}` : ""),
  skipped: () => "Already downloaded ✓",
  failed: (it) => `Failed: ${it.message}`,
  cancelled: () => "Cancelled",
};

function statusLine(key) {
  const node = el("div", { class: "dl-status", "data-status-key": key });
  const it = state.dl.get(key);
  if (it) paintStatus(node, it);
  return node;
}

function paintStatus(node, it) {
  node.className = `dl-status ${it.state}`;
  node.textContent = STATUS[it.state](it);
  node.title = it.paths?.length ? it.paths.join("\n") : "";
}

function setsContaining(key) {
  return [...state.sets, ...state.elsewhere]
    .filter((s) => s.rows.some((r) => r.products.some((p) => p.key === key))).map((s) => s.name);
}

$("download").addEventListener("click", async () => {
  const items = [...state.selected.values()];
  if (!items.length || !state.target) return;
  const total = items.reduce((s, p) => s + (p.size_bytes || 0), 0);
  const limit = state.info.settings.size_warning_gb * 1e9;
  if (total > limit && !confirm(`About ${fmt.size(total)} will be downloaded, over your ${fmt.size(limit)} warning limit. Continue?`)) return;

  const body = {
    target: state.target, star_repair: $("opt-repair").checked, cutout: $("opt-cutout").checked,
    items: items.map((p) => ({ key: p.key, sets: setsContaining(p.key) })),
  };
  $("download").disabled = true;
  $("download-summary").hidden = true;
  let snap;
  try {
    const r = await fetch("/api/download", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    snap = await r.json();
    if (!r.ok) throw new Error(snap.detail || "The download couldn't start.");
  } catch (err) {
    showDownloadSummary(err.message, false);
    updateSelection();
    return;
  }
  state.dl.clear();
  showProgress(snap);
  $("download-cancel").hidden = false;
  $("download-progress").hidden = false;
  const src = new EventSource(`/api/download/${snap.id}/events`);
  state.jobSource = src;
  src.addEventListener("progress", (e) => showProgress(JSON.parse(e.data)));
  src.addEventListener("end", (e) => finishDownload(JSON.parse(e.data)));
  src.onerror = () => { if (state.jobSource) finishDownload(null, "The connection to FITS-fetcher was lost."); };
});

$("download-cancel").addEventListener("click", async () => {
  if (!state.job) return;
  $("download-cancel").disabled = true;
  $("overall-text").textContent = "Cancelling…";
  try { await fetch(`/api/download/${state.job.id}/cancel`, { method: "POST" }); } catch (_) { /* reported by the stream */ }
});

$("open-folder").addEventListener("click", async () => {
  if (!state.job) return;
  const r = await fetch(`/api/download/${state.job.id}/open`, { method: "POST" });
  if (!r.ok) $("download-summary-text").textContent = (await r.json()).detail;
});

function showProgress(snap) {
  state.job = snap;
  for (const it of snap.items) {
    const before = state.dl.get(it.key);
    state.dl.set(it.key, it);
    for (const node of document.querySelectorAll(`[data-status-key="${CSS.escape(it.key)}"]`)) paintStatus(node, it);
    if ((it.state === "saved" || it.state === "skipped") && before?.state !== it.state) showThumbnail(snap.id, it.key);
  }
  const c = snap.counts, n = snap.items.length;
  const left = n - c.saved - c.skipped - c.failed - c.cancelled;
  $("overall").value = snap.bytes_total ? snap.bytes_done / snap.bytes_total : (n - left) / n;
  if (!snap.cancelled) $("overall-text").textContent =
    `${n - left} of ${n} done · ${fmt.size(snap.bytes_done)} of about ${fmt.size(snap.bytes_total)}`;
}

// REQ-27: images without an archive preview get one made from the saved file.
function showThumbnail(jobId, key) {
  for (const ph of document.querySelectorAll(`div[data-thumb-key="${CSS.escape(key)}"]`)) {
    ph.replaceWith(el("img", { class: "thumb", src: `/api/download/${jobId}/thumb?key=${encodeURIComponent(key)}`,
      alt: "Preview made from the downloaded image" }));
  }
}

function finishDownload(snap, error) {
  if (state.jobSource) { state.jobSource.close(); state.jobSource = null; }
  if (snap) showProgress(snap);
  if (state.job) state.job.finished = true;
  $("download-cancel").hidden = true;
  $("download-cancel").disabled = false;
  $("download-progress").hidden = true;
  updateSelection();
  if (error) { showDownloadSummary(error, false); return; }
  const c = snap.counts;
  const parts = [`${c.saved} saved`, `${c.skipped} already downloaded`, `${c.failed} failed`];
  if (c.cancelled) parts.push(`${c.cancelled} cancelled`);
  showDownloadSummary(`${parts.join(", ")}. Folder: ${snap.object_dir}`, c.saved + c.skipped > 0);
}

function showDownloadSummary(text, canOpen) {
  $("download-summary-text").textContent = text;
  $("open-folder").hidden = !canOpen;
  $("download-summary").hidden = false;
}

// ---------- settings dialog (S-08, REQ-64–66) ----------
const SETTINGS_FIELDS = [
  ["Folders", [
    { key: "output_dir", label: "Output folder", type: "folder", hint: "Downloaded images are saved here, one folder per object." },
    { key: "cache_dir", label: "Cache folder", type: "folder", hint: "Partial downloads wait here so they can resume; files are removed once saved." },
  ]],
  ["Downloads", [
    { key: "size_warning_gb", label: "Warn when a download is over", unit: "GB", step: "any" },
    { key: "parallel_downloads", label: "Downloads at once, per archive", unit: "", step: 1 },
    { key: "archive_timeout_s", label: "Archive search timeout", unit: "s", step: 1 },
  ]],
  ["Search defaults", [
    { key: "min_filters", label: "Minimum filters", unit: "", step: 1 },
    { key: "mix_instruments", label: "Allow mixing instruments and archives", type: "check" },
    { key: "hst_show_mosaics", label: "Also show HST mosaics (cut around the object)", type: "check" },
    { key: "pixel_scale_warn_ratio", label: "Warn when pixel scales in a mixed set differ by more than", unit: "×", step: "any" },
  ]],
  ["Processing defaults", [
    { key: "star_repair", label: "Repair star cores", type: "check" },
    { key: "star_repair_max_area", label: "Largest hole to repair", unit: "pixels", step: 1 },
    { key: "star_repair_max_area_bright", label: "Largest hole next to a bright star", unit: "pixels", step: 1,
      hint: "Larger holes are filled only when their edge is bright starlight, e.g. Pan-STARRS masks around bright stars." },
    { key: "cutout", label: "Cut around the object", type: "check" },
    { key: "cutout_default_arcmin", label: "Cutout box when the object's size is unknown", unit: "′", step: "any" },
  ]],
];
const settingsState = { defaults: null };

function buildSettingsForm() {
  $("settings-fields").replaceChildren(...SETTINGS_FIELDS.map(([legend, fields]) =>
    el("fieldset", {}, el("legend", {}, legend), ...fields.map(settingsField))));
}

function settingsField(f) {
  const id = `s-${f.key}`;
  const err = el("p", { class: "field-error error", hidden: true });
  if (f.type === "check") {
    return el("div", { class: "field", "data-field": f.key },
      el("label", { class: "check" }, el("input", { id, type: "checkbox", name: f.key }), f.label), err);
  }
  const input = f.type === "folder"
    ? el("input", { id, type: "text", name: f.key, class: "grow", autocomplete: "off", spellcheck: "false" })
    : el("input", { id, type: "number", name: f.key, step: f.step });
  const choose = f.type === "folder"
    ? el("button", { type: "button", class: "secondary", onclick: () => chooseFolder(f, input, err) }, "Choose…") : null;
  return el("div", { class: "field", "data-field": f.key },
    el("label", { for: id }, f.label),
    el("div", { class: "row" }, input, f.unit ? el("span", { class: "muted" }, f.unit) : null, choose),
    f.hint ? el("p", { class: "hint" }, f.hint) : null, err);
}

function fillSettings(values) {
  for (const [, fields] of SETTINGS_FIELDS) for (const f of fields) {
    const input = $(`s-${f.key}`);
    if (f.type === "check") input.checked = !!values[f.key]; else input.value = values[f.key];
  }
}

function showSettingsErrors(message, errors = {}) {
  $("settings-error").textContent = message || "";
  $("settings-error").hidden = !message;
  for (const node of document.querySelectorAll("#settings-fields .field")) {
    const msg = errors[node.dataset.field];
    const err = node.querySelector(".field-error");
    err.textContent = msg || ""; err.hidden = !msg;
    node.querySelector("input").classList.toggle("invalid", !!msg);
  }
}

async function chooseFolder(f, input, err) {
  const btn = input.parentElement.querySelector("button");
  btn.disabled = true; btn.textContent = "Choosing…";
  try {
    const r = await fetch("/api/choose-folder", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: `Choose the ${f.label.toLowerCase()}`, initial: input.value }) });
    const body = await r.json();
    if (!r.ok) { err.textContent = body.detail; err.hidden = false; return; }
    if (body.path) { input.value = body.path; err.hidden = true; input.classList.remove("invalid"); }
  } finally {
    btn.disabled = false; btn.textContent = "Choose…";
  }
}

$("open-settings").addEventListener("click", async () => {
  const body = await (await fetch("/api/settings")).json();
  settingsState.defaults = body.defaults;
  fillSettings(body.settings);
  showSettingsErrors();
  $("settings-dialog").showModal();
});

$("settings-cancel").addEventListener("click", () => $("settings-dialog").close());
$("settings-reset").addEventListener("click", () => { fillSettings(settingsState.defaults); showSettingsErrors(); });

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const changes = {};
  for (const [, fields] of SETTINGS_FIELDS) for (const f of fields) {
    const input = $(`s-${f.key}`);
    changes[f.key] = f.type === "check" ? input.checked : input.value;
  }
  $("settings-save").disabled = true;
  try {
    const r = await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) });
    const body = await r.json();
    if (!r.ok) { showSettingsErrors(body.detail.message || "The settings couldn't be saved.", body.detail.errors); return; }
    applySavedSettings(state.info.settings, body.settings);
    $("settings-dialog").close();
  } catch (err) {
    showSettingsErrors("The settings couldn't be saved: the connection to FITS-fetcher was lost.");
  } finally {
    $("settings-save").disabled = false;
  }
});

// REQ-66: a changed default is applied to the page; anything left unchanged keeps what you set for this search.
function applySavedSettings(old, now) {
  state.info.settings = now;
  const changed = (k) => old[k] !== now[k];
  if (changed("min_filters")) $("min-filters").value = now.min_filters;
  if (changed("mix_instruments")) $("mix").checked = now.mix_instruments;
  if (changed("hst_show_mosaics")) $("hst-mosaics").checked = now.hst_show_mosaics;
  if (changed("star_repair")) $("opt-repair").checked = now.star_repair;
  if (changed("cutout")) $("opt-cutout").checked = now.cutout;
  if (state.target) $("opt-cutout-label").textContent = `Cut around the object (${cutoutBox(state.target).toFixed(1)}′ box)`;
  updateSelection();
}

// ---------- quit (S-36) ----------
$("quit").addEventListener("click", async () => {
  if (downloading() && !confirm("A download is still running. Quit anyway?")) return;
  stopSearch();
  try { await fetch("/api/quit", { method: "POST" }); } catch (_) { /* server already gone */ }
  document.body.replaceChildren(el("main", {}, el("section", { class: "panel" },
    el("h2", {}, "FITS-fetcher has stopped."), el("p", { class: "muted" }, "You can close this tab."))));
});

init();
