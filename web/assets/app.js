/* Reporte PI2 — lógica de la página.
   Datos precalculados: window.P1 (Parte I, diagnostics.py) y window.P2 (Parte II,
   clustering.py). Lo único que se recalcula en vivo es lo barato: KMeans++ y
   DBSCAN sobre una muestra en el espacio PCA, y el corte del dendrograma. */
(() => {
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (s) => document.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const nf = new Intl.NumberFormat("es-PE");
const nf1 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 2 });
const pct = (x, d = 1) => (100 * x).toLocaleString("es-PE", { maximumFractionDigits: d }) + " %";
const soles = (x) => x >= 1e9 ? "S/ " + nf1.format(x / 1e9) + " mil M"
  : x >= 1e6 ? "S/ " + nf1.format(x / 1e6) + " M" : "S/ " + nf.format(Math.round(x));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const series = () => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => css("--s" + i));
const tile = (v, l) => `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`;

function layout(extra = {}) {
  const text = css("--text"), text2 = css("--text-2"), grid = css("--border");
  const axis = { gridcolor: grid, zerolinecolor: grid, linecolor: grid, tickfont: { color: text2, size: 12 },
                 title: { font: { color: text2, size: 12 } }, automargin: true };
  const base = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, system-ui, sans-serif", color: text, size: 13 },
    margin: { l: 56, r: 16, t: 36, b: 44 },
    title: { font: { size: 14, color: text }, x: 0, xanchor: "left" },
    legend: { orientation: "h", y: -0.18, font: { color: text2, size: 12 } },
    hoverlabel: { bgcolor: css("--surface"), bordercolor: grid, font: { color: text } },
    xaxis: { ...axis }, yaxis: { ...axis },
  };
  for (const [k, v] of Object.entries(extra)) {
    base[k] = (typeof v === "object" && !Array.isArray(v) && base[k]) ? { ...base[k], ...v } : v;
  }
  if (extra.title && typeof extra.title === "string") base.title = { text: extra.title, font: { size: 14, color: text }, x: 0, xanchor: "left" };
  return base;
}
const CFG = { displayModeBar: false, responsive: true };
const plot = (id, data, lay) => Plotly.react(id, data, layout(lay), CFG);

// render registry: todo se vuelve a dibujar al cambiar el tema
const renderers = [];
const reg = (fn) => { renderers.push(fn); fn(); };

// seg buttons
function seg(el, onChange) {
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    el.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    onChange(b.dataset.v);
  }));
}
const debounce = (fn, ms = 60) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

// theme toggle
$("#theme").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  renderers.forEach((f) => f());
});
try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => renderers.forEach((f) => f()));

// ================================================================ PARTE I
const P1 = window.P1, P2 = window.P2;
const C = P1.contracts, ER = P1.entity_resolution, PART = P1.partitioning;

$("#hero-tiles").innerHTML = [
  tile(nf.format(C.n_items), "ítems adjudicados (2024)"),
  tile(nf.format(P1.buyers.n_buyer_ids), "entidades compradoras"),
  tile(nf.format(P1.artifacts.supplier_features), "proveedores (canónicos)"),
  tile(soles(C.amount_pen), "monto adjudicado"),
].join("");

// --- resolución de entidades
const merged = (ER.by_rule.exacto || 0) + (ER.by_rule.minhash || 0);
$("#er-tiles").innerHTML = [
  tile(nf.format(ER.n_ids), "IDs de proveedor (adjudicados + postores)"),
  tile(nf.format(merged), `fusiones (${ER.by_rule.exacto} exactas, ${ER.by_rule.minhash} MinHash)`),
  tile(nf.format(ER.by_type.consorcio), "IDs de consorcio (no se fusionan)"),
  tile(String(P1.buyers.same_name_groups.length), "nombres de entidad repetidos"),
].join("");
const typeLabels = { persona_juridica: "Persona jurídica (RUC 20)", consorcio: "Consorcio (código interno)",
  persona_natural: "Persona natural (RUC 10)", extranjero: "Extranjero", otro_ruc: "Otro RUC" };
reg(() => {
  const t = Object.entries(ER.by_type).sort((a, b) => a[1] - b[1]);
  plot("ch-er-types", [{ type: "bar", orientation: "h", x: t.map((d) => d[1]), y: t.map((d) => typeLabels[d[0]] || d[0]),
    marker: { color: css("--s1") }, hovertemplate: "%{y}: %{x:,} IDs<extra></extra>" }],
    { title: "IDs de proveedor por tipo", margin: { l: 170 }, xaxis: { title: { text: "IDs" } } });
});
$("#tb-er").innerHTML = "<tr><th>ID sin RUC</th><th>Nombre</th><th>RUC canónico</th><th>Regla</th></tr>" +
  ER.examples.slice(0, 8).map((r) => `<tr><td><code>${esc(r.supplier_id.replace("PE-RUC-", ""))}</code></td>
  <td>${esc(r.name_norm)}<br><span style="color:var(--muted)">→ ${esc(r.canonical_name)}</span></td>
  <td><code>${esc(r.canonical_id.replace("PE-RUC-", ""))}</code></td><td>${r.match_rule}</td></tr>`).join("");
const homs = P1.buyers.same_name_groups.map((g) => `«${g.name_norm}» (${g.departments.join(" y ")})`).join("; ");
$("#buyer-text").innerHTML = `Los ${nf.format(P1.buyers.n_buyer_ids)} <code>buyer_id</code> usan un único esquema
  (${P1.buyers.id_schemes.map((s) => s.scheme).join(", ")}) y, tras normalizar el nombre, solo
  ${P1.buyers.same_name_groups.length} nombres se repiten con distinto ID: ${esc(homs)}. Son <b>distritos homónimos de
  departamentos distintos</b>, es decir, entidades diferentes. No hay duplicados de compradores que resolver; la
  deduplicación se concentra en los proveedores.`;

