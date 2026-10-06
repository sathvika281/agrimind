# AgriMind: presentation prompt (15 slides, 5 members x 3 slides)

How to use: copy everything from "PROMPT START" to the end into your AI tool (Gemini, ChatGPT, Claude...). Fill the 4 bracketed items first.
Everything in the FACTS sections is true of the project today. Items marked **[STATUS]** must be updated by you right before presenting.

---

## PROMPT START

You are an expert presentation designer and an AI-course (Fundamentals of Artificial Intelligence, "FAI") teaching assistant.
Create a **15-slide** presentation, **speaker notes** and a **design spec** for our project **AgriMind**.

Fill-ins: Team members = **[Member 1, Member 2, Member 3, Member 4, Member 5]** · Course = **Fundamentals of Artificial Intelligence** · Time = **[15 minutes + Q&A]** · Audience = **[faculty / judges]**

### Hard rules
1. Exactly **15 slides**: **5 members x 3 slides each**. Put the member's name on each slide (small tag, bottom-left).
2. **Do not invent** features, numbers or results. Use only the facts below. Where I list a limitation or "not used", say it honestly.
3. Slides are **visual**: max 12 words per bullet, max 4 bullets, one idea per slide, big numbers, icons, simple diagrams. No paragraphs on slides; put explanation in speaker notes (3 to 5 plain spoken sentences, about 1 minute per slide).
4. **All heavy technical content (architecture, workflows, tests) goes at the END** (slides 13 to 15), because Member 5 will explain it live.
5. Mark clearly on slides which parts are **built and tested** versus **in progress**.

### Slide plan (fixed)

**Member 1: Introduction and problem (slides 1 to 3)**
1. Title: "AgriMind: connected farm intelligence" + tagline "Understand, Learn, Act, Decide" + team names + course.
2. The problem (use the problem statements below, as 4 icon cards).
3. Our solution at a glance: the four layers (Understand, Learn, Act, Decide) as one diagram; each layer answers one farmer question. Show the sentence "one connected system, not ten AI tools".

**Member 2: Features that help the farmer decide what is wrong and what is happening (slides 4 to 6)**
4. Crop check and Result (UNDERSTAND): verdict, "What to do now", "When to get help", "Why this result?" (investigation, competing possibilities, sources, unknowns).
5. Farm intelligence (LEARN): Crop journey (+ Before vs now) and Farm patterns, farm diary, many farms kept separate.
6. Farm plan (ACT): Do now, Next 5 days, If conditions change; re-plans only on material change; plan versions.

**Member 3: Weather, money and experience (slides 7 to 9)**
7. Weather and Smart Farm Weather Alerts (inside the existing Weather page): real OpenWeather data, farm-specific alerts, severity ladder, "May affect your Farm plan", Review Plan. **[STATUS: say "built/in progress/next" truthfully]**
8. Economics (DECIDE): outlook, production, costs, break-even, markets and net value, what-if scenarios, data labels.
9. Design and accessibility: the app's visual language (see design spec), English and Telugu, voice, mobile first, 44 px tap targets, contrast.

**Member 4: FAI point of view (slides 10 to 12)**
10. FAI concepts in AgriMind: intelligent agent (PEAS table), goal-based and rule-based reasoning, reasoning under uncertainty, planning and replanning, knowledge representation and retrieval, responsible AI.
11. **Syllabus coverage**: a table of the 11 course modules, each marked Covered / Partly / Not used, with one line on how it improves the project (use the syllabus table below; **highlight covered modules in the lime accent colour**).
12. How the agents communicate and why this makes the system better (shared structured context, structured state not chat, specialisation, safety gate, recorded steps).

**Member 5: Technical workflows, testing, limits (slides 13 to 15)**
13. Architecture and tech stack + the agent landscape (diagram).
14. Workflows (the 4 pipelines as flow diagrams): Investigation graph, Farm plan, Economics, Weather alerts, and how weather connects to the plan.
15. Testing and verification, honest limitations, next steps, thank you / questions.

### Problem statements (slide 2) and how our features solve them
| Problem | How AgriMind addresses it |
|---|---|
| Small farmers get generic advice that ignores their own farm, history and weather | Shared farm context: crop, location, planting date, diary, past checks and weather are used together |
| AI answers sound certain but can be wrong or unsafe | Uncertainty shown in words, "not a diagnosis", no chemical doses, safety-check agent, no invented confidence percentages |
| Farmers cannot see why an answer was given | "Why this result?": real agent steps, evidence, competing possibilities, unknowns, sources |
| Advice is one-off; nothing remembers the farm | Farm memory, Crop journey, Before vs now, Farm patterns |
| Plans do not react to changing weather | Adaptive Farm plan with real forecast and versioned re-planning; weather alerts that point to affected plan items |
| Farmers cannot judge whether the crop will pay | Economics: break-even, margin ranges, net selling value after transport, what-if scenarios |
| Language and access barriers | Full Telugu support, voice input and read-aloud, mobile-first, large tap targets |

