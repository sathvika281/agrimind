# AgriMind: FAI viva notes (AI concepts only)

Everything here is taken from the actual code. If a viva question goes beyond this, say "that is not implemented; it is future work".

---

## PART 1: TOPIC NOTES

### 1. What AgriMind is, and what AI does in it
- **Means:** an AI decision-support system for farmers: it takes a crop problem and the farm's own data and returns what is likely happening, what to do, and how sure it is.
- **In AgriMind:** AI does perception and language (read text/photo, write advice) and reasoning over evidence. Numbers and safety checks are done by rules.
- **Remember:** decision support, not a diagnosis.

### 2. Agents (all of them)
**Investigation graph (LangGraph, 7 agents):**
| # | Agent | Type | Purpose |
|---|---|---|---|
| 1 | **Investigation (planner)** | Rule-based | Decides which specialists this request needs; asks the farmer a clarifying question if the input is too vague or the photo is poor (max 2 times) |
| 2 | **Crop Analysis** | **LLM** (call 1) | Reads description/photo; lists observations, candidate explanations, stated uncertainty; returns a fixed JSON schema |
| 3 | **Farm Memory** | Rule-based | Compares with this farm's earlier checks and diary: matches, recurrence, change. "No history" is a valid answer |
| 4 | **Environment** | Rule-based | Applies weather thresholds: is the weather *consistent with* the candidates (never "caused by") |
| 5 | **Knowledge (RAG)** | Rule-based (BM25) | Retrieves cited passages from the local trusted-document library |
| 6 | **Decision Support** | **LLM** (call 2) | Writes the farmer-facing answer from structured evidence only; may cite only retrieved source ids; cannot change issue, severity or lower uncertainty |
| 7 | **Safety** | Rule-based, fail-closed | Last gate: no doses/products, no extra certainty, no invented sources, must contain actions |

Also in the graph: **clarify**, **fallback** and **finalize** nodes (finalize builds the "Why this result?" dossier, deterministically).

**Separate agents:**
- **Adaptive Planning Agent**: rule-based; builds the Farm plan and re-plans.
- **Economics Agent**: rule-based interpreter run by its own LangGraph (8 steps).
- **Weather alert evaluation**: deterministic rules (not a model, not counted as an LLM agent).
- **Remember:** only **2 of the agents use an LLM**; the rest are deterministic on purpose.

### 3. How the agents work together
- **Means:** each agent does one job and passes structured results to the next.
- **In AgriMind:** planner decides who runs, then crop analysis, then memory/environment/knowledge as needed, then decision support, then safety. Safety can send the answer back to decision support to be rewritten.
- **Remember:** specialisation plus a feedback loop (safety to decision).

### 4. LangGraph and why
- **Means:** a library to build agent workflows as a graph: **nodes** (steps), **edges** (what runs next), **conditional edges** (choose next step from the state), one shared **state**.
- **In AgriMind:** `StateGraph` with 10 nodes; conditional edges route "clarify or continue", "which specialist next", "safe, retry, or fall back". Retry loop is bounded (max 2) and recursion limit is 40.
- **Remember:** it makes the flow explicit, bounded, testable, and records which agents really ran.

### 5. Shared state and agent communication
- **Means:** agents do not chat; they read and write one typed state object.
- **In AgriMind:** `AgriMindState` holds the plan, crop analysis, memory, environment, knowledge evidence, decision, safety verdict, retry count and the step log. Each agent returns a small typed (Pydantic) object.
- **Remember:** communication = structured data, not free text.

### 6. Orchestration
- **Means:** controlling which agent runs, in what order, and what happens on failure.
- **In AgriMind:** the graph decides dynamically (skips agents it does not need and records them as skipped). Optional agents are failure-tolerant; crop analysis or the safety gate failing ends safely with a user-safe error (fail closed).
- **Remember:** orchestration = routing + retries + fallback.

### 7. LLM usage
- **Means:** a large language model generates and understands language.
- **In AgriMind:** exactly **two calls** (Gemini): (1) crop analysis (structured JSON, low temperature), (2) decision synthesis from structured evidence. Without a key, a rule-based demo provider is used.
- **Remember:** the LLM explains and observes; it does not compute, retrieve, decide safety, or authorise sources.

