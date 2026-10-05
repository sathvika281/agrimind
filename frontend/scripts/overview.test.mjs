// Tests for the pure Overview logic (no browser). Run: npm run test:overview
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = buildSync({
  stdin: {
    contents: `export * from "./src/overview/derive";`,
    resolveDir: root, loader: "ts",
  },
  bundle: true, format: "esm", platform: "node", write: false,
});
const m = await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text).toString("base64"));
const { latestByFarm, levelOf, summarize, fieldGeometry, mulberry32, rainOutlook, shouldFetchWeather, WEATHER_RETRY_MS, MAP_W, MAP_H } = m;

let passed = 0;
const test = (name, fn) => { try { fn(); passed++; console.log("PASS", name); } catch (e) { console.log("FAIL", name, "\n   ", e.message); process.exitCode = 1; } };
const A = (id, farm_id, severity) => ({ id, farm_id, result: { severity } });

test("levelOf mirrors the REAL backend severity (never invented)", () => {
  assert.equal(levelOf(A(1, 1, "low")), "ok");
  assert.equal(levelOf(A(1, 1, "medium")), "attention");
  assert.equal(levelOf(A(1, 1, "high")), "critical");
  assert.equal(levelOf(A(1, 1, "unknown")), "unrated");
  assert.equal(levelOf(A(1, 1, undefined)), "unrated");
  assert.equal(levelOf(undefined), "none");
  assert.equal(levelOf(null), "none");
});
test("latestByFarm picks the newest check per farm, any input order", () => {
  const list = [A(5, 1, "low"), A(9, 1, "high"), A(7, 2, "medium"), A(3, 1, "medium")];
  const m2 = latestByFarm(list);
  assert.equal(m2.get(1).id, 9); assert.equal(m2.get(2).id, 7); assert.equal(m2.get(3), undefined);
  assert.equal(latestByFarm([...list].reverse()).get(1).id, 9);
});
test("summarize counts each level and needsAttention = attention + critical", () => {
  const farms = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }];
  const latest = latestByFarm([A(1, 1, "low"), A(2, 2, "medium"), A(3, 3, "high"), A(4, 4, "unknown")]);
  assert.deepEqual(summarize(farms, latest), { ok: 1, attention: 1, critical: 1, unrated: 1, none: 1, needsAttention: 2 });
});
test("field geometry is deterministic per farm id and different between farms", () => {
  assert.equal(fieldGeometry(7, 0).points, fieldGeometry(7, 0).points);
  assert.notEqual(fieldGeometry(7, 0).points, fieldGeometry(8, 0).points);
});
test("polygons are organic (8 points, not axis-aligned rectangles) and stay inside their grid cell", () => {
  for (let id = 1; id <= 30; id++) for (let i = 0; i < 6; i++) {
    const g = fieldGeometry(id, i);
    const pts = g.points.split(" ").map((p) => p.split(",").map(Number));
    assert.equal(pts.length, 8);
    const col = i % 3, row = Math.floor(i / 3), cw = MAP_W / 3, ch = MAP_H / 2;
    for (const [x, y] of pts) {
      assert.ok(x >= col * cw && x <= (col + 1) * cw && y >= row * ch && y <= (row + 1) * ch, `${id}/${i} (${x},${y})`);
    }
    assert.ok(new Set(pts.map((p) => p[0].toFixed(0))).size > 4);
    assert.ok(g.cx > col * cw && g.cx < (col + 1) * cw && g.cy > row * ch && g.cy < (row + 1) * ch);
  }
});
test("mulberry32 is deterministic and in [0,1)", () => {
  const a = mulberry32(42), b = mulberry32(42);
  for (let i = 0; i < 50; i++) { const x = a(); assert.equal(x, b()); assert.ok(x >= 0 && x < 1); }
});
test("rain outlook uses real forecast numbers only; missing weather is 'unknown'", () => {
  assert.deepEqual(rainOutlook(null), { kind: "unknown", mm: null });
  assert.deepEqual(rainOutlook({ next_3d_rain_mm: null }), { kind: "unknown", mm: null });
  assert.deepEqual(rainOutlook({ next_3d_rain_mm: 0.4 }), { kind: "dry", mm: 0.4 });
  assert.deepEqual(rainOutlook({ next_3d_rain_mm: 14 }), { kind: "rain", mm: 14 });
});
test("weather: a failed answer is retried once after the cooldown, never in a loop, never without a location", () => {
  const T = 1_000_000;
  assert.equal(shouldFetchWeather(undefined, true, T, false), true, "never asked -> ask");
  assert.equal(shouldFetchWeather(undefined, true, T, true), false, "already in flight -> don't duplicate");
  assert.equal(shouldFetchWeather({ weather: { t: 1 }, at: T - 10 * WEATHER_RETRY_MS }, true, T, false), false, "real data is kept");
  assert.equal(shouldFetchWeather({ weather: null, at: T - 1000 }, true, T, false), false, "just failed -> no immediate retry (no loop)");
  assert.equal(shouldFetchWeather({ weather: null, at: T - WEATHER_RETRY_MS }, true, T, false), true, "after the cooldown -> one retry");
  assert.equal(shouldFetchWeather({ weather: null, at: T - 10 * WEATHER_RETRY_MS }, false, T, false), false, "no saved location -> nothing to retry");
});

console.log(`\n${passed} passed${process.exitCode ? ", SOME FAILED" : ""}`);