### FEATURES (facts)
**Product:** crop decision-support web app in English and Telugu. A farmer describes a problem (text, voice or photo) and gets a plain-language answer saying what is most likely happening, what to do now and how sure it is. Decision support, **not** a diagnosis. Tech: FastAPI + SQLite, React + TypeScript + Tailwind, one Docker service on Render, weather from OpenWeather with Open-Meteo as automatic backup.

**UNDERSTAND (Result page):** verdict card, numbered "What to do now", "When to get help", tap-questions that refine the answer, a rule-based "what to consider next" panel, and one **"Why this result?"** area containing: Investigation Dossier (real agent steps, evidence considered, why this conclusion, what is unknown, what would verify it), Current possibilities (better supported / also possible, how to tell them apart), Sources (only documents really retrieved), Before vs now link.

**LEARN (Farm intelligence page, tabs):** *Crop journey*: planting date, checks and diary in time order, nothing invented, a Before vs now comparison per check. *Farm patterns*: recurring issues and weather/diary associations with cautious labels (Strong / Possible / Limited evidence); needs at least 4 checks, otherwise "not enough history". Both are deterministic code (no AI call). Also: Farm diary (sowed, irrigated, fertilised, sprayed, weeded, harvested), many farms per farmer with one-tap switching and strictly separate data.

**ACT (Farm plan page):** one Adaptive Farm Planning agent (deterministic). Uses real forecast, farm profile, latest crop check and the farmer's planned activities; produces Do now / Next / If conditions change. Re-plans only on a **material** change (rain crossing 10 mm or moving 10 mm, max temperature crossing 35 C or moving 5 C, a new crop check, a farmer edit). Keeps plan versions; no change means no new version; never simulates weather.

**DECIDE (Economics page):** production, cost, break-even price, market quotes, net value per market after transport, price/yield/cost what-if scenarios, harvest window from the planting date. One Economics agent run by a **LangGraph workflow of 8 recorded steps**; it interprets numbers calculated by deterministic code and **does not call a language model**. Inputs the farmer enters are labelled "Farmer provided"; calculated values "Calculated". **No live market-price feed, price forecast or export-price source is connected**; the page says so. An optional, clearly labelled DEMO DATA mode exists.

**WEATHER and SMART FARM WEATHER ALERTS (inside the existing Weather page; no new page or menu item):** existing weather: current conditions, rain, temperature, humidity, wind, non-chemical "how to cope" tips, from OpenWeather (Open-Meteo backup). Smart alerts **[STATUS: designed, rules and plan-impact logic written; finish wiring and testing before claiming it works]**:
- Alert types: heavy rain, thunderstorm, strong wind, high temperature, low temperature, large temperature change.
- Deterministic severity ladder: info, watch, important, severe (ordinary weather is not an alert). Thresholds reuse the app's existing rain/heat rules and add wind, cold and very-heavy-rain rules.
- Farm-specific wording ("Heavy rain expected near Farm A tomorrow"), using the stored farm location, crop and plan.
- Alert identity (farm + type + day) so repeated refreshes do not create duplicates; lifecycle active, updated, resolved; dismiss; recent alerts list.
- Data freshness shown ("updated 18 minutes ago"); if the forecast is unavailable it says so and never fabricates an alert.
- **Weather to Farm plan link**: if a planned item falls on the alert day, the alert says "May affect your Farm plan" with Review Plan. Weather never re-plans; the Farm plan's own material-change rules decide whether a new plan version is made.
- No new agent is needed: evaluation is deterministic code with recorded steps.

**Other:** voice input and read-aloud; non-chemical weather tips; account export and full account delete; owner checks on every farm route (foreign farm returns the same 404 as a missing one); rate limits; Telugu throughout (not yet reviewed by a native-speaking agronomist).

### FAI POINT OF VIEW (slides 10 to 12)
**Slide 10: AgriMind as an intelligent agent (PEAS):**
- Performance measure: safe, honest, useful advice; correct arithmetic; no false certainty.
- Environment: a farm, its crop history, weather, markets (as the farmer reports them).
- Actuators: recommendations, plan items, alerts, economic outlook shown to the farmer.
- Sensors: farmer's text, voice and photos; stored history; OpenWeather forecast.