// --- contratos
reg(() => {
  const f = Object.fromEntries(C.by_flag.map((r) => [String(r.has_contract), r]));
  const y = ["Ítems", "Monto"];
  const w = [f.true.n_items / C.n_items, f.true.amount_pen / C.amount_pen];
  plot("ch-contract", [
    { type: "bar", orientation: "h", name: "Con contrato", y, x: w, marker: { color: css("--s1") },
      hovertemplate: "%{y}: %{x:.1%} con contrato<extra></extra>" },
    { type: "bar", orientation: "h", name: "Sin contrato vinculado", y, x: w.map((v) => 1 - v), marker: { color: css("--s2") },
      hovertemplate: "%{y}: %{x:.1%} sin contrato<extra></extra>" },
  ], { title: "Adjudicaciones con y sin contrato", barmode: "stack", xaxis: { tickformat: ".0%" }, bargap: 0.45 });
  const cats = { goods: "Bienes", services: "Servicios", works: "Obras" };
  const bc = C.by_category.filter((r) => cats[r.category]);
  plot("ch-contract-cat", [{ type: "bar", x: bc.map((r) => cats[r.category]), y: bc.map((r) => r.pct_without_contract),
    marker: { color: css("--s2") }, text: bc.map((r) => pct(r.pct_without_contract)), textposition: "outside",
    hovertemplate: "%{x}: %{y:.1%} de ítems sin contrato<extra></extra>" }],
    { title: "% de ítems sin contrato por categoría", yaxis: { tickformat: ".0%", range: [0, 0.38] } });
  const without = f.false;
  $("#contract-text").innerHTML = `El ${pct(without.n_items / C.n_items)} de los ítems adjudicados no tiene contrato
    vinculado, pero esos ítems suman el <b>${pct(without.amount_pen / C.amount_pen)} del monto</b>: son más grandes
    (mediana ${soles(without.median_item)} frente a ${soles(f.true.median_item)}). En obras la brecha llega al
    ${pct(C.by_category.find((r) => r.category === "works").pct_without_contract, 0)}.`;
});

// --- artefactos
const artUse = {
  supplier_features: ["Vector por proveedor canónico (12+ variables)", "II · clustering"],
  buyer_features: ["Vector por entidad (9 variables)", "II · clustering"],
  inter_buyer_supplier: ["Matriz implícita entidad × proveedor (n.º ítems, procesos, monto)", "III · recomendación"],
  inter_buyer_family: ["Matriz entidad × familia UNSPSC", "III · contenido · VI · SVD"],
  edges_bipartite: ["Grafo dirigido entidad → proveedor", "IV · PageRank / HITS"],
  edges_coparticipation: ["Grafo proveedor — proveedor por co-participación", "V · comunidades · VI · embeddings"],
};
$("#tb-artifacts").innerHTML = "<tr><th>Artefacto</th><th>Contenido</th><th class='n'>Filas</th><th>Alimenta</th></tr>" +
  Object.entries(P1.artifacts).map(([k, n]) => `<tr><td><code>${k}</code></td><td>${artUse[k][0]}</td>
  <td class="n">${nf.format(n)}</td><td>${artUse[k][1]}</td></tr>`).join("");

// --- particionamiento
const gz = PART.gz, pr = PART.pruning, sh = PART.shuffle;
$("#par-cores").textContent = gz.default_parallelism;
reg(() => {
  plot("ch-gz", [{ type: "bar", x: ["1 partición (lectura del .gz)", `repartition(${gz.partitions_after_repartition})`],
    y: [gz.seconds_flatten_1_partition, gz.seconds_flatten_repartitioned], marker: { color: [css("--s2"), css("--s1")] },
    text: [gz.seconds_flatten_1_partition, gz.seconds_flatten_repartitioned].map((v) => nf2.format(v) + " s"),
    textposition: "outside", hovertemplate: "%{x}: %{y:.2f} s<extra></extra>" }],
    { title: "Aplanado de las 3 tablas sobre el JSON cacheado", yaxis: { title: { text: "segundos" },
      range: [0, gz.seconds_flatten_1_partition * 1.25] } });
});
$("#gz-text").innerHTML = `Spark lee un <code>.gz</code> con <b>${gz.partitions_after_read} sola partición</b>, porque
  gzip no es divisible: aunque haya ${gz.default_parallelism} núcleos, un solo hilo descomprime
  (${nf1.format(gz.seconds_read_gz)} s) y, sin reparticionar, un solo hilo haría todos los <code>explode</code>.
  Con <code>repartition(${gz.partitions_after_repartition})</code> el aplanado baja de
  ${nf2.format(gz.seconds_flatten_1_partition)} s a ${nf2.format(gz.seconds_flatten_repartitioned)} s
  (−${pct(1 - gz.seconds_flatten_repartitioned / gz.seconds_flatten_1_partition, 0)}).`;

