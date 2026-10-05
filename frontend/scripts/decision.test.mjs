// Tests for the rule-based decision-support wording and the two Copilot decision questions (no browser, no model).
// Run: npm run test:decision
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = buildSync({
  stdin: { contents: `export * from "./src/insights/decision"; export { en } from "./src/i18n/en"; export { te } from "./src/i18n/te";`, resolveDir: root, loader: "ts" },
  bundle: true, format: "esm", platform: "node", write: false,
});
const m = await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text).toString("base64"));
const { decisionView, decisionAnswer, DECISION_QUESTIONS, en, te } = m;

let passed = 0;
const test = (name, fn) => { try { fn(); passed++; console.log("PASS", name); } catch (e) { console.log("FAIL", name, "\n   ", e.message); process.exitCode = 1; } };
const fmt = (iso) => iso.slice(0, 10);
const AT = "2026-08-05T09:00:00Z";
const ev = (id) => ({ analysis_id: id, at: `2026-08-0${id}T09:00:00Z` });
const D = (state, extra = {}) => ({
  farm_id: 1, analysis_id: 5, state, level: "enough", history_total: 5,
  observed: { crop: "Tomato", issue: "Leaf spot", unclear: false, severity: "medium", uncertainty: "some", image_quality: "good", input_type: "text", checked_at: AT },
  evidence: [{ kind: "this_check", value: "issue", dates: [] }, { kind: "severity", value: "medium", dates: [] }, { kind: "history_same_issue", count: 3, dates: [ev(1), ev(3), ev(5)] },
    { kind: "trend", value: "recurring", count: 3, window: 5, dates: [ev(1), ev(3), ev(5)] }],
  actions: ["inspect_plants", "check_spread"], limitations: ["no_treatment", "history_insufficient", "context_not_causal"], expert_reason: null,
  context: [{ field: "primary_crop", value: "Tomato" }, { field: "irrigation_method", value: "drip" }], ...extra,
});
const STATES = {
  none: D("no_actionable_evidence", { observed: null, evidence: [], actions: [], limitations: ["no_treatment", "no_farm_context"], context: [], level: "none", history_total: 0, analysis_id: null }),
  unclear: D("no_actionable_evidence", { observed: { crop: "Tomato", issue: "Unable to pinpoint", unclear: true, severity: "unknown", uncertainty: "high", image_quality: "poor", input_type: "text", checked_at: AT }, actions: ["add_detail"], limitations: ["no_treatment", "no_farm_context"], context: [] }),
  verify: D("verify"),
  monitor: D("monitor", { actions: ["recheck_if_changes", "check_spread"] }),
  expert: D("seek_expert_help", { actions: ["consult_expert", "check_spread"], expert_reason: "recurring" }),
};
const view = (dict, d) => decisionView(dict.ds, dict.prof, d, fmt, fmt);

test("no_treatment is the FIRST limitation in EVERY state, in both languages", () => {
  for (const [name, d] of Object.entries(STATES)) for (const dict of [en, te]) {
    const v = view(dict, d);
    assert.equal(v.limitations[0], dict.ds.limit.no_treatment, `${name} ${dict.locale}`);
    assert.ok(v.limitations.length <= 2);
  }
});

test("panel stays compact: evidence <= 3, next step <= 2, limitation <= 2", () => {
  const big = D("seek_expert_help", { actions: ["consult_expert", "check_spread", "inspect_plants"], limitations: ["no_treatment", "severity_not_recorded", "history_insufficient", "no_farm_context", "context_not_causal"], expert_reason: "severity_high" });
  for (const dict of [en, te]) {
    const v = view(dict, big);
    assert.ok(v.evidence.length <= 3 && v.actions.length <= 2 && v.limitations.length <= 2);
    assert.ok(v.allLimitations.length === 5 && v.allEvidence.length === 4, "the full lists remain available to the Copilot 'why' answer");
  }
});

test("the evidence shown first is the decision-relevant one (trend before severity before history)", () => {
  const v = view(en, STATES.expert);
  assert.equal(v.evidence[0], en.ds.evThisText);
  assert.ok(v.evidence[1].includes("3 of the last 5"));
});

test("unclear / none states say so and invent no action; observed wording is honest", () => {
  assert.equal(view(en, STATES.none).observed, en.ds.observedNone);
  assert.ok(view(en, STATES.none).actions.length === 0);
  assert.ok(view(en, STATES.unclear).observed.startsWith("No actionable issue was identified"));
  assert.deepEqual(view(en, STATES.unclear).actions, [en.ds.action.add_detail]);
  assert.equal(view(en, D("verify", { observed: { ...STATES.verify.observed, crop: "" } })).observed, en.ds.cropMissing);
});