### 8. Deterministic / rule-based components, and why
- **Means:** fixed rules and arithmetic, same input gives same output.
- **In AgriMind:** planner, memory, environment, retrieval, safety, decision-support rules, dossier, journey/patterns, adaptive planning, economics, weather alerts.
- **Why:** reliable, testable, explainable, cannot hallucinate, thresholds can be reviewed by experts.
- **Remember:** use the LLM only where language understanding is needed.

### 9. RAG (Retrieval-Augmented Generation)
- **Means:** retrieve relevant documents first, then generate the answer using them.
- **In AgriMind:** the Knowledge agent retrieves passages; the Decision agent writes the answer from them and may cite only those passages.
- **Remember:** RAG grounds the answer in trusted text instead of the model's memory.

### 10. BM25
- **Means:** a keyword ranking formula (term frequency, rarity of the word, document length) with parameters k1 and b.
- **In AgriMind:** plain-Python BM25 (k1 = 1.5, b = 0.75) plus a crop filter over a local library; top 4 passages; a score below 1.0 is too weak to cite.
- **Remember:** BM25 = transparent keyword ranking, no embeddings, no vector database.

### 11. Knowledge retrieval and source grounding
- **Means:** every claim can be traced to a real source.
- **In AgriMind:** each passage has a stable id, title, institution and URL. The final answer can attach a source only if its id was really retrieved; otherwise the safety agent rejects it.
- **Remember:** sources are shown only when actually retrieved.

### 12. Farm memory / context
- **Means:** the system remembers this farm's history and facts.
- **In AgriMind:** Farm Memory agent reads stored checks and diary through an owner-bound toolbox; a shared farm-context loader gives crop, planting date and location to other features.
- **Remember:** this is retrieval of stored history, **not model training or learning**.

### 13. Decision support
- **Means:** helping a person decide, not deciding for them.
- **In AgriMind:** Decision Support agent plus a separate rule-based "what to consider next" (observe, verify, monitor, seek expert help).
- **Remember:** advice carries stated limits and "ask your agricultural officer".

### 14. Competing hypotheses
- **Means:** keep several possible explanations instead of one answer.
- **In AgriMind:** candidates from crop analysis are ranked "currently better supported" vs "also possible", each with supporting evidence, what is against/unknown, and how to tell them apart. Built from the agents' coded outputs, no scores.
- **Remember:** never a confidence percentage, never called a diagnosis.

### 15. Uncertainty / confidence
- **Means:** being explicit about how sure the system is.
- **In AgriMind:** uncertainty level (low / some / high) from crop analysis; later steps cannot lower it; wording is "possible", "consistent with"; "not sure yet" is a normal output; clarifying questions when evidence is poor.
- **Remember:** honest uncertainty instead of fake probabilities.

### 16. Safety agent / gate / guardrails
- **Means:** checks that block unsafe output before the user sees it.
- **In AgriMind:** rule-based and **fail-closed**. Blocks dosage/product/spray advice (English and Telugu), blocks claiming more certainty, changing the issue or severity, citing unretrieved sources, answers with no actions. If it rejects, the answer is rewritten (max 2 retries) or falls back to the verified crop analysis; if the gate itself errors, nothing is returned.
- **Remember:** a deterministic gate after the LLM, not a prompt.

### 17. Adaptive planning and re-planning
- **Means:** a plan that changes when the world changes.
- **In AgriMind:** the planning agent decides (Do now / Next / If conditions change), diffs against the previous version, and creates a new version only on a **material** change (rain at least 10 mm or moved 10 mm, max temperature crossing 35 C or moved 5 C, new crop check, farmer edit). No change means no new version.
- **Remember:** plan versions are kept; small wobbles do not re-plan.

### 18. Weather reasoning
- **Means:** turning forecast numbers into farm-relevant meaning.
- **In AgriMind:** Environment agent: weather "consistent with" certain problems. Planning: forecast drives irrigation and activity advice. Alerts: fixed severity ladder (info, watch, important, severe) over the real forecast, linked to plan items that fall on that day.
- **Remember:** real forecast only; unavailable means "unavailable", never simulated.