const layoutNames = { partitioned: "partitionBy +<br>repartition (actual)", smallfiles: "partitionBy<br>sin repartition", flat: "Sin<br>particionar" };
const layoutOrder = ["flat", "smallfiles", "partitioned"];
let query = "cusco";
function renderLayouts() {
  const cols = [css("--s2"), css("--s4"), css("--s1")];
  const key = query === "cusco" ? "seconds_cusco" : "seconds_full_scan";
  const L = pr.layouts;
  plot("ch-layout-time", [{ type: "bar", x: layoutOrder.map((k) => layoutNames[k]), y: layoutOrder.map((k) => L[k][key]),
    marker: { color: cols }, text: layoutOrder.map((k) => nf2.format(L[k][key]) + " s"), textposition: "outside",
    hovertemplate: "%{x}: %{y:.3f} s<extra></extra>" }],
    { title: query === "cusco" ? "Tiempo: filtro buyer_department = 'CUSCO'" : "Tiempo: escaneo completo",
      yaxis: { title: { text: "segundos" }, range: [0, Math.max(...layoutOrder.map((k) => L[k][key])) * 1.3] } });
  const fk = query === "cusco" ? "files_read_cusco" : "files_total";
  plot("ch-layout-files", [{ type: "bar", x: layoutOrder.map((k) => layoutNames[k]), y: layoutOrder.map((k) => L[k][fk]),
    marker: { color: cols }, text: layoutOrder.map((k) => nf.format(L[k][fk])), textposition: "outside",
    hovertemplate: "%{x}: %{y} archivos<extra></extra>" }],
    { title: "Archivos Parquet leídos", yaxis: { type: "log", dtick: 1, title: { text: "archivos (escala log)" },
      range: [-0.2, Math.log10(Math.max(...layoutOrder.map((k) => L[k][fk]))) * 1.25] } });
}
seg($("#seg-query"), (v) => { query = v; renderLayouts(); });
reg(renderLayouts);

function showPlan(text, el, marks) {
  let h = esc(text);
  for (const m of marks) h = h.replace(new RegExp(m, "g"), (x) => `<mark>${x}</mark>`);
  $(el).innerHTML = h;
}
const planMarks = ["PartitionFilters: \\[[^\\n]*", "PushedFilters: \\[[^\\n]*", "\\(\\d+\\) Filter", "Filter \\(\\d+\\)"];
const plans = { partitioned: pr.plan_partitioned, flat: pr.plan_flat };
seg($("#seg-plan"), (v) => showPlan(plans[v], "#plan-view", planMarks));
showPlan(plans.partitioned, "#plan-view", planMarks);
const Lp = pr.layouts;
$("#pruning-text").innerHTML = `Con la tabla particionada, el filtro se convierte en <code>PartitionFilters</code>:
  el optimizador lo resuelve <b>antes de leer</b>, listando solo la carpeta <code>buyer_department=CUSCO</code>
  (${Lp.partitioned.files_read_cusco} de ${Lp.partitioned.files_total} archivos), y el nodo <code>Filter</code>
  desaparece del plan. Sin particionar, el filtro solo llega como <code>PushedFilters</code>: Parquet salta
  row-groups usando sus estadísticas min/max, pero hay que abrir los ${Lp.flat.files_total} archivos y volver a
  filtrar fila por fila. Resultado: ${nf2.format(Lp.flat.seconds_cusco)} s → ${nf2.format(Lp.partitioned.seconds_cusco)} s
  (${nf1.format(Lp.flat.seconds_cusco / Lp.partitioned.seconds_cusco)}× más rápido). Con 98 mil filas los tiempos son
  pequeños; lo que escala es el número de archivos leídos, que con el histórico completo sería 25 veces menor.`;

reg(() => {
  const t = sh.seconds_by_shuffle_partitions, ks = Object.keys(t);
  plot("ch-shuffle", [{ type: "bar", x: ks.map((k) => k + " particiones"), y: ks.map((k) => t[k]),
    marker: { color: ks.map((k) => k === "32" ? css("--s1") : css("--noise")) },
    text: ks.map((k) => nf2.format(t[k]) + " s"), textposition: "outside", hovertemplate: "%{x}: %{y:.2f} s<extra></extra>" }],
    { title: "Co-participación según spark.sql.shuffle.partitions", yaxis: { title: { text: "segundos" },
      range: [0, Math.max(...Object.values(t)) * 1.25] } });
});
const st = sh.seconds_by_shuffle_partitions;
$("#shuffle-text").innerHTML = `El grafo de co-participación es un <b>self-join</b> de los postores por
  <code>ocid</code>. El plan tiene ${sh.n_exchanges} <code>Exchange</code> (shuffles): el join con
  <code>supplier_map</code> va como <code>BroadcastHashJoin</code> (la tabla pequeña se copia a cada tarea y no se
  baraja), mientras que el self-join y los <code>groupBy</code> necesitan <code>SortMergeJoin</code> con
  <code>hashpartitioning(ocid)</code>. El valor por defecto de Spark, 200 particiones, tarda ${nf2.format(st["200"])} s
  frente a ${nf2.format(st["32"])} s con 32: en local, 200 tareas diminutas cuestan más en planificación que lo que
  paralelizan. AQE fusiona particiones después del shuffle, pero no evita esa sobrecarga en la fase de mapeo.
  Por eso <code>get_spark()</code> usa 32.`;
showPlan(sh.plan_coparticipation, "#plan-copart", ["BroadcastHashJoin[^\\n]*", "SortMergeJoin[^\\n]*", "Exchange \\(\\d+\\)"]);

// ================================================================ PARTE II
const ENT = { proveedores: P2.points.proveedores, entidades: P2.points.entidades };
const SUM = P2.summary;