Map course ideas to the project (use only what is true):
- **Agent types:** goal-based and utility-style reasoning (plan toward "what should I do"), rule-based agents (planning, patterns, journey, economics) and an LLM-based perception/language agent for crop analysis.
- **Reasoning under uncertainty:** uncertainty levels (low, some, high), "possible" versus "confirmed" wording, competing hypotheses, deliberately **no fake probabilities**.
- **Knowledge representation and retrieval:** a local library of trusted agricultural documents searched with BM25 (keyword ranking, not embeddings); sources shown only when retrieved.
- **Planning and replanning:** the adaptive planner updates the plan when the world changes materially.
- **Learning from experience (memory, not model training):** farm memory and patterns learn from the farm's own stored history. No model is trained.
- **Search/rules:** deterministic rules with named thresholds that experts can review.
- **Responsible AI:** safety agent, no chemical doses, ownership and privacy, transparency of what ran, honest limits.

**Slide 11: Syllabus coverage (highlight covered ones). Be honest; use exactly these ratings:**
| Course module | In AgriMind? | How it helps the project |
|---|---|---|
| Course Overview | Covered | Frames the project as applied AI end to end |
| Building LLM Applications Using Python | **Covered** | Python/FastAPI backend, a swappable AI-provider layer (Gemini or demo), structured JSON outputs validated with Pydantic |
| Building UI and Deploying LLM Applications | **Covered** | React/Tailwind mobile-first UI in English and Telugu; Dockerised and deployed on Render |
| Understanding How LLMs Work and Enhancing Productivity with AI | **Covered** | Prompt and output design: structured outputs, uncertainty levels, safety constraints; AI used for language, code for numbers |
| Tools Use and Function Calling in LLMs | **Partly** | Agents use a toolbox (farm history lookup, weather, knowledge search) through code-defined tools **[verify before saying "native LLM function calling"]** |
| Introduction to LangChain and Retrieval-Augmented Generation (RAG) | **Partly** | RAG is real: trusted local documents retrieved (BM25) and cited. We use **LangGraph** (LangChain's agent-orchestration library), not the LangChain chain classes or a vector database |
| Building AI Agents Using LangChain and Memory Agents | **Covered** | Specialised agents orchestrated in LangGraph; a **Farm Memory agent** brings the farm's own history into every investigation |
| Building AI-Powered Conversational Interview Assistant and RAG Agent Using LangChain | **Partly** | An agent asks clarifying questions when evidence is poor ("Help AgriMind be more sure"), and a knowledge agent retrieves sources. It is not a full conversational chat |
| Introduction to Context Engineering and MCP | **Partly** | **Context engineering: covered** (a shared, structured, per-farm context decides exactly what each agent sees). **MCP: not used** (possible future step) |
| Building Multi-Agent Systems and LLM Evaluation | **Partly** | Multi-agent: covered (planner, crop analysis, memory, environment, knowledge, decision, safety, plus planning and economics agents). Evaluation: a safety-verification agent and ~760 automated tests; no formal LLM benchmark |
| Running Models Locally and Fine-Tuning LLMs | **Not used** | We call a hosted model; the knowledge library and all rule logic run locally; no fine-tuning (future work) |

**Slide 12: How the agents communicate and why this is better:**
- They do **not** chat with each other. They exchange **structured state** (typed objects) through LangGraph and a shared farm context.
- Each agent has one job and a boundary: the planner decides who is needed (and records who was skipped); crop analysis reads the photo/text; farm memory reads history; environment reads weather; knowledge retrieves sources; decision support combines evidence; the safety agent verifies and can send the answer back.
- Benefits: specialisation (each part is simpler and testable), transparency (the recorded steps are shown, never faked), safety (a gate before anything reaches the farmer), no duplicated entry (the farmer states the crop once), and cross-feature reuse (the same context feeds Economics and Plan).
- Honest line: separate features (Plan, Economics, Weather alerts) share the **same farm context and weather data**; they connect through data, not by calling each other.

### TECHNICAL SLIDES (13 to 15) content
**13. Architecture:** React/TypeScript UI, FastAPI, SQLite, LangGraph, a swappable AI provider, a local knowledge library, OpenWeather then Open-Meteo, Docker on Render. Agent landscape diagram: Investigation graph agents, Planning agent, Economics agent, Weather evaluation, all reading the shared farm context.

**14. Workflows (draw as left-to-right flow diagrams):**
1. *Investigation (LangGraph):* Investigation planner, then Crop analysis, then optional Farm memory, Environment, Knowledge (RAG), then Decision support, then Safety gate (pass, rewrite up to 2 times, or safe fallback), then Result with a recorded step log.
2. *Farm plan:* real forecast + farm facts + latest check + planned activities, then decide, then diff against the last version, then store a new version only if material.
3. *Economics (LangGraph, 8 recorded steps):* economic input, production calculation, cost calculation, market data, market analysis, scenario calculation, economics agent, result.
4. *Weather alerts + plan link:* OpenWeather forecast (cached), then deterministic alert evaluation (severity ladder), then reconcile (new, updated, resolved, no duplicates), then Farm plan impact check (read only), then the farmer taps Review Plan, then the existing plan refresh decides (material change gives plan v2, otherwise keep). **[STATUS]**
Show weather feeding both Farm plan and the alerts, and the shared farm context in the middle.

**15. Verification and honesty:** about 760 backend tests; wording tests in English and Telugu; real-browser tests on phone, tablet and desktop checking contrast, tap targets, overflow, Telugu, farm separation and exact numbers. Limitations: not a diagnosis tool; Economics uses farmer-entered prices (no live feed, no forecast); small local knowledge library; thresholds are rules of thumb for expert review; Telugu needs native review; weather alerts **[STATUS]**; no MCP, no fine-tuning, no vector database. Next steps: live market feed, native Telugu review, finish weather alerts, formal LLM evaluation, MCP tools.

### DESIGN SPEC (so the deck looks like the app)
Make the deck feel like the same product as the app:
- **Colours:** deep forest green `#0d2d21` and `#123c2c` for dark slides; **lime accent `#c8f169`** only for the key highlight/selected state/primary call-to-action; warm off-white `#f3f2ed` background for content slides; white cards; amber `#ffd166` for "attention / in progress"; red `#c0392b` only for important warnings; muted grey-green `#66726b` for secondary text.
- **Typography:** clean humanist sans (Segoe UI or Inter). Titles bold and tight (28 to 40 pt), body 18 to 22 pt, never below 16 pt. Short uppercase tracked eyebrow labels (e.g. "1 . UNDERSTAND") above titles.
- **Shapes:** very rounded cards (about 24 px radius), soft shadows, pill buttons and pill tags, glass-style translucent cards over photos.
- **Imagery:** use real aerial farm and crop photographs as slide headers (free-licence Pexels photos are in `frontend/public/img/`; credits in `CREDITS.md`) with a dark gradient overlay (light at top, dark at bottom) so white text stays readable. Dark title/section slides use a photo; content slides are off-white.
- **Icons:** one consistent thin-outline icon set (sun, rain, storm, crop, inspect, check, chevron, history, info). No emoji as meaning.
- **Layer chips:** a small pill on feature slides: `1 . UNDERSTAND`, `2 . LEARN`, `3 . ACT`, `4 . DECIDE`, with a lime number badge. Use the same chip on the app screenshots.
- **Screenshots:** show real app screenshots in a phone frame (360 to 390 px wide) and a desktop frame; capture: Result with "Why this result?" open, Crop journey with Before vs now open, Farm plan (dark card, 5 day pills), Economics outlook and scenario, Weather page (with the alert section when ready), sidebar showing LEARN / ACT / DECIDE groups, the same page in Telugu.
- **Layout rhythm:** left-aligned titles, generous white space, 2 or 3 column card grids, one lime highlight per slide, consistent 16:9, footer with member name and slide number.
- **Diagrams:** rounded boxes joined by thin arrows, agents as green pills, deterministic code as white boxes, data sources as grey boxes; lime for the step being explained.
- **Tone:** confident, plain, honest. No buzzwords.

### Likely hard questions (add as backup slides or notes)
- Is this just a chatbot or one big prompt? No: separate agents, structured state, deterministic code for numbers, a safety gate.
- How do you stop hallucination? Numbers come from data or code; sources only if retrieved; uncertainty is shown; no confidence percentages; a safety agent verifies.
- Where does market data come from? Farmer-entered quotes today; no live feed; demo data is labelled.
- How do agents communicate? Structured shared state and farm context; steps are recorded, not invented.
- What if the weather API is down? The plan uses the last real forecast or says unavailable; alerts are not created from unknown data.
- Is it using MCP or fine-tuning? No, and we say so; both are future work.
- How is farmer data protected? Per-user ownership checks, same 404 for foreign farms, export and delete.

### Output format
1. A table of the 15 slides: number, member, title, 3 to 4 short bullets, visual to show.
2. Speaker notes per slide (about 1 minute each).
3. The design spec applied (colours, fonts, layout) as a short style guide for the deck.
4. A 2-minute demo script: Check my crop, Result and "Why this result?", Farm intelligence, Farm plan, Economics, switch to Telugu.
5. Backup Q&A slide text.
