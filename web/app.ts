type Choice = { code: string; name: string };
type Age = { start: number; end: number | null; label: string };
type Row = { age: Age; q: number; l: number; rate: number; e: number | null };
type Fan = { years: number[]; point: number[]; bounds: Record<string, [number[], number[]]>; origin: number; model: string; seed: number };
type Series = { country: string; name: string; region: string; year: number; sex: string; e0: number; table: Row[]; e0_history: number[]; deaths: number[]; exposure: number[]; forecast: Fan | null };
type Comparison = { source: string; vintage: string; panel_sha256: string; status: string; unit: string; year: number; years: number[]; ages: Age[]; lexis: number[][]; series: Series[] };
type Catalogue = { countries: Choice[]; years: number[]; vintage: string; cause_countries: Choice[]; forecast: { model: string; seed: number; origin: number } | null };
type Cohort = { birth: number; points: { age: number; year: number; rate: number | null }[]; truncated: boolean };
type Cause = { available: boolean; message: string; year: number; sex: string; name: string; all_deaths: number; unknown_age_deaths: number | null; groups: { id: string; label: string; count: number }[]; scenario: { baseline_e0: number; conditional_e0: number; by_age: number[]; ages: string[]; factor: number; residual_years: number } | null };
type Trace = { x: number[]; y: number[]; color: string; dash?: boolean };
type Band = { x: number[]; low: number[]; high: number[]; color: string; opacity: number };

const teal = "#116461", rust = "#b54e34";
const ns = "http://www.w3.org/2000/svg";
const byId = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing workspace element ${id}`);
  return node as T;
};
const form = byId<HTMLFormElement>("period-form");
const causeForm = byId<HTMLFormElement>("cause-form");
const controls = { left: byId<HTMLSelectElement>("left"), right: byId<HTMLSelectElement>("right"), sex: byId<HTMLSelectElement>("sex"), year: byId<HTMLSelectElement>("year") };
const notice = byId("notice");
const canvas = byId<HTMLCanvasElement>("lexis");
const birth = byId<HTMLInputElement>("birth");
let comparison: Comparison | null = null;
let periodRequest: AbortController | null = null;
let causeRequest: AbortController | null = null;
let cohortRequest: AbortController | null = null;

function svg<K extends keyof SVGElementTagNameMap>(kind: K, attrs: Record<string, string | number>): SVGElementTagNameMap[K] {
  const node = document.createElementNS(ns, kind);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

function text(tag: string, value: string, className?: string): HTMLElement {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

function option(select: HTMLSelectElement, value: string, label: string) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  select.append(node);
}

async function read<T>(path: string, query: Record<string, string>, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${path}?${new URLSearchParams(query)}`, { signal });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result as T;
}

function showError(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") return;
  notice.textContent = error instanceof Error ? error.message : "Request failed.";
}

function plot(target: string, title: string, traces: Trace[], bands: Band[] = [], unit = "", yBounds?: [number, number]) {
  const host = byId(target);
  host.replaceChildren();
  const values = traces.flatMap(t => t.y).concat(bands.flatMap(b => [...b.low, ...b.high]));
  if (!values.length) {
    host.append(text("p", "No eligible values for this selection.", "small"));
    return;
  }
  const xvalues = traces.flatMap(t => t.x).concat(bands.flatMap(b => b.x));
  const x0 = Math.min(...xvalues), x1 = Math.max(...xvalues);
  const y0 = yBounds?.[0] ?? Math.min(...values);
  const y1 = yBounds?.[1] ?? Math.max(...values);
  const w = 540, h = 235, l = 57, b = 196;
  const x = (v: number) => l + (w - l - 18) * (v - x0) / Math.max(1, x1 - x0);
  const y = (v: number) => b - (b - 27) * (v - y0) / Math.max(1e-9, y1 - y0);
  const root = svg("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": title });
  const caption = svg("text", { x: l, y: 17, "font-size": 12 });
  caption.textContent = unit;
  root.append(caption);
  for (let tick = 0; tick <= 4; tick++) {
    const value = y0 + (y1 - y0) * tick / 4;
    const pos = y(value);
    const label = svg("text", { x: l - 8, y: pos + 4, "text-anchor": "end", "font-size": 11 });
    label.textContent = value.toFixed(y1 - y0 <= 2 ? 2 : 0);
    root.append(svg("line", { x1: l, x2: w - 18, y1: pos, y2: pos, stroke: "#d7dfd6" }), label);
  }
  for (let tick = 0; tick <= 4; tick++) {
    const value = Math.round(x0 + (x1 - x0) * tick / 4);
    if (x1 === x0 && tick) break;
    const label = svg("text", { x: x(value), y: b + 21, "text-anchor": "middle", "font-size": 11 });
    label.textContent = String(value);
    root.append(label);
  }
  for (const band of bands) {
    const top = band.x.map((year, i) => `${x(year)},${y(band.high[i])}`);
    const bottom = band.x.map((year, i) => `${x(year)},${y(band.low[i])}`).reverse();
    root.append(svg("polygon", { points: [...top, ...bottom].join(" "), fill: band.color, opacity: band.opacity }));
  }
  for (const trace of traces) {
    root.append(svg("polyline", {
      points: trace.x.map((value, i) => `${x(value)},${y(trace.y[i])}`).join(" "),
      fill: "none", stroke: trace.color, "stroke-width": 2.6, "stroke-dasharray": trace.dash ? "6 5" : "",
    }));
  }
  host.append(root);
}