// Nombres e interpretación de los clústeres del k elegido (ids de KMeans con
// random_state=42, ver src/parte2/clustering.py).
const NAMES = {
  proveedores: {
    0: ["Bienes, proveedor ocasional", "Un contrato de bienes, pocos rivales (4) y gana la mitad de lo que postula: pymes que entran al mercado público de forma esporádica."],
    1: ["Proveedores nacionales multicliente", "Mediana de 10 procesos con 7 entidades en 3 departamentos; ninguna entidad concentra sus ventas. Farmacéuticas, aseguradoras, combustibles, equipos."],
    2: ["Recurrentes locales", "2–3 procesos, 1–2 entidades, mezcla de bienes y servicios; dependencia media de su cliente principal."],
    3: ["Consorcios de obra", "81 % consorcios. Una obra, una entidad, 15 postores de mediana, tasa de éxito 1: vehículos formados para una sola licitación."],
    4: ["Servicios de contrato único", "El grupo más numeroso: un servicio, un cliente, gana lo que postula. Mucho volumen de actores, poco monto."],
    5: ["Contratación directa", "Todo su monto llega por contratación directa, con 2 postores de mediana. Incluye exclusividades (medicamentos, equipos) y emergencias."],
  },
  entidades: {
    0: ["Pequeñas y concentradas", "Pocas compras (3 procesos) con buena competencia, pero el 77 % del monto va a un solo proveedor: municipios distritales pequeños."],
    1: ["Grandes compradores", "57 procesos y 52 proveedores de mediana: ministerios, EsSalud, Provías, Petroperú. El 23 % de las entidades gasta el 81 % del monto."],
    2: ["Directa + postor único", "La mitad de los ítems por contratación directa y 40 % con un solo postor. Es el segmento a priorizar en una revisión."],
    3: ["Compradores medianos", "14 procesos, competencia normal (8 postores), concentración moderada: el comportamiento típico."],
    4: ["Baja competencia", "40 % de ítems con un solo postor y 3 postores de mediana, sin contratación directa; más presentes en Loreto y San Martín."],
  },
};
const fmtVal = (col, v) => col.startsWith("pct_") || col.endsWith("_share") || col === "win_rate" ? pct(v, 0)
  : col.includes("amount") ? soles(v) : nf1.format(v);

// ?actor=entidades abre todos los módulos con las entidades seleccionadas
const actor0 = new URLSearchParams(location.search).get("actor") === "entidades" ? "entidades" : "proveedores";
const state = { vars: actor0, km: actor0, db: actor0, ward: actor0, out: actor0 };
document.querySelectorAll(".seg-entity").forEach((el) => {
  el.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.v === actor0));
  seg(el, (v) => { state[el.dataset.target] = v; ENTITY_RENDER[el.dataset.target](); });
});
const ENTITY_RENDER = {};

// --- variables + PCA
ENTITY_RENDER.vars = () => {
  const s = SUM[state.vars];
  $("#tb-vars").innerHTML = "<tr><th>Variable</th><th>Columna</th><th>Transformación</th></tr>" +
    s.variables.map((v) => `<tr><td>${v.label}</td><td><code>${v.col}</code></td><td>${v.transform === "log" ? "log1p → z" : "z"}</td></tr>`).join("");
  const ex = s.pca.explained, cum = ex.map((_, i) => ex.slice(0, i + 1).reduce((a, b) => a + b, 0));
  plot("ch-pca", [
    { type: "bar", x: ex.map((_, i) => "PC" + (i + 1)), y: ex, name: "Varianza explicada",
      marker: { color: ex.map((_, i) => i < s.pca.n_components ? css("--s1") : css("--noise")) },
      hovertemplate: "%{x}: %{y:.1%} (acum. %{customdata:.1%})<extra></extra>", customdata: cum },
  ], { title: `PCA: ${s.pca.n_components} componentes retenidas (≥ 90 %)`, yaxis: { tickformat: ".0%" }, showlegend: false });
  const labs = Object.keys(s.pca.loadings_pc1);
  plot("ch-loadings", [
    { type: "bar", orientation: "h", name: "PC1", y: labs, x: labs.map((l) => s.pca.loadings_pc1[l]), marker: { color: css("--s1") } },
    { type: "bar", orientation: "h", name: "PC2", y: labs, x: labs.map((l) => s.pca.loadings_pc2[l]), marker: { color: css("--s2") } },
  ], { title: "Cargas de PC1 y PC2", barmode: "group", margin: { l: 220 }, height: 60 + labs.length * 34,
       yaxis: { autorange: "reversed" }, legend: { y: -0.12 } });
  $("#pca-text").textContent = ["proveedores", "entidades"].map((e) =>
    `${e}: ${SUM[e].pca.n_components} de ${SUM[e].pca.explained.length}`).join("; ");
};
reg(() => ENTITY_RENDER.vars());

// --- KMeans++ en JS
function rng(seed) { return () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const d2 = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; s += d * d; } return s; };

function kmeans(X, k, nInit = 4, seed = 42) {
  const R = rng(seed); let best = null;
  for (let run = 0; run < nInit; run++) {
    // k-means++: cada nuevo centro con probabilidad ∝ D(x)²
    const C = [X[Math.floor(R() * X.length)].slice()];
    const D = X.map((x) => d2(x, C[0]));
    while (C.length < k) {
      const tot = D.reduce((a, b) => a + b, 0); let r = R() * tot, i = 0;
      while (r > D[i] && i < X.length - 1) { r -= D[i]; i++; }
      C.push(X[i].slice());
      for (let j = 0; j < X.length; j++) D[j] = Math.min(D[j], d2(X[j], C[C.length - 1]));
    }
    const lab = new Int32Array(X.length); let inertia = 0;
    for (let it = 0; it < 100; it++) {
      let moved = 0; inertia = 0;
      for (let j = 0; j < X.length; j++) {
        let bi = 0, bd = Infinity;
        for (let c = 0; c < k; c++) { const d = d2(X[j], C[c]); if (d < bd) { bd = d; bi = c; } }
        if (lab[j] !== bi) { lab[j] = bi; moved++; } inertia += bd;
      }
      const S = Array.from({ length: k }, () => new Float64Array(X[0].length)), n = new Int32Array(k);
      for (let j = 0; j < X.length; j++) { n[lab[j]]++; const s = S[lab[j]]; for (let i = 0; i < s.length; i++) s[i] += X[j][i]; }
      for (let c = 0; c < k; c++) if (n[c]) C[c] = Array.from(S[c], (v) => v / n[c]);
      if (!moved && it) break;
    }
    if (!best || inertia < best.inertia) best = { lab, C, inertia };
  }
  // reordenar por tamaño: el color sigue al grupo más grande, no a un id arbitrario
  const size = Array(k).fill(0); best.lab.forEach((l) => size[l]++);
  const order = size.map((s, i) => [s, i]).sort((a, b) => b[0] - a[0]).map((d) => d[1]);
  const remap = Array(k); order.forEach((o, i) => (remap[o] = i));
  return { lab: Array.from(best.lab, (l) => remap[l]), C: order.map((o) => best.C[o]), size: order.map((o) => size[o]) };
}