### 19. Economics agent and its role
- **Means:** an agent that interprets economic numbers.
- **In AgriMind:** deterministic code calculates production, cost, break-even, margins, net value per market and scenarios; the **Economics agent** (LangGraph, 8 recorded steps) interprets the result: outlook, confidence level with reasons, main drivers, what is missing, which market looks stronger.
- **Remember:** the agent never does arithmetic and never calls an LLM; prices and yields come from the farmer, none are invented.

### 20. Why agentic, not a chatbot
- **Means:** an agentic system perceives, decides, acts with tools, and loops on feedback.
- **In AgriMind:** it plans which specialists to use, uses tools (history, weather, retrieval), keeps shared state, checks itself (safety loop), asks clarifying questions, and acts on a plan over time.
- **Remember:** a chatbot answers one prompt; AgriMind runs a workflow with memory, tools and checks.

### 21. Hallucination and how it is handled
- **Means:** the model states things that are not true or not supported.
- **In AgriMind:** structured JSON schema output; retrieval grounding; the decision step cannot cite sources it was not given; deterministic safety gate; numbers come from data or code; uncertainty is shown; "not enough information" is allowed.
- **Remember:** reduce, not eliminate. Layered defences.

### 22. Limitations
- The two LLM steps can still be wrong; rules and gate reduce risk but do not prove correctness.
- Small local knowledge library; BM25 matches words, not meaning.
- Rule thresholds are general rules of thumb (need expert review per region).
- Economics depends on farmer-entered prices and yields; no live market feed or price forecast.
- Telugu text not reviewed by a native-speaking agronomist.
- The agentic graph is switched on by a configuration flag; without it the older single-call pipeline runs.
- No model training, fine-tuning or vector search.

### 23. Responsible AI, safety, privacy
- **Means:** safe, transparent, fair, private AI.
- **In AgriMind:** not a diagnosis, no chemical doses, uncertainty shown, sources shown, recorded agent steps (transparency), farm data only readable by its owner (tools cannot take an id from the model), notes are not sent to the AI, export and delete of own data.
- **Remember:** human stays in control; the system says when to ask an expert.

---

## PART 2: VIVA QUESTIONS (short answers)