const stops = [[242,236,211],[179,207,173],[87,155,135],[34,109,113],[22,45,74]];
function heatColor(rate: number) {
  const value = Math.max(0, Math.min(1, (Math.log10(Math.max(rate, 1e-7)) + 5) / 5)) * 4;
  const low = Math.floor(value), high = Math.min(low + 1, 4);
  return `rgb(${stops[low].map((channel, i) => Math.round(channel + (value - low) * (stops[high][i] - channel))).join(",")})`;
}

function renderLexis() {
  if (!comparison) return;
  const { years, ages, lexis, year, series } = comparison;
  const w = Math.floor(canvas.clientWidth), h = Math.floor(canvas.clientHeight);
  if (!w || !h) return;
  const ratio = Math.min(2, devicePixelRatio || 1);
  canvas.width = w * ratio;
  canvas.height = h * ratio;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(ratio, ratio);
  const margin = 38, end = 17, top = 12, bottom = 29;
  const dx = (w - margin - end) / years.length, dy = (h - top - bottom) / ages.length;
  for (let i = 0; i < years.length; i++) {
    for (let j = 0; j < ages.length; j++) {
      ctx.fillStyle = heatColor(lexis[i][j]);
      ctx.fillRect(margin + i * dx, top + (ages.length - 1 - j) * dy, dx + .5, dy + .5);
    }
  }
  ctx.strokeStyle = "#b54e34";
  ctx.lineWidth = 2;
  ctx.strokeRect(margin + years.indexOf(year) * dx, top, dx, h - top - bottom);
  ctx.fillStyle = "#546764";
  ctx.font = "11px monospace";
  for (let tick = 0; tick <= 4; tick++) {
    const pos = Math.round((years.length - 1) * tick / 4);
    ctx.fillText(String(years[pos]), margin + pos * dx - 8, h - 9);
  }
  for (let j = 0; j < ages.length; j++) {
    if (j % 5 === 0 || j === ages.length - 1) ctx.fillText(ages[j].label, 1, top + (ages.length - 1 - j + .75) * dy);
  }
  canvas.setAttribute("aria-label", `Log mortality surface for ${series[0].name}, ${years[0]} to ${years.at(-1)}. CSV export includes the exact selected-year rates.`);
}

function render(result: Comparison) {
  comparison = result;
  byId("period-source").textContent = `${result.vintage} · Modeled historical estimates · Deaths per person-year · ${result.ages.length} intervals`;
  byId("lexis-title").textContent = `${result.series[0].name} mortality by age and period`;
  const cards = byId("cards");
  cards.replaceChildren();
  for (const [i, s] of result.series.entries()) {
    const card = text("article", "", "card");
    card.append(text("p", `${i === 0 ? "A" : "B"} / ${s.name}`, "eyebrow"), text("strong", `${s.e0.toFixed(2)} yr`),
      text("small", `Period life expectancy at birth · ${s.year}`));
    cards.append(card);
  }
  const gap = result.series[0].e0 - result.series[1].e0;
  const delta = text("article", "", "card");
  delta.append(text("p", "A − B / PERIOD DIFFERENCE", "eyebrow"), text("strong", `${gap >= 0 ? "+" : ""}${gap.toFixed(2)} yr`),
    text("small", "Same year, published sex and table method"));
  cards.append(delta);
  renderLexis();
  const colors = [teal, rust];
  const ages = result.ages.map(a => a.start);
  plot("survival", "Age-specific survivorship in the two selected populations", result.series.map((s, i) => ({
    x: ages, y: s.table.map(row => row.l / s.table[0].l), color: colors[i],
  })), [], "Survival probability · age in years", [0, 1]);
  plot("hazard", "Age-specific log central rates in the two selected populations", result.series.map((s, i) => ({
    x: ages, y: s.table.map(row => Math.log10(Math.max(1e-8, row.rate))), color: colors[i],
  })), [], "log₁₀ deaths per person-year · age in years");
  const traces = result.series.map((s, i) => ({ x: result.years, y: s.e0_history, color: colors[i] } as Trace));
  const bands: Band[] = [];
  result.series.forEach((s, i) => {
    if (!s.forecast) return;
    traces.push({ x: s.forecast.years, y: s.forecast.point, color: colors[i], dash: true });
    for (const level of ["0.95", "0.8", "0.5"]) {
      const [low, high] = s.forecast.bounds[level];
      bands.push({ x: s.forecast.years, low, high, color: colors[i], opacity: .13 });
    }
  });
  plot("fan", "Historical expectancy and forecast intervals", traces, bands, "Period e₀ · years");
  const future = result.series[0].forecast;
  byId("forecast-source").textContent = future
    ? `Teal = A, rust = B. Dashed = frozen ${future.model} forecast from ${future.origin}, seed ${future.seed}. Bands show 50%, 80%, and 95% intervals.`
    : "Teal = A, rust = B. Forecast unavailable. Start the server with a frozen checkpoint to see predictive paths.";
}