function scatterTraces(E, labels, nameOf, colorOf) {
  const groups = [...new Set(labels)].sort((a, b) => a - b), tr = [];
  for (const g of groups) {
    const idx = labels.map((l, i) => (l === g ? i : -1)).filter((i) => i >= 0);
    tr.push({ type: "scattergl", mode: "markers", name: nameOf(g), x: idx.map((i) => E.z[i][0]), y: idx.map((i) => E.z[i][1]),
      marker: { size: 6, color: colorOf(g), opacity: g === -1 ? 0.45 : 0.75, line: { width: 0 } },
      customdata: idx.map((i) => [E.label[i], E.group[i], soles(E.amount[i])]),
      hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]} · %{customdata[2]}<extra>" + esc(nameOf(g)) + "</extra>" });
  }
  return tr;
}

const kSlider = $("#k-slider");
function renderKM() {
  const E = ENT[state.km], s = SUM[state.km], k = +kSlider.value, col = series();
  $("#k-out").textContent = k; $("#km-n").textContent = nf.format(E.z.length);
  const res = kmeans(E.z, k);
  const tr = scatterTraces(E, res.lab, (g) => `Grupo ${g + 1} (${pct(res.size[g] / E.z.length, 0)})`, (g) => col[g % 8]);
  tr.push({ type: "scatter", mode: "markers+text", x: res.C.map((c) => c[0]), y: res.C.map((c) => c[1]),
    text: res.C.map((_, i) => String(i + 1)), textfont: { color: css("--bg"), size: 11 }, showlegend: false, hoverinfo: "skip",
    marker: { size: 18, color: css("--text"), line: { width: 2, color: css("--bg") } } });
  plot("ch-km", tr, { title: `KMeans++ con k = ${k} (vista PC1 × PC2)`, xaxis: { title: { text: "PC1" } }, yaxis: { title: { text: "PC2" } } });
  const ks = s.k_selection.map((r) => r.k), mk = (arr, name, fmt) => [
    { type: "scatter", mode: "lines+markers", x: ks, y: arr, line: { color: css("--s1"), width: 2 }, marker: { size: 8, color: css("--s1") },
      hovertemplate: `k=%{x}: %{y${fmt}}<extra></extra>`, name },
    { type: "scatter", mode: "markers", x: [k], y: [arr[ks.indexOf(k)]], marker: { size: 14, color: "rgba(0,0,0,0)", line: { width: 2, color: css("--text") } },
      hoverinfo: "skip", showlegend: false },
    { type: "scatter", mode: "markers", x: [s.k_best], y: [arr[ks.indexOf(s.k_best)]], marker: { size: 10, color: css("--s2"), symbol: "diamond" },
      name: "k elegido", hovertemplate: "k elegido = %{x}<extra></extra>" }];
  plot("ch-elbow", mk(s.k_selection.map((r) => r.inertia), "Inercia", ":,.0f"),
    { title: "Codo: inercia (población completa)", showlegend: false, xaxis: { dtick: 1, title: { text: "k" } } });
  plot("ch-sil", mk(s.k_selection.map((r) => r.silhouette), "Silueta", ":.3f"),
    { title: "Silueta (muestra de 10 000)", showlegend: false, xaxis: { dtick: 1, title: { text: "k" } } });
}
kSlider.addEventListener("input", debounce(renderKM));