test("expert reason is shown ONLY for the expert state", () => {
  assert.ok(view(en, STATES.expert).expertReason.includes("repeatedly appeared"));
  for (const k of ["none", "unclear", "verify", "monitor"]) assert.equal(view(en, STATES[k]).expertReason, null);
});

test("English and Telugu show the same facts (same counts, same actions, same limitation keys)", () => {
  for (const [name, d] of Object.entries(STATES)) {
    const a = view(en, d), b = view(te, d);
    assert.equal(a.evidence.length, b.evidence.length, name);
    assert.equal(a.actions.length, b.actions.length, name);
    assert.equal(a.allLimitations.length, b.allLimitations.length, name);
    assert.equal(!!a.expertReason, !!b.expertReason, name);
    assert.ok(/[ఀ-౿]/.test(b.limitations[0]), `${name}: Telugu limitation text`);
    for (const l of [...b.evidence, ...b.actions, ...b.limitations, b.observed]) assert.ok(l && !/undefined|NaN|\[object/.test(l), `${name}: ${l}`);
  }
  assert.ok(view(te, STATES.verify).evidence.some((l) => l.includes("3")));
});

test("Copilot 'next' = the stored actions (+ expert reason) + the no-treatment limit, citing the real checks", () => {
  const a = decisionAnswer(en.ds, en.prof, STATES.expert, "next", fmt, fmt);
  assert.ok(a.lines.includes(en.ds.action.consult_expert) && a.lines.includes(en.ds.expert.recurring) && a.lines.includes(en.ds.limit.no_treatment));
  assert.deepEqual(a.evidence.map((e) => e.analysis_id).sort(), [1, 3, 5]);
  assert.equal(a.insufficient, false);
  const n = decisionAnswer(en.ds, en.prof, STATES.none, "next", fmt, fmt);
  assert.equal(n.insufficient, true);
  assert.ok(n.lines[0] === en.ds.noneNext && n.lines.includes(en.ds.limit.no_treatment) && n.evidence.length === 0);
});

test("Copilot 'why' lists ALL evidence, the recorded context as background only, and every limitation", () => {
  const a = decisionAnswer(en.ds, en.prof, STATES.expert, "why", fmt, fmt);
  const t = a.lines.join(" | ");
  assert.ok(t.startsWith(en.ds.whyIntro) && t.includes("appeared in 3 of the last 5") && t.includes("Recorded farm context: Main crop: Tomato · Irrigation: Drip."));
  assert.ok(t.includes(en.ds.limit.context_not_causal) && t.includes(en.ds.limit.history_insufficient));
  assert.ok(!/caused by|because of your|due to your/i.test(t));
  const none = decisionAnswer(en.ds, en.prof, STATES.none, "why", fmt, fmt);
  assert.ok(!none.lines.join(" ").includes("Recorded farm context"), "no context -> no context line, nothing invented");
});

test("both new questions exist in both languages and answer in Telugu", () => {
  assert.deepEqual(DECISION_QUESTIONS, ["next", "why"]);
  for (const q of DECISION_QUESTIONS) for (const dict of [en, te]) assert.ok(dict.ins.q[q].length > 5);
  assert.ok(/[ఀ-౿]/.test(decisionAnswer(te.ds, te.prof, STATES.verify, "why", fmt, fmt).lines.join(" ")));
});

test("no treatment / dosage / spraying / causal / guarantee wording anywhere in the decision text (en + te, incl. templates)", () => {
  const render = (k, v) => (typeof v === "function" ? v(3, 5, "x") : v);
  for (const dict of [en, te]) {
    const all = JSON.stringify(dict.ds, render).toLowerCase();
    assert.ok(!/\b(spray|apply|dose|dosage|fertili[sz]er|fertili[sz]e|pesticide|fungicide|insecticide|irrigate|ml per|litres?|guarantee|guaranteed|will yield|will solve|caused by|because of your)\b/.test(all), dict.locale);
  }
});

test("each decision action has wording, and only the closed catalogue exists", () => {
  const keys = ["inspect_plants", "compare_plants", "check_spread", "record_clearer_photo", "recheck_if_changes", "consult_expert", "add_detail"];
  for (const dict of [en, te]) assert.deepEqual(Object.keys(dict.ds.action).sort(), [...keys].sort());
});

console.log(`\n${passed} passed${process.exitCode ? ", SOME FAILED" : ""}`);
