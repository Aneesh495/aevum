const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const url = process.env.AEVUM_QA_URL || "http://127.0.0.1:8078";
const output = process.argv[2];
if (!output) throw new Error("Specify an output directory");
fs.mkdirSync(output, { recursive: false });

async function qa() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(String(error)));
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  try {
    await page.goto(url);
    await page.locator("#cards .card").first().waitFor();
    await page.getByRole("img", { name: "Historical expectancy and forecast intervals" }).waitFor();
    assert.match(await page.locator("#forecast-source").innerText(), /frozen structured forecast/);
    assert.equal(await page.locator("#cards .card").count(), 3);
    assert.match(await page.locator("#period-source").innerText(), /Modeled historical estimates/);
    await page.locator("#cohort svg").waitFor();
    await page.screenshot({ path: path.join(output, "period-desktop.png"), fullPage: true });
    await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement.textContent), "Skip to research workspace");
    await page.locator("#right").selectOption("SWE");
    await page.waitForFunction(() => document.querySelector("#cards").textContent.includes("Sweden"));
    await page.getByRole("button", { name: "Save view" }).click();
    await page.reload();
    await page.waitForFunction(() => document.querySelector("#cards").textContent.includes("Sweden"));
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export CSV" }).click();
    const csv = fs.readFileSync(await (await download).path(), "utf8");
    assert.match(csv, /person_years/);
    assert.match(csv, /WPP2024-original/);
    assert.equal(csv.trim().split("\n").length, 41);
    const trials = await page.evaluate(async () => {
      const field = document.querySelector("#year");
      async function change(year) {
        const begin = performance.now();
        await new Promise((resolve, reject) => {
          const observer = new MutationObserver(() => {
            if (document.querySelector("#cards").textContent.includes(year)) {
              observer.disconnect();
              clearTimeout(timeout);
              requestAnimationFrame(() => requestAnimationFrame(resolve));
            }
          });
          const timeout = setTimeout(() => { observer.disconnect(); reject(new Error("comparison timeout")); }, 4000);
          observer.observe(document.querySelector("#cards"), { childList: true, subtree: true });
          field.value = year;
          field.dispatchEvent(new Event("change", { bubbles: true }));
        });
        return performance.now() - begin;
      }
      await change("2020");
      await change("2021");
      const timings = [];
      for (let i = 0; i < 40; i++) timings.push(await change(i % 2 === 0 ? "2020" : "2021"));
      return timings;
    });
    const p95 = trials.slice().sort((a, b) => a - b)[Math.ceil(trials.length * .95) - 1];
    assert.ok(p95 < 500, `cached p95 was ${p95} ms`);
    await page.evaluate(() => {
      const control = document.querySelector("#year");
      for (const year of ["2020", "2019", "2022"]) {
        control.value = year;
        control.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    await page.waitForFunction(() => document.querySelector("#cards").textContent.includes("2022"));
    const catalogue = await (await page.request.get(url + "/api/catalogue")).json();
    const pick = catalogue.cause_countries.find(country => country.name === "Japan");
    assert.ok(pick, "Japan missing from WHO registration panel");
    await page.getByRole("button", { name: /Cause lab/ }).click();
    await page.locator("#who-country").selectOption(pick.code);
    await page.locator("#who-year").selectOption("2019");
    await page.waitForFunction(() => document.querySelector("#cause-view").textContent.includes("Japan, 2019"));
    await page.getByRole("checkbox").check();
    await page.locator("#scenario-plot svg").waitFor();
    await page.screenshot({ path: path.join(output, "causes-desktop.png"), fullPage: true });
    const invalid = await page.request.get(url + "/api/causes?" + new URLSearchParams({
      country: pick.code, sex: "female", year: "2019", factor: "6", approx: "1",
    }));
    assert.equal(invalid.status(), 400);
    const empty = await page.request.get(url + "/api/cohort?country=JPN&sex=female&birth=1870");
    assert.deepEqual((await empty.json()).points, []);
    await page.getByRole("button", { name: /Forecast errors/ }).click();
    if (catalogue.error_models.length > 0) {
      await page.locator("#error-grid table").waitFor();
      assert.equal(await page.locator("#error-grid tbody tr").count(), 42);
      await page.screenshot({ path: path.join(output, "errors-desktop.png"), fullPage: true });
    } else {
      await page.getByText("Load a frozen backtest summary to inspect forecast errors.").waitFor();
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: /Period comparison/ }).click();
    await page.locator("#cohort svg").waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: path.join(output, "period-mobile.png"), fullPage: true });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, "browser.json"), JSON.stringify({
      cached_samples: trials, p95_ms: p95, desktop: [1440, 1100], mobile: [390, 844],
      engine: browser.version(), csv_rows: 40, errors,
      checks: ["keyboard", "saved view", "export", "aborted selections", "bounded scenario", "empty cohort", "mobile layout"],
    }, null, 2) + "\n");
  } finally {
    await context.tracing.stop({ path: path.join(output, "trace.zip") });
    await browser.close();
  }
}

qa().catch(error => { console.error(error); process.exitCode = 1; });