ENTITY_RENDER.km = () => {
  const s = SUM[state.km], col = series();
  kSlider.value = s.k_best; $("#kbest-label").textContent = `k = ${s.k_best}`;
  renderKM();
  const P = s.kmeans_profiles, vars = s.variables, names = NAMES[state.km];
  const zs = vars.map((v) => P.map((p) => p.z[v.col]));
  plot("ch-heat", [{ type: "heatmap", z: zs, x: P.map((p) => `${p.cluster + 1} · ${names[p.cluster][0]}`), y: vars.map((v) => v.label),
    zmin: -2, zmax: 2, zmid: 0, colorscale: [[0, css("--div-neg")], [0.5, css("--div-mid")], [1, css("--div-pos")]],
    xgap: 2, ygap: 2, colorbar: { title: { text: "z medio", side: "right" }, thickness: 10, tickfont: { color: css("--text-2") } },
    customdata: vars.map((v) => P.map((p) => fmtVal(v.col, p.median[v.col]))),
    hovertemplate: "%{x}<br>%{y}<br>z medio %{z:.2f} · mediana %{customdata}<extra></extra>" }],
    { title: "Perfil de cada clúster: desviación media respecto de la población (z)", margin: { l: 230, b: 120 },
      height: 120 + vars.length * 30, xaxis: { tickangle: -25 }, yaxis: { autorange: "reversed" } });
  $("#km-cards").innerHTML = P.map((p) => `<div class="card"><div class="h"><span class="sw" style="background:${col[p.cluster % 8]}"></span>
    ${p.cluster + 1} · ${names[p.cluster][0]}</div>
    <div class="m">${pct(p.share)} de los actores · <b>${pct(p.amount_share)} del monto</b></div>
    <div>${names[p.cluster][1]}</div>
    <div class="m">Ej.: ${p.examples.slice(0, 3).map(esc).join(" · ")}</div></div>`).join("");
  const sil = (kk) => s.k_selection.find((r) => r.k === kk).silhouette.toFixed(2);
  $("#km-interp").innerHTML = state.km === "proveedores" ? `
    <p><b>Elección de k.</b> La silueta máxima está en k = 2 (${sil(2)}), pero ese corte solo separa
      «un proceso» de «varios», algo que ya se sabe. La curva de inercia no tiene un codo nítido (el espacio es casi
      continuo). Se eligió <b>k = 6</b>: la silueta (${sil(6)}) queda cerca del máximo local de k = 4
      (${sil(4)}) y separa dos grupos que k = 4 mezcla, los <i>multicliente nacionales</i> y los
      <i>recurrentes locales</i>, que se comportan distinto en monto y dependencia del cliente.</p>
    <p><b>Lectura.</b> La concentración salta a la vista: los <b>consorcios de obra</b> son el 17 % de los proveedores y
      se llevan el 57 % del monto; los <b>multicliente</b> son el 3 % y se llevan el 19 %. Los dos grupos de «un solo
      contrato» (servicios y bienes) reúnen al 58 % de los proveedores con apenas el 8 % del monto.</p>
    <p>El slider recalcula KMeans++ en vivo sobre una muestra de ${nf.format(ENT.proveedores.z.length)} puntos (la
      muestra sobrerrepresenta el ruido de HDBSCAN para que los atípicos se vean), así que sus grupos no tienen por qué
      coincidir uno a uno con los perfiles fijos de abajo, calculados sobre los 49 569.</p>` : `
    <p><b>Elección de k.</b> La silueta es baja en todo el rango (≤ ${sil(2)}): las entidades forman un
      continuo de tamaño más que grupos separados. Se eligió <b>k = 5</b> (silueta ${sil(5)}, máximo local)
      porque es el primer k que separa la <i>forma</i> de comprar del tamaño: con k = 3 la contratación directa y el
      postor único quedan en un mismo grupo.</p>
    <p><b>Lectura.</b> Los <b>grandes compradores</b> (23 %) concentran el 81 % del gasto. Dos grupos pequeños
      interesan para la detección de anomalías: <b>directa + postor único</b> (105 entidades) y <b>baja competencia</b>
      (288), donde el 40 % de los ítems tuvo un solo postor. El grupo de <b>pequeñas y concentradas</b> (24 %) muestra
      otra forma de dependencia: buena competencia por proceso, pero el 77 % del monto termina en un proveedor.</p>`;
};
reg(() => ENTITY_RENDER.km());

// --- DBSCAN en JS
const epsS = $("#eps-slider"), msS = $("#ms-slider");
const kdCache = {};
function kDistance(E, ms) {
  const key = E.entity + ms; if (kdCache[key]) return kdCache[key];
  const n = E.z.length, out = new Float64Array(n), row = new Float64Array(n);
  for (let i = 0; i < n; i++) { for (let j = 0; j < n; j++) row[j] = d2(E.z[i], E.z[j]); out[i] = Math.sqrt(row.sort()[ms - 1]); }
  const curve = Array.from(out).sort((a, b) => a - b);
  // codo: máxima distancia a la recta entre extremos (igual que en Python)
  let knee = 0, best = -Infinity;
  for (let i = 0; i < n; i++) { const x = i / (n - 1), y = (curve[i] - curve[0]) / (curve[n - 1] - curve[0]); if (x - y > best) { best = x - y; knee = i; } }
  return (kdCache[key] = { curve, eps: curve[knee] });
}
function dbscan(X, eps, ms) {
  const n = X.length, e2 = eps * eps, lab = new Int32Array(n).fill(-2), nb = [];
  for (let i = 0; i < n; i++) { const a = []; for (let j = 0; j < n; j++) if (d2(X[i], X[j]) <= e2) a.push(j); nb.push(a); }
  let c = 0;
  for (let i = 0; i < n; i++) {
    if (lab[i] !== -2) continue;
    if (nb[i].length < ms) { lab[i] = -1; continue; }
    lab[i] = c; const q = [...nb[i]];
    while (q.length) { const j = q.pop(); if (lab[j] === -1) lab[j] = c; if (lab[j] !== -2) continue;
      lab[j] = c; if (nb[j].length >= ms) q.push(...nb[j]); }
    c++;
  }
  return Array.from(lab);
}
function renderDB() {
  const E = ENT[state.db], eps = +epsS.value, ms = +msS.value, col = series();
  $("#eps-out").textContent = nf2.format(eps); $("#ms-out").textContent = ms;
  const lab = dbscan(E.z, eps, ms);
  // los clústeres se ordenan por tamaño; los que pasan de 7 se agrupan en "otros"
  const cnt = {}; lab.forEach((l) => { if (l >= 0) cnt[l] = (cnt[l] || 0) + 1; });
  const order = Object.keys(cnt).map(Number).sort((a, b) => cnt[b] - cnt[a]);
  const rank = Object.fromEntries(order.map((l, i) => [l, Math.min(i, 7)]));
  const shown = lab.map((l) => (l === -1 ? -1 : rank[l]));
  const nOther = order.length > 7 ? order.length - 7 : 0;
  plot("ch-db", scatterTraces(E, shown, (g) => g === -1 ? "Ruido" : g === 7 ? `Otros ${nOther} clústeres` : `Clúster ${g + 1}`,
    (g) => g === -1 ? css("--noise") : col[g]),
    { title: `DBSCAN (eps = ${nf2.format(eps)}, min_samples = ${ms})`, xaxis: { title: { text: "PC1" } }, yaxis: { title: { text: "PC2" } } });
  const kd = kDistance(E, ms);
  const step = Math.max(1, Math.floor(kd.curve.length / 400)), xs = [], ys = [];
  for (let i = 0; i < kd.curve.length; i += step) { xs.push(i); ys.push(kd.curve[i]); }
  plot("ch-kdist", [
    { type: "scatter", mode: "lines", x: xs, y: ys, line: { color: css("--s1"), width: 2 }, name: "k-distancia",
      hovertemplate: "punto %{x}: %{y:.2f}<extra></extra>" },
    { type: "scatter", mode: "lines", x: [0, kd.curve.length], y: [eps, eps], line: { color: css("--s2"), width: 2, dash: "dot" }, name: "eps actual", hoverinfo: "skip" },
  ], { title: `Curva de ${ms}-distancias (codo ≈ ${nf2.format(kd.eps)}; punteada = eps actual)`,
       xaxis: { title: { text: "puntos ordenados" } }, yaxis: { title: { text: "distancia" } }, showlegend: false });
  const noise = lab.filter((l) => l === -1).length;
  $("#db-tiles").innerHTML = tile(String(order.length), "clústeres") + tile(pct(noise / lab.length), "ruido") +
    tile(nf2.format(kd.eps), "codo de k-distancias en la muestra");
}
epsS.addEventListener("input", debounce(renderDB, 120)); msS.addEventListener("input", debounce(renderDB, 150));