function selection(): Record<string, string> {
  return Object.fromEntries(Object.entries(controls).map(([key, field]) => [key, field.value]));
}

async function loadCohort() {
  if (!comparison || !birth.reportValidity()) return;
  cohortRequest?.abort();
  const request = new AbortController();
  cohortRequest = request;
  try {
    const values = await read<Cohort>("/api/cohort", { country: controls.left.value, sex: controls.sex.value, birth: birth.value }, request.signal);
    if (request.signal.aborted) return;
    const points = values.points.filter(p => p.rate !== null);
    plot("cohort", `Single-age period diagonal for ${values.birth}`, points.length ? [{
      x: points.map(p => p.age), y: points.map(p => Math.log10(Math.max(1e-8, p.rate!))), color: teal,
    }] : [], [], "log₁₀ deaths per person-year · age in years");
    if (points.length) byId("cohort").append(text("p", `${points.length} single-age cells, ${points[0].year}–${points.at(-1)!.year}. Lifetime expectancy unavailable for this truncated trace.`, "small"));
  } catch (error) { showError(error); }
}

async function loadPeriod() {
  periodRequest?.abort();
  cohortRequest?.abort();
  const request = new AbortController();
  periodRequest = request;
  notice.textContent = "Loading period comparison…";
  byId<HTMLButtonElement>("export").disabled = true;
  try {
    const result = await read<Comparison>("/api/compare", selection(), request.signal);
    if (request.signal.aborted) return;
    render(result);
    byId<HTMLButtonElement>("export").disabled = false;
    notice.textContent = "";
    void loadCohort();
  } catch (error) { showError(error); }
}

const causeColors = ["#48746d", "#a55740", "#284e6d", "#798b53", "#88657f", "#c79653", "#6d8d9a", "#aa9180", "#b1b8ac"];
async function loadCauses() {
  if (!causeForm.reportValidity()) return;
  if (!byId<HTMLSelectElement>("who-country").value) {
    byId("cause-view").textContent = "Build the WHO source panel to explore registration counts.";
    return;
  }
  causeRequest?.abort();
  const request = new AbortController();
  causeRequest = request;
  const query = Object.fromEntries(new FormData(causeForm).entries()) as Record<string, string>;
  query.approx = query.approx ? "1" : "0";
  notice.textContent = "Loading registration tabulation…";
  try {
    const response = await read<Cause>("/api/causes", query, request.signal);
    if (request.signal.aborted) return;
    const host = byId("cause-view");
    const scenario = byId("scenario");
    host.replaceChildren();
    scenario.replaceChildren(text("p", response.message, "small"));
    notice.textContent = "";
    if (!response.available) {
      host.append(text("p", response.message, "small"));
      return;
    }
    host.append(text("p", `${response.name}, ${response.year} · ${response.all_deaths.toLocaleString()} registered deaths · completeness unverified`, "small"));
    const bar = svg("svg", { viewBox: "0 0 1000 28", role: "img", "aria-label": "Shares of all registered causes of death" });
    let start = 0;
    const list = text("ul", "", "cause-list");
    response.groups.forEach((group, i) => {
      const share = group.count / response.all_deaths;
      const rect = svg("rect", { x: start * 1000, width: share * 1000, y: 0, height: 27, fill: causeColors[i] });
      bar.append(rect);
      start += share;
      const row = text("li", `${i + 1}. ${group.label}`);
      row.append(text("strong", `${(share * 100).toFixed(1)}% · ${group.count.toLocaleString()}`));
      list.append(row);
    });
    host.append(bar, list);
    if (response.unknown_age_deaths !== null) host.append(text("p", `Unknown age: ${response.unknown_age_deaths.toLocaleString()} deaths.`, "small"));
    if (response.scenario) {
      const values = response.scenario;
      scenario.append(text("p", `${values.baseline_e0.toFixed(2)} years → ${values.conditional_e0.toFixed(2)} years at rate multiplier ${values.factor.toFixed(2)}`));
      const chart = text("div", "");
      chart.id = "scenario-plot";
      scenario.append(chart);
      plot(chart.id, "Finite-change expectancy contributions by age interval", [{
        x: values.ages.map(age => Number.parseInt(age, 10)), y: values.by_age, color: teal,
      }], [], "Contribution to e₀ · years");
    }
  } catch (error) { showError(error); }
}