1. **What is an AI agent?** A program that perceives its input, decides, uses tools, acts, and keeps state toward a goal.
2. **What agents do you have?** Investigation graph: Investigation, Crop Analysis, Farm Memory, Environment, Knowledge (RAG), Decision Support, Safety. Plus Adaptive Planning and Economics agents.
3. **Why multiple agents?** One job each: easier to test, safer, and failures are isolated.
4. **How do agents communicate?** Through one shared typed state in LangGraph, as structured objects, not free text.
5. **What is LangGraph?** A library for building agent workflows as a graph of nodes and edges over shared state.
6. **What is a node?** One step or agent in the graph (for example `farm_memory`).
7. **What is an edge?** The link saying which node runs next; conditional edges choose based on the state.
8. **What is state?** The shared object all nodes read and update: plan, evidence, decision, safety verdict, retries, step log.
9. **Why not one LLM for everything?** It would hallucinate, be hard to verify, and mix reasoning with safety. Rules do exact work; the LLM does language.
10. **Where exactly is the LLM used?** Two places: crop analysis and decision-support wording. Nowhere else.
11. **What is RAG?** Retrieve trusted documents, then generate using them.
12. **What is BM25?** A keyword ranking formula based on term frequency, word rarity and document length.
13. **Why BM25 instead of a vector database?** Small corpus, transparent ranking, no embedding model or extra service, results traceable to matched words.
14. **How does RAG reduce hallucination?** The answer is tied to retrieved passages and may cite only those; the safety gate rejects other citations.
15. **What if retrieved knowledge is insufficient?** Passages below the score threshold are dropped; the answer says no source was found and stays cautious.
16. **Role of the safety agent?** Final fail-closed gate: no doses, no extra certainty, no unretrieved sources, must include actions.
17. **How is uncertainty handled?** Stated as low/some/high, cannot be lowered later, cautious wording, clarifying questions, no fake percentages.
18. **How does farm memory help?** It brings this farm's past checks and diary into the investigation: recurrence, change, supporting or contradicting history.
19. **How does adaptive planning work?** Reads real forecast, crop check and the farmer's plan; builds Now/Next/If; re-plans only on a material change and stores versions.
20. **What makes it agentic?** Dynamic routing, tool use, shared state, a feedback loop (safety to decision), clarifying questions, and a plan that adapts.
21. **Limitations?** LLM can still err, small library, keyword search, rule-of-thumb thresholds, farmer-entered economics inputs, Telugu not expert-reviewed.
22. **Is AgriMind a diagnosis system?** No. It gives possible explanations with uncertainty and tells the farmer when to ask an expert.
23. **What if an agent fails?** Optional agents (memory, environment, knowledge) are skipped and reported; crop analysis or the safety gate failing returns a safe error (fail closed).
24. **Which parts are deterministic and why?** Planner, memory, environment, retrieval, safety, planning, economics, alerts: for reliability, testability and no hallucination.
25. **How does the Economics Agent work?** Code computes the numbers; the agent reads them and outputs outlook, confidence with reasons, drivers, missing inputs and best market.
26. **How does weather reasoning work?** Thresholds on real forecast data; Environment agent says "consistent with"; alerts use a severity ladder; the plan checks affected activities.
27. **Why LangGraph, not plain functions?** Explicit routing, loops with limits, one state, and a recorded execution.
28. **What is conditional routing?** Choosing the next node from the state, for example "safe, retry, or fall back".
29. **What happens if safety rejects the answer?** Decision support rewrites with required changes (max 2 times); then fallback to the verified crop analysis; else error.
30. **How do you prevent invented sources?** Sources are attached by retrieved id only; the safety agent checks every cited URL was retrieved.
31. **Does the system learn?** It remembers farm history (memory), but no model is trained or fine-tuned.
32. **What is context engineering here?** Giving each agent only the structured, farm-scoped context it needs; shared farm context avoids re-asking.
33. **Why competing hypotheses?** To avoid one overconfident answer; shows what supports each and how to tell them apart.
34. **How do you keep data private across farmers?** Tools are built after an ownership check and cannot accept an id from the model; every query is scoped to the user and farm.
35. **Why no confidence percentages?** They would be fabricated; levels with reasons are honest.
36. **What is fail-closed?** If the safety check errors, nothing is shown, rather than showing unchecked output.
37. **What is grounding?** Tying statements to real evidence or sources.
38. **How do weather alerts connect to the plan?** An alert points to plan items on that day; the farmer reviews, and the existing plan refresh decides whether to re-plan.
39. **What would you improve?** Live market data, formal LLM evaluation, vector search, expert review of thresholds and Telugu, MCP-style tools.
40. **Difference between agent and tool?** A tool does one action (fetch weather); an agent decides what to do and which tools to use.

---

## PART 3: MUST MEMORIZE

1. AgriMind is **decision support**, not diagnosis.
2. **7 agents** in the investigation graph: Investigation, Crop Analysis, Farm Memory, Environment, Knowledge (RAG), Decision Support, Safety.
3. Plus **Adaptive Planning** and **Economics** agents.
4. **Only two LLM calls**: Crop Analysis and Decision Support. Everything else is rules.
5. Rules are used for reliability, testability and zero hallucination.
6. **LangGraph** = nodes + edges + conditional edges + shared state.
7. Agents communicate through **structured shared state**, not chat.
8. **RAG** = retrieve trusted text, then answer from it.
9. **BM25** keyword ranking (k1 = 1.5, b = 0.75), crop filter, top 4, score below 1.0 dropped; no vector database.
10. A source can be cited **only if it was retrieved**.
11. **Safety agent** = deterministic, fail-closed gate; rewrites up to 2 times, then falls back.
12. **Uncertainty**: low / some / high; never lowered later; no fake percentages.
13. **Competing hypotheses**: better supported vs also possible; never a score.
14. **Farm memory** = retrieval of stored history, not training.
15. **Adaptive planning**: re-plan only on a material change; versions are kept.
16. **Weather**: "consistent with", never "caused by"; real forecast only; alert severity is a fixed ladder.
17. **Economics agent** interprets numbers; it does no arithmetic and no LLM call; inputs come from the farmer.
18. **Agentic** = routing + tools + shared state + feedback loop + clarifying questions + adaptive plan.
19. **Hallucination**: reduced by schema, grounding, gate and uncertainty, not eliminated.
20. **Limitations**: LLM can still err, small library, keyword matching, rule-of-thumb thresholds, no fine-tuning, no live market feed.