ENTITY_RENDER.db = () => {
  const E = ENT[state.db], s = SUM[state.db];
  // valor inicial: el eps elegido sobre la población completa (Python)
  msS.value = E.min_samples_default; epsS.value = E.eps_default;
  renderDB();
  const h = s.hdbscan, keyVars = state.db === "proveedores"
    ? ["total_amount", "n_processes_won", "pct_direct", "pct_goods", "pct_works", "avg_competitors", "win_rate"]
    : ["total_amount", "n_processes", "pct_direct", "avg_competitors", "pct_single_bidder", "top_supplier_share"];
  const lab = Object.fromEntries(s.variables.map((v) => [v.col, v.label.replace(" (log)", "")]));
  $("#tb-hdb").innerHTML = `<tr><th>Clúster</th><th class="n">Actores</th><th class="n">% monto</th>${keyVars.map((v) => `<th class="n">${lab[v]} (mediana)</th>`).join("")}</tr>` +
    h.profiles.map((p) => `<tr><td>${p.cluster === -1 ? "<b>Ruido</b>" : p.cluster + 1}</td><td class="n">${nf.format(p.size)}</td>
    <td class="n">${pct(p.amount_share)}</td>${keyVars.map((v) => `<td class="n">${fmtVal(v, p.median[v])}</td>`).join("")}</tr>`).join("");
  const d = s.dbscan;
  $("#db-interp").innerHTML = state.db === "proveedores" ? `
    <p><b>HDBSCAN</b> (min_cluster_size = ${h.min_cluster_size}, min_samples = ${h.min_samples}) encuentra ${h.n_clusters}
      zonas densas y marca como ruido al <b>${pct(h.noise_share)}</b> de los proveedores, que suman el
      <b>${pct(h.noise_amount_share)} del monto</b>. Las zonas densas son «pilas» de actores casi idénticos: un proceso,
      100 % bienes o 100 % servicios, la misma competencia. Por eso el ruido no es «raro» en sentido negativo: es todo
      el que tiene un perfil <i>mixto</i> (vende bienes y servicios, a varias entidades), que es justamente donde está
      el dinero. Con min_cluster_size pequeño las pilas se fragmentan en decenas de micro-clústeres (38 con 250), sin
      ganar interpretabilidad. ARI frente a KMeans: ${nf2.format(h.ari_vs_kmeans)}.</p>
    <p><b>Dos zonas densas valen la pena:</b> servicios con <b>un solo postor</b> y monto mínimo, y contratación directa
      con un solo postor. Son microcompras sin competencia que KMeans diluye dentro de grupos más grandes.</p>
    <p><b>DBSCAN</b> sobre la población completa (eps = ${nf2.format(d.eps)} por el codo de k-distancias,
      min_samples = ${d.min_samples} = 2 × dimensiones) da ${d.n_clusters} clústeres y ${pct(d.noise_share)} de ruido:
      un único eps no sirve para pilas muy densas y periferias dispersas a la vez, y esa es la razón de usar HDBSCAN.</p>
    <p><b>En vivo.</b> El valor inicial es ese mismo eps. La muestra es ~20 veces menos densa, así que su codo de
      k-distancias sale mayor (~2) y, con él, todo se funde en un único clúster. Moverse entre 0.6 y 1.2 muestra lo
      sensible que es DBSCAN a eps: el ruido baja del 35 % al 18 % y los clústeres cambian de forma.</p>` : `
    <p><b>HDBSCAN</b> encuentra una gran zona densa (las entidades «normales»), un micro-grupo de 15 entidades con una
      sola compra con postor único, y <b>${pct(h.noise_share)} de ruido</b> (${h.profiles.find((p) => p.cluster === -1).size}
      entidades) que concentra el ${pct(h.noise_amount_share)} del monto. Su perfil mediano combina más contratación
      directa (25 %), menos postores (3.5) y más postor único (32 %) que el resto. Es una señal más fina que la de
      KMeans porque no obliga a cada entidad a pertenecer a un grupo.</p>
    <p>ARI frente a KMeans = ${nf2.format(h.ari_vs_kmeans)}: coinciden poco porque responden preguntas distintas. KMeans
      reparte un continuo en tramos y HDBSCAN separa «núcleo vs. periferia». <b>DBSCAN</b> (eps = ${nf2.format(d.eps)})
      da el mismo resultado: ${d.n_clusters} clústeres y ${pct(d.noise_share)} de ruido.</p>`;
};
reg(() => ENTITY_RENDER.db());