function exportCsv() {
  if (!comparison) return;
  const escape = (v: string | number | null) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const fields = ["country", "sex", "year", "age_start", "age_end", "deaths", "person_years", "rate", "q", "l", "e", "status", "vintage", "source", "panel_sha256"];
  const lines = [fields.join(",")];
  for (const s of comparison.series) {
    for (const [i, row] of s.table.entries()) {
      const age = comparison.ages[i];
      lines.push([s.country, s.sex, s.year, age.start, age.end, s.deaths[i], s.exposure[i], row.rate, row.q, row.l, row.e, comparison.status, comparison.vintage, comparison.source, comparison.panel_sha256].map(escape).join(","));
    }
  }
  const url = URL.createObjectURL(new Blob([lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" }));
  const download = document.createElement("a");
  download.href = url;
  download.download = `aevum-period-${comparison.year}.csv`;
  download.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function section(showCause: boolean) {
  byId("period").hidden = showCause;
  byId("cause").hidden = !showCause;
  byId("period-tab").setAttribute("aria-pressed", String(!showCause));
  byId("cause-tab").setAttribute("aria-pressed", String(showCause));
  notice.textContent = "";
  if (showCause) {
    periodRequest?.abort();
    cohortRequest?.abort();
    void loadCauses();
  } else {
    causeRequest?.abort();
    void loadPeriod();
  }
}

async function start() {
  const catalogue = await read<Catalogue>("/api/catalogue", {});
  for (const country of catalogue.countries) {
    option(controls.left, country.code, country.name);
    option(controls.right, country.code, country.name);
  }
  for (const year of [...catalogue.years].reverse()) option(controls.year, String(year), String(year));
  controls.left.value = "JPN";
  controls.right.value = "USA";
  controls.year.value = "2021";
  try {
    const saved = JSON.parse(localStorage.getItem("aevum.period.v1") ?? "{}");
    for (const [name, field] of Object.entries(controls)) {
      if (typeof saved[name] === "string" && [...field.options].some(o => o.value === saved[name])) field.value = saved[name];
    }
  } catch { notice.textContent = "Saved view could not be read."; }
  const who = byId<HTMLSelectElement>("who-country");
  for (const country of catalogue.cause_countries) option(who, country.code, country.name);
  const germany = catalogue.cause_countries.find(country => country.name === "Germany");
  if (germany) who.value = germany.code;
  for (let year = 2022; year >= 2008; year--) option(byId("who-year"), String(year), String(year));
  for (const [id, label] of Object.entries({ circulatory: "Circulatory", neoplasms: "Neoplasms", respiratory: "Respiratory", infectious: "Infectious", external: "External", special: "Special codes", other: "Other classified" })) {
    option(byId("who-cause"), id, label);
  }
  form.addEventListener("change", () => { void loadPeriod(); });
  form.addEventListener("submit", event => event.preventDefault());
  causeForm.addEventListener("change", () => { void loadCauses(); });
  byId("cause").addEventListener("change", event => {
    if ((event.target as HTMLInputElement).name === "approx") void loadCauses();
  });
  causeForm.addEventListener("submit", event => event.preventDefault());
  birth.addEventListener("change", () => { void loadCohort(); });
  byId("period-tab").addEventListener("click", () => section(false));
  byId("cause-tab").addEventListener("click", () => section(true));
  byId("export").addEventListener("click", exportCsv);
  byId("save").addEventListener("click", () => {
    try { localStorage.setItem("aevum.period.v1", JSON.stringify(selection())); notice.textContent = "View saved in this browser."; }
    catch (error) { showError(error); }
  });
  new ResizeObserver(renderLexis).observe(canvas);
  await loadPeriod();
}
void start().catch(showError);
