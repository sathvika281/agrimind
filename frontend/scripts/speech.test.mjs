// Tests for the pure voice logic (no browser needed). Run: npm run test:speech
// Bundles the TS sources with the esbuild that already ships with Vite (no new dependency).
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = buildSync({
  stdin: {
    contents: `
      export * from "./src/voice/speechText";
      export { appendTranscript, mapRecognitionError, recognitionLang } from "./src/voice/stt";
      export { pickVoice } from "./src/voice/tts";
      export { en } from "./src/i18n/en";
      export { te } from "./src/i18n/te";`,
    resolveDir: root,
    loader: "ts",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  write: false,
});
const code = out.outputFiles[0].text;
const m = await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
const { buildSpeechText, MAX_SPOKEN_CHARS, appendTranscript, mapRecognitionError, recognitionLang, pickVoice, en, te } = m;

let passed = 0;
const test = (name, fn) => {
  try {
    fn();
    passed++;
    console.log("PASS", name);
  } catch (e) {
    console.log("FAIL", name, "\n   ", e.message);
    process.exitCode = 1;
  }
};

const fullEn = {
  likely_issue: "Possible fungal leaf spot (early stage)",
  explanation: "Long explanation that must NOT be spoken in full.",
  recommended_actions: ["r1"],
  precautions: ["Wear gloves.", "second precaution"],
  uncertainty: "Raw uncertainty text.",
  severity: "medium",
  observations: ["obs one"],
  when_to_seek_help: "Call your local agricultural officer if it spreads fast.",
  possible_alternatives: [{ possibility: "Water stress", how_to_tell: "x" }],
  evidence_for: ["ev"], evidence_against: [], unknowns: ["u"],
  immediate_actions: ["Remove badly affected leaves", "Check soil moisture", "Inspect nearby plants", "FOURTH ACTION"],
  monitoring_steps: ["Watch new leaves", "Check neighbours", "THIRD WATCH"],
  follow_up_questions: ["q?"], uncertainty_level: "some", image_quality: "good", image_guidance: "",
};
const fullTe = {
  ...fullEn,
  likely_issue: "ఆకు మచ్చ తెగులు కావచ్చు (ఫంగస్)",
  immediate_actions: ["బాగా దెబ్బతిన్న ఆకులను తీసివేయండి", "మట్టి తేమ చూడండి", "పక్క మొక్కలను గమనించండి", "నాలుగో పని"],
  monitoring_steps: ["కొత్త ఆకులను గమనించండి", "పక్క మొక్కలు చూడండి", "మూడో గమనిక"],
  when_to_seek_help: "సమస్య వేగంగా వ్యాపిస్తే వ్యవసాయ అధికారిని సంప్రదించండి.",
  precautions: ["చేతి తొడుగులు వేసుకోండి.", "రెండో జాగ్రత్త"],
  uncertainty_level: "high",
};
const old = { likely_issue: "Old issue", explanation: "e", recommended_actions: ["Do A", "Do B"], precautions: ["Be careful"], uncertainty: "u" };

test("English: issue, certainty sentence, <=3 actions, <=2 watch steps, help, first precaution, in order", () => {
  const s = buildSpeechText(fullEn, "en");
  const order = ["AgriMind's best guess:", en.uncertainty.some, "What to do now.", "What to watch.", "When to get help.", "One precaution."].map((x) => s.indexOf(x));
  assert.ok(order.every((v, i) => v >= 0 && (i === 0 || v > order[i - 1])), order.join(","));
  assert.ok(s.includes("Remove badly affected leaves.") && s.includes("Inspect nearby plants."));
  assert.ok(!s.includes("FOURTH ACTION") && !s.includes("THIRD WATCH") && !s.includes("second precaution"));
  assert.ok(s.includes("Wear gloves.") && s.includes("Watch new leaves."));
});
test("English: parentheses are made speakable and the long explanation/observations are not read", () => {
  const s = buildSpeechText(fullEn, "en");
  assert.ok(s.includes("Possible fungal leaf spot, early stage.") && !s.includes("(") && !s.includes("Long explanation") && !s.includes("obs one"));
});
test("never speaks keys, raw enum values or internal metadata", () => {
  for (const [r, l] of [[fullEn, "en"], [fullTe, "te"]]) {
    const s = buildSpeechText(r, l);
    // ("some"/"high"/"low" are ordinary words inside the spoken sentences, so only unambiguous internal tokens are checked)
    for (const bad of ["likely_issue", "immediate_actions", "uncertainty_level", "severity", "image_quality", "monitoring_steps", "not_provided", "input_type", "medium", "{", "}", "undefined", "null"]) {
      assert.ok(!s.includes(bad), `${l} speech contains internal token "${bad}"`);
    }
    assert.ok(!s.includes("Raw uncertainty text."));
  }
});
test("Telugu: Telugu spoken labels + Telugu certainty sentence, same limits", () => {
  const s = buildSpeechText(fullTe, "te");
  for (const x of [te.speech.bestGuess, te.uncertainty.high, te.speech.doNow, te.speech.watch, te.speech.help, te.speech.precaution]) assert.ok(s.includes(x), x);
  assert.ok(s.includes("పక్క మొక్కలను గమనించండి.") && !s.includes("నాలుగో పని") && !s.includes("మూడో గమనిక") && !s.includes("రెండో జాగ్రత్త"));
  assert.ok(!/What to do now|best guess/.test(s));
});
test("old Phase 1 result (few fields) is spoken safely, falling back to recommended actions", () => {
  const s = buildSpeechText(old, "en");
  assert.ok(s.includes("Old issue.") && s.includes("What to do now. Do A. Do B.") && s.includes("One precaution. Be careful."));
  assert.ok(!s.includes("What to watch") && !s.includes("When to get help") && !s.includes("undefined"));
});
test("missing/null optional fields do not crash and are skipped", () => {
  const s = buildSpeechText({ likely_issue: "X", explanation: "e", recommended_actions: [], precautions: [], uncertainty: "u",
    immediate_actions: null, monitoring_steps: undefined, when_to_seek_help: null, uncertainty_level: "weird" }, "en");
  assert.equal(s, "AgriMind's best guess: X.");
});
test("long results are capped at the limit and keep the issue and the first action", () => {
  const long = "word ".repeat(120).trim() + ".";
  const s = buildSpeechText({ ...fullEn, immediate_actions: [long, long, long], monitoring_steps: [long, long], precautions: [long] }, "en");
  assert.ok(s.length <= MAX_SPOKEN_CHARS, String(s.length));
  assert.ok(s.startsWith("AgriMind's best guess:") && s.includes("What to do now."));
});
test("building speech text never mutates the result", () => {
  const before = JSON.stringify(fullTe);
  buildSpeechText(fullTe, "te");
  buildSpeechText(fullTe, "en");
  assert.equal(JSON.stringify(fullTe), before);
});
test("pickVoice: Telugu needs a te voice (never an English one)", () => {
  assert.equal(pickVoice([{ lang: "en-US" }, { lang: "hi-IN" }], "te"), null);
  assert.equal(pickVoice([{ lang: "en-US" }, { lang: "te-IN", name: "T" }], "te").name, "T");
  assert.equal(pickVoice([{ lang: "te_IN", name: "U" }], "te").name, "U");
});
test("pickVoice: English prefers en-IN, then any en, else null", () => {
  assert.equal(pickVoice([{ lang: "en-US", name: "US" }, { lang: "en-IN", name: "IN" }], "en").name, "IN");
  assert.equal(pickVoice([{ lang: "en-GB", name: "GB" }], "en").name, "GB");
  assert.equal(pickVoice([{ lang: "te-IN" }], "en"), null);
});
test("appendTranscript appends with one space and never overwrites typed text", () => {
  assert.equal(appendTranscript("Leaves are yellow.", "and spots too"), "Leaves are yellow. and spots too");
  assert.equal(appendTranscript("typed   \n", "spoken"), "typed spoken");
  assert.equal(appendTranscript("", "  only spoken  "), "only spoken");
});
test("appendTranscript with an empty transcript changes nothing", () => {
  assert.equal(appendTranscript("keep me", ""), "keep me");
  assert.equal(appendTranscript("keep me", "   "), "keep me");
});
test("recognition language follows the UI language (te-IN / en-IN)", () => {
  assert.equal(recognitionLang("te"), "te-IN");
  assert.equal(recognitionLang("en"), "en-IN");
});
test("browser speech errors map to friendly categories", () => {
  assert.equal(mapRecognitionError("not-allowed"), "denied");
  assert.equal(mapRecognitionError("audio-capture"), "no_mic");
  assert.equal(mapRecognitionError("no-speech"), "no_speech");
  assert.equal(mapRecognitionError("network"), "network");
  assert.equal(mapRecognitionError("language-not-supported"), "lang_unsupported");
  assert.equal(mapRecognitionError("service-not-allowed"), "unavailable");
  assert.equal(mapRecognitionError("something-new"), "unavailable");
  assert.equal(mapRecognitionError("aborted"), null);
});
test("every voice string exists in both languages, non-empty", () => {
  for (const k of Object.keys(en.voice)) assert.ok(te.voice[k] && te.voice[k].trim(), `te.voice.${k}`);
  for (const k of Object.keys(en.speech)) assert.ok(te.speech[k] && te.speech[k].trim(), `te.speech.${k}`);
});

console.log(`\n${passed} passed${process.exitCode ? ", SOME FAILED" : ""}`);