// --- dendrograma
const cutS = $("#cut-slider");
function renderWard() {
  const s = SUM[state.ward], dn = s.ward.dendrogram, maxH = Math.max(...dn.dcoord.map((d) => d[1]));
  const h = (+cutS.value / 100) * maxH * 1.02;
  const merges = dn.dcoord.map((d) => d[1]);
  const nCl = 1 + merges.filter((m) => m > h).length;
  $("#cut-out").textContent = `${nf1.format(h)} → ${nCl} grupos`;
  const xs = [], ys = [];
  dn.icoord.forEach((ic, i) => { xs.push(...ic, null); ys.push(...dn.dcoord[i], null); });
  plot("ch-dendro", [
    { type: "scatter", mode: "lines", x: xs, y: ys, line: { color: css("--text-2"), width: 1.5 }, hoverinfo: "skip", showlegend: false },
    { type: "scatter", mode: "lines", x: [0, dn.ivl.length * 10], y: [h, h], line: { color: css("--s2"), width: 2, dash: "dash" },
      name: `corte: ${nCl} grupos`, hoverinfo: "skip" },
  ], { title: `Ward sobre muestra de ${nf.format(s.ward.sample)} (40 hojas; entre paréntesis, n.º de actores)`,
       xaxis: { tickvals: dn.ivl.map((_, i) => 5 + 10 * i), ticktext: dn.ivl, tickangle: -60, tickfont: { size: 10 }, showgrid: false },
       yaxis: { title: { text: "distancia Ward" } }, margin: { b: 90 } });
}
cutS.addEventListener("input", renderWard);
ENTITY_RENDER.ward = () => {
  const s = SUM[state.ward], dn = s.ward.dendrogram, merges = dn.dcoord.map((d) => d[1]).sort((a, b) => b - a);
  const maxH = merges[0], hk = (merges[s.k_best - 2] + merges[s.k_best - 1]) / 2;
  cutS.value = Math.round((hk / (maxH * 1.02)) * 100);
  renderWard();
  $("#ward-interp").innerHTML = `<p>El enlace de Ward minimiza el aumento de varianza intra-grupo en cada fusión: es el
    análogo jerárquico de KMeans. Con un costo de O(n²) en memoria se aplica a una muestra de ${nf.format(s.ward.sample)}.
    Cortado en k = ${s.k_best}, su partición coincide con la de KMeans con <b>ARI = ${nf2.format(s.ward.ari_vs_kmeans)}</b>.</p>` +
    (state.ward === "proveedores"
      ? `<p>El dendrograma muestra <b>dos grandes ramas</b> que se unen muy arriba: la de los actores de un solo proceso y
         la de los recurrentes (la misma división de k = 2 con máxima silueta). Dentro de cada rama las fusiones ocurren a
         alturas parecidas, lo que explica por qué no hay un codo nítido. ARI ≈ 0.6 significa que las tipologías son
         <b>estables al método</b> en su núcleo y difieren en los bordes (perfiles mixtos).</p>`
      : `<p>En entidades el árbol es más «escalonado», sin un salto que destaque: es la firma de un continuo. El ARI
         moderado (≈ 0.5) confirma que los cortes intermedios (k = 3–5) dependen del método. Lo robusto es la separación
         entre grandes compradores y el resto, y la existencia de una periferia de baja competencia.</p>`);
};
reg(() => ENTITY_RENDER.ward());

// --- outliers
ENTITY_RENDER.out = () => {
  const s = SUM[state.out], names = NAMES[state.out];
  $("#tb-out").innerHTML = `<tr><th>#</th><th>Actor</th><th>${state.out === "proveedores" ? "Tipo" : "Departamento"}</th>
    <th class="n">Monto</th><th>Clúster KMeans</th><th>Variables más extremas (z)</th></tr>` +
    s.outliers.slice(0, 20).map((o, i) => `<tr><td>${i + 1}</td><td>${esc(o.label)}</td><td>${esc(typeLabels[o.group] || o.group)}</td>
    <td class="n">${soles(o.total_amount)}</td><td>${o.kmeans_cluster + 1} · ${names[o.kmeans_cluster][0]}</td>
    <td>${o.drivers.map((d) => `<span class="chip">${esc(d.var.replace(" (log)", ""))} ${d.z > 0 ? "+" : ""}${nf1.format(d.z)}</span>`).join("")}</td></tr>`).join("");
  $("#out-interp").innerHTML = `<p><b>Método.</b> Se toman los puntos que HDBSCAN marca como ruido y se ordenan por su
    distancia al centroide KMeans más cercano: así se combinan «fuera de toda zona densa» y «lejos de toda tipología».
    Cada fila muestra las tres variables con mayor |z| como explicación.</p>` + (state.out === "proveedores"
    ? `<p><b>Lectura.</b> Los proveedores más atípicos son <b>proveedores nacionales</b> con cientos de procesos y clientes en casi
       todos los departamentos (diagnóstico clínico, telecomunicaciones, maquinaria, farmacéuticas, seguros). Su
       atipicidad es de <i>escala y alcance</i>, no de forma de contratar: son los candidatos naturales a nodos centrales
       en el PageRank de la Parte IV.</p>`
    : `<p><b>Lectura.</b> En entidades, lo que más separa es la relación <b>proveedores por proceso</b>: programas que
       adjudican un proceso entre decenas de proveedores (compras por ítems, como alimentos o material educativo) o, al
       revés, entidades que repiten el mismo proveedor en todos sus procesos (z muy negativo). También aparecen
       entidades con alta contratación directa y montos altos, que conviene leer junto con su contexto (emergencias,
       reconstrucción).</p>`);
};
reg(() => ENTITY_RENDER.out());
})();
