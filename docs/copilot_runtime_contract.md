# MedScribe — Copilot Runtime Contract

**Status:** `1.2` normative (PR #50). Next contract change follows §10.
**Contract version:** `1.2`
**Date:** 2026-09-10
**Revised:** 2026-09-16 (#50 — 1.2 normative: tool ids v2, evidence state, dispatch table, `planning_agent`, `sub_asks`); 2026-09-30 (#50 — runtime object model and SDD data-model pass, aligned to `docs/design/medscribe-runtime-sdd.md` Appendix A)
**Phase:** 1A of [agent_refactor_plan.md](./agent_refactor_plan.md)
**Code:** `server/app/agents/intent/` (gate schema, policy, executor contract), `server/app/agents/tool_contracts.py` (shared tool registry), `server/app/agents/compile_contracts.py` (Lane B outputs), `server/app/agents/config.py` (provisional tuning constants).
**Tests:** `server/tests/unit/test_intent_contract.py`
**Golden sets:** `server/tests/fixtures/intent_task_v2.jsonl`, `server/tests/fixtures/intent_addressee_v1.jsonl`

The refactor plan says *why* and *in what order*. This document says *what is
agreed*. Later phases build against it; changing it follows §10.

> **Maintain patient-scoped information state and acquire the evidence a physician goal needs, under explicit consistency, latency, grounding, and authority constraints; one tool registry under every mechanism.**
> Listen by default, retrieve when asked on an explicit channel, compile in the background, persist only with authority.

### Revision 1.2 (2026-09-16, PR #50)

Normative from this PR. Implementation issues: #51–#63, #83–#85. Sign-off: #47.

1. **Tool ids v2:** `retrieve_structured` (with `kind=`) replaces the v1 lookup tool; `get_patient_profile` and `retrieve_source_chunks` added; the v1 monolithic safety tool is split into `check_med_conflicts`, `check_dosage`, `check_metric_alerts` (each returns `not_covered` when outside rule coverage); compute tools `normalize_units`, `compute_trend`, `compute_delta` added (LLM-free, planner-allowlisted; #85).
2. **Evidence state, receipt time, stable ids:** `Citation` gains `citation_id` (`{source_kind}:{source_id}`), `received_at`, `evidence_state` (`received` | `materialized` | `validated` | `authorized`), and `locator`, a union tagged on `kind`: `document_span` | `transcript_span` | `row_ref`. New `Claim` and `Derivation` types for the strict grounding validator (§5.3); both reference `citation_id`s.
3. **Stage B sub-asks:** `TaskSlots` gains `sub_asks` (list of `SubAsk`) and `readings_conflict`. `SubAsk` carries calibrated per-class scores, `entity_hints`, free-text `domain_hints`, canonical `scope_ids`, `time_range`, `depends_on`. `task_subtype` is deprecated (1.1 compatibility only).
4. **Dispatch table:** `dispatch_assist(context, slots)` is a pure code function returning one `DispatchDecision`; no model decides the execution path. Dispatch values: `silent`, `clarify`, `workflow`, `fanout`, `planning_agent`.
5. **Planner deferred:** trajectory and compare are fixed workflows. `planning_agent` stays in the dispatch literal so the boundary is stable, but rule 3 maps to `clarify` and logs `needs_plan` until #58 re-enters (SDD §9.2).
6. **`ClarifyRequest` / `ScopeChoice`:** every clarify is structured; no model-written free-text question. Provisional `SUB_ASK_MIN_CONFIDENCE` `0.75`, `MAX_FANOUT_WORKFLOWS` `3`, `REFERENCE_RESOLUTION_WAIT_MS` `3000`, `RECHECK_INTERVAL_MS` `1000`, `POST_BARRIER_RESERVE_MS` `3300` (config.py).
7. **`ToolCaller` updated:** `planning_agent` added; `fixed_executor` and `lane_b_stage` unchanged.
8. **Request carriers (§5.4):** `AssistRequestContext` + `ReceiptWatermarks` own request identity, cutoff, and deadline; `EvidenceBundle` is the one evidence accumulator; fixed workflows return a closed `WorkflowOutcome`; `PlanRequest` + `EvidenceRef` are the immutable handoff; `AssistAnswer` is the rendered output. The 1.1 handoff bag is deleted.
9. **Source kinds name what a source is** (§6.5): `document`, `observation`, `visit` replace the arrival-time kinds, so one document has one `citation_id`.
10. **Lane B provenance (§7):** `CandidateFact.provenance` is a `FactProvenance` (`evidence`, `extractor`, `prompt_version`); the fact's source documents and segments are read from it, not stored twice. Review lives in Postgres `review_items`; the review-state enum is derived.
11. **Scope keys:** the clinician scope key is `clinician_id`. `ingest_delta` is a Lane B stage only; intake is gateway-owned.

### Revision 1.1 (2026-09-10)

Aligns the contract with the plan's critique pass. Changes from 1.0:

1. **The gate no longer emits a plan.** It outputs addressee + task slots; the executor owns plans (§5).
2. **Addressee and task are separate stages** with different error costs (§3.2).
3. **v1 copilot channels are explicit only:** `explicit_ui` and `wake_word` (renamed from the 1.0 voice channel). Ambient transcript is always silent in v1; chips are research-only and ambient never auto-answers (§4).
4. **Fixed workflows where plan is known up front; planning agent for dependent/uncovered acquisition only** (§2). In 1.1 trajectory and compare ran as bounded agents; in 1.2 they are fixed workflows.
5. **Tool registry hardening:** runtime-injected patient/tenant scope, planner allowlist, three caller kinds. Registry implementation in Phase 1 (§6).
6. **Groundedness means citation correctness**, checked post-hoc before rendering (§5.3).
7. **Lane B outputs are part of the contract:** push safety alerts and delta-compile semantics (§7).
8. **The golden set is split** into a task set and an addressee set (§9).

---

## 1. Lanes in product language


| Lane                       | Code id       | What the clinician experiences                                                                       | Latency class                                                               | May write                                | Must never                                                               |
| -------------------------- | ------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------ |
| A — Live stream           | `live_stream` | Their words appear in the transcript. Nothing else changes on screen.                                | real-time hot path                                                          | Redis transcript buffer                  | call any LLM; wait on the gate, retrieval, Lane B/C, or PostgreSQL       |
| A-assist — Copilot answer | `assist`      | They asked MedScribe something. A sourced answer card appears.                                       | interactive: factoid p95 < ~1.5–2 s; trajectory/compare p95 < ~3–5 s warm | Redis answer artifacts, session scratch  | write chart fields; render a patient fact that fails the grounding check |
| B — Clinical compile      | `compile`     | The draft record updates quietly. Safety alert cards can appear unasked. Review badge may increment. | background                                                                  | Redis draft, review queue, alert channel | block transcript or chat; mutate the PostgreSQL patient record           |
| Note job                   | `note_job`    | They asked for SOAP / summary / discharge. Progress, then a draft note.                              | background job, visible progress                                            | Redis note draft                         | auto-finalize a note                                                     |
| Doc ingest                 | `doc_ingest`  | They uploaded or reprocessed a document. A field-change package appears for review.                  | background job                                                              | artifact store, Redis review package     | apply field changes without sign-off                                     |
| C — Durability            | `durability`  | They end the visit or sign off. The record is saved.                                                 | boundary; may take seconds                                                  | PostgreSQL                               | persist unapproved changes; run agentically; start from voice alone      |

### 1.1 Three things that look alike and are not


| Artifact                  | Means                                        | Lives in   | Status                |
| ------------------------- | -------------------------------------------- | ---------- | --------------------- |
| Visible transcript / chat | It was said or heard                         | Redis      | `transcript_appended` |
| Compiled draft            | MedScribe's current structured understanding | Redis      | `draft_ready`         |
| Persisted record          | Physician-authorized chart state             | PostgreSQL | `persisted`           |

A finished pipeline run never by itself means the chart changed.

### 1.2 Encounter status model

`EncounterStatus` in `schemas.py`. UI copy should come from this list, not from
graph node names.


| Status                                 | Lane     | Shown to clinician as              |
| -------------------------------------- | -------- | ---------------------------------- |
| `listening`                            | A        | mic active                         |
| `transcript_appended`                  | A        | transcript line appears            |
| `intent_detected`                      | gate     | not shown by default (audit only)  |
| `assist_answering` / `assist_answered` | A-assist | answer card loading / ready        |
| `compile_running` / `draft_ready`      | B        | "Updating draft" / "Draft updated" |
| `note_running` / `note_ready`          | note job | "Writing note" / "Note ready"      |
| `safety_alert_raised`                  | B        | alert card                         |
| `review_pending` / `review_approved`   | B → C   | review badge / cleared             |
| `session_finalizing` / `persisted`     | C        | "Saving" / "Saved to record"       |

Until Phase 3 lands, `PipelineProgress.status == "completed"` means the graph
finished, which may include a durable write *or* only review staging. UI must
not label it "Saved".

---

## 2. Orchestration style per lane

Execution style is chosen from the information-acquisition path, not from a
lane or task label. There are four independent axes: execution, temporal,
authority, and evidence state. Lanes, workflows, and the planning agent are
mechanisms under the goal of acquiring the evidence a physician goal needs.

**Fixed workflow** when the evidence class is known and the steps are
deterministic (retrieval → chunks → synthesis). Every assist ask in 1.2 runs
a fixed workflow, keyed by evidence class (§5.1), or is clarified.
**`planning_agent`** is reserved for dependent sub-asks, an accepted
`no_workflow` class, or a fixed workflow returning `planning_needed`. While
the planner is deferred, those asks are clarified and logged as `needs_plan`.

`dispatch_assist()` in `executor_contract.py` is the code form of the dispatch
table (§5.2).


| Lane / ask                            | Execution                          | Why                         |
| ------------------------------------- | ---------------------------------- | --------------------------- |
| Lane A                                | no LLM at all                      | latency invariant           |
| Lane B compile, including push safety | fixed DAG with conditional edges   | durable IR, reproducible    |
| Lane C                                | fixed, never agentic               | authority boundary          |
| Retrieval evidence classes            | fixed workflow per class           | plan known up front         |
| `note`, `session_control`             | the one `jobs` workflow            | inputs known                |
| dependent / uncovered asks            | `clarify` until #58                | planner deferred            |

---

## 3. Intent gate

### 3.1 Channels

A channel is **where an input came from**, not what it means.


| Channel              | Source                                                                                 | v1 behavior                                                                |
| -------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `explicit_ui`        | Copilot input box →`POST /api/session/{id}/assistant`; Summarize / SOAP / End buttons | Addressee is`copilot` by construction. Stage B runs.                       |
| `wake_word`          | Wake word / explicit spoken address (whether v1 needs it is plan §16 Q1)              | Addressee is`copilot` by construction. Stage B runs.                       |
| `ambient_transcript` | `POST /transcribe` segments                                                            | **No gate call.** Lane A only. Stage A exists for research, behind a flag. |

API surface decisions:

- The existing `POST /api/session/{session_id}/assistant` route **is** the
  explicit channel. Phase 2 hardens it; no new route.
- `POST /transcribe` never calls a gate model, in any phase.
- Transcript rows with speaker `Scribe` are MedScribe's own output and never
  enter the gate. Accepted speakers: `Clinician`, `Patient`.

### 3.2 Two stages


| Stage          | Question                                               | Error cost                     | v1                                                                   |
| -------------- | ------------------------------------------------------ | ------------------------------ | -------------------------------------------------------------------- |
| A — addressee | Is the speaker talking to the patient or to MedScribe? | **very high** (false barge-in) | skipped: explicit channels imply`copilot`; ambient is silent         |
| B — task      | Which task, with which slots?                          | medium (clinician re-asks)     | rules + optional small-model slot extraction, explicit channels only |

Text heuristics cannot separate "What was your last blood pressure reading?"
(to the patient) from a copilot question. That is why ambient is out of v1. If
ambient research starts, use a local addressee classifier, not a hosted LLM on
a sub-second budget.

### 3.3 Enums

**Addressee:** `patient` · `copilot` · `unknown`

**Task subtype** (deprecated, G7): 1.1 compatibility only. Dispatch reads
`sub_asks`; workflows key on evidence class. Removed when #55 merges.


| Task              | Meaning                                                    | Example                                                  | Lane         | Executor        |
| ----------------- | ---------------------------------------------------------- | -------------------------------------------------------- | ------------ | --------------- |
| `factoid`         | single fact lookup                                         | "What was the RBC on the last blood test?"               | `assist`     | `fixed`         |
| `trajectory`      | longitudinal synthesis                                     | "How has her respiratory system trended over two years?" | `assist`     | `fixed`         |
| `compare`         | new vs old: session vs history, doc vs doc, visit vs visit | "Compare the new findings with the old blood tests."     | `assist`     | `fixed`         |
| `safety`          | allergy / interaction / contraindication check (pull)      | "Is it safe to start amoxicillin with her meds?"         | `assist`     | `fixed`         |
| `compile`         | build or refresh the structured draft                      | "Refresh the structured draft."                          | `compile`    | `fixed`         |
| `note`            | SOAP / discharge / session summary                         | "Summarize the session so far."                          | `note_job`   | `fixed`         |
| `doc_ingest`      | process or reprocess an uploaded document                  | "Reprocess the lab PDF I uploaded."                      | `doc_ingest` | `fixed`         |
| `session_control` | end, pause, sign-off                                       | "End session."                                           | `durability` | `fixed`         |
| `unknown`         | unclear                                                    | "hmm"                                                    | `assist`     | `fixed`         |

Dictation is not a task in v1 (plan §5.9). It is either an explicit dictation
mode in the UI or plain Lane A transcript.

### 3.4 `IntentDecision`

Composite audit object after Stage A (if any) and Stage B. **It has no plan
field.**


| Field       | Type                                      | Rule                                                                     |
| ----------- | ----------------------------------------- | ------------------------------------------------------------------------ |
| `addressee` | `AddresseeDecision`                       | always present                                                           |
| `task`      | `TaskSlots` \| null                       | present iff addressee is`copilot`                                        |
| `intervene` | bool                                      | produce user-visible copilot output now;`true` requires `task`           |
| `urgency`   | `silent` \| `background` \| `interactive` | `intervene=true` ⇒ not `silent`; `intervene=false` ⇒ not `interactive` |

`AddresseeDecision`


| Field          | Type                                | Rule                                                     |
| -------------- | ----------------------------------- | -------------------------------------------------------- |
| `addressee`    | `patient` \| `copilot` \| `unknown` | explicit channels ⇒`copilot`                            |
| `confidence`   | float 0..1                          | 1.0 on explicit channels                                 |
| `channel`      | §3.1                               |                                                          |
| `reason_codes` | list of strings                     | short snake_case audit codes, never model reasoning text |

`TaskSlots`


| Field           | Type                                    | Rule                                      |
| --------------- | --------------------------------------- | ----------------------------------------- |
| `task_subtype`      | §3.3                                    |                                           |
| `query_rewrite`     | string \| null                          | normalized retrieval question             |
| `time_range`        | string \| null                          | e.g. `last_2_years`                       |
| `domain_hints`      | list of strings                         | e.g. `["hematology"]`                     |
| `source_prefs`      | list of source kinds (§6.5)             | hints only, not an executable plan        |
| `entity_hints`      | list of strings                         | e.g. `["rbc", "amoxicillin"]`             |
| `speak_policy`      | `none` \| `text_only` \| `text_and_tts` | `intervene=false` ⇒ never `text_and_tts` |
| `sub_asks`          | list of `SubAsk`                        | evidence breakdown from Stage B; `[]` until Stage B ships (#55) |
| `readings_conflict` | bool                                    | true when sub-asks reference contradictory readings; triggers `clarify` |

`SubAsk` (§12.3): `sub_ask_id`, `span`, `class_scores` (evidence class → float), `entity_hints`, `domain_hints` (free text), `scope_ids` (canonical scope library ids set by the scope gate), `time_range`, `depends_on`. A class is accepted at `SUB_ASK_MIN_CONFIDENCE`. Stage B never emits tool ids.

**Evidence classes:** `session` · `measurement` · `document` · `trajectory` · `compare` · `safety` · `general` · `note` · `session_control` · `no_workflow`. Compile is a Lane B trigger and document intake is gateway-owned; neither is an ask.

`validate_intent_decision()` enforces the enums, types, and cross-field rules.
It also rejects forbidden keys anywhere in the decision: `plan`, `tool_ids`,
`tool_args`, and scope keys (`patient_id`, `clinician_id`, `session_id`,
`tenant_id`). Output that fails validation counts as a gate failure (§4.1 rule 5).

### 3.5 `intent.decision` audit event

Envelope type `IntentDecisionEvent`. One event per gate decision.


| Field                    | Notes                                                              |
| ------------------------ | ------------------------------------------------------------------ |
| `contract_version`       | `1.2`                                                              |
| `event_id`, `session_id` | opaque ids                                                         |
| `source`                 | `explicit_channel` \| `heuristics` \| `router_model` \| `fallback` |
| `speaker`                | `Clinician` \| `Patient` \| null for UI input                      |
| `segment_ref`            | transcript segment or UI message id.**No raw utterance text.**     |
| `decision`               | `IntentDecision`                                                   |
| `mode`                   | §4.2                                                              |
| `latency_ms`             | gate latency                                                       |
| `created_at`             | ISO-8601                                                           |

### 3.6 What the gate may and may not do

**May:** set the addressee (explicit channels short-circuit to `copilot`), set
the task subtype and slots, set `intervene` and urgency.

**Must not:** choose tool ids or tool order, answer the clinical question,
write structured record fields, supply `patient_id` / tenant, or run on the
`POST /transcribe` request thread.

---

## 4. Intervention policy

Implemented by `resolve_intervention()` in `server/app/agents/intent/policy.py`.

### 4.1 Rules

1. **Silence is the default** for anything heard in the room. In v1, ambient transcript is always silent.
2. **Explicit channels always get a visible response:** an answer, a job, or a clarifying question.
3. **Ambient never auto-answers.** With the research flag on, a copilot-directed ambient utterance can at most produce a suggestion chip.
4. **Voice never ends or signs off a session.** `wake_word` + `session_control` yields a confirm chip; only the UI button runs it.
5. **Gate failure** (timeout, error, invalid output): explicit channels answer with the `general` cascade (reason code `default_factoid_chain`); ambient stays silent and logs.
6. **Push safety alerts** from Lane B bypass the gate and render as `alert` cards (§7.2).

### 4.2 Modes


| Mode           | `intervene` | `urgency`   | `speak_policy`                     | UI behavior                                              |
| -------------- | ----------- | ----------- | ---------------------------------- | -------------------------------------------------------- |
| `silent`       | false       | silent      | none                               | nothing                                                  |
| `suggest_chip` | false       | background  | text_only                          | subtle chip; clicking resubmits as`explicit_ui`          |
| `answer`       | true        | interactive | text_only (text_and_tts if TTS on) | answer card with citations                               |
| `job`          | true        | interactive | text_only                          | job progress, then result                                |
| `clarify`      | true        | interactive | text_only                          | one short clarifying question                            |
| `alert`        | true        | interactive | text_only                          | safety alert card; produced by Lane B, never by the gate |

### 4.3 Decision table

Research chip threshold: addressee confidence ≥ `0.6`.


| Task                                         | `explicit_ui`                    | `wake_word`            | `ambient_transcript` (v1) | `ambient_transcript` (research flag)              |
| -------------------------------------------- | -------------------------------- | ---------------------- | ------------------------- | ------------------------------------------------- |
| `factoid`, `trajectory`, `compare`, `safety` | answer                           | answer                 | silent                    | copilot ∧ conf ≥ threshold: chip · else silent |
| `note`, `compile`, `doc_ingest`              | job                              | job                    | silent                    | copilot ∧ conf ≥ threshold: chip · else silent |
| `session_control`                            | job (button is the confirmation) | chip (confirm)         | silent                    | silent                                            |
| `unknown` or no task                         | clarify                          | clarify                | silent                    | silent                                            |
| gate failure                                 | answer (general cascade)         | answer (general cascade) | silent                  | silent                                            |

### 4.4 Frozen vs provisional

- **Frozen:** rules §4.1, modes §4.2, and the table shape in §4.3.
- **Provisional:** the chip threshold. It only matters if ambient research starts.

---

## 5. Executor

Tables and validators in `server/app/agents/intent/executor_contract.py`.

### 5.1 Fixed workflows

Each fixed workflow is named after the evidence class it serves (`workflow_id_for()`).
Tool order inside a workflow is the workflow's own (#56), not a contract table.

| Evidence class | Workflow id |
| -------------- | ----------- |
| `session`, `measurement`, `document`, `trajectory`, `compare`, `safety` | same as the class |
| `general` | `general_cascade` |
| `note`, `session_control` | `jobs` |
| `no_workflow` | none; dispatch rule 3 |

### 5.2 Dispatch

`dispatch_assist(context, slots)` is a pure code function returning a
`DispatchDecision`: `dispatch`, `dispatch_rule`, `clarify_kind` (set iff
`dispatch` is `clarify`), `reason_codes`, `workflow_ids` (one per workflow run,
in sub-ask order). It fills the merged `route` span. It validates the context
and the sub-asks and raises `ContractViolationError` on invalid input. First
match wins:

| # | Condition | `dispatch` | `clarify_kind` |
| - | --------- | ---------- | -------------- |
| 1 | `ambient_transcript` (v1) | `silent` | — |
| 2 | `readings_conflict` | `clarify` | `reading` |
| 2 | no sub-asks, or a sub-ask with no accepted class | `clarify` | `rephrase` |
| 2 | a retrieval sub-ask with no entity hint, domain hint, or scope id | `clarify` | `scope` |
| 3 | any `depends_on`, or an accepted `no_workflow` class | `clarify` (`planning_agent` once #58 lands); logs `needs_plan` | `narrow` (dependencies) / `rephrase` |
| 4 | exactly one workflow | `workflow` | — |
| 5 | 2 to `MAX_FANOUT_WORKFLOWS` (`3`) workflows | `fanout` | — |
| 6 | more than the cap | `clarify` | `narrow` |

Rules 4 to 6 count workflows, not sub-asks: one sub-ask with two accepted
classes fans out to both.

**`ClarifyRequest`** (§12.4): `kind` (`scope` | `reading` | `rephrase` | `narrow`), `choices` (list of `ScopeChoice`: `scope_id`, `rank`, `label`, `supporting_citation_ids`, `expands_to`), `allow_free_text`. No model writes a free-text clarifying question. `supporting_citation_ids` are `citation_id`s of chart rows.

**`PhysicianChoice`** on the still-processing card: `processed_pages` | `reask` | `none`. Durable notify-when-ready is deferred.

### 5.3 Grounding check

**Groundedness means citation correctness, not citation presence.** Before an
assist answer renders, each patient-fact claim's citation must resolve to a real
source record that contains the stated value (SQL row match or chunk
entailment).

`GroundingReport`: `claims_checked`, `unsupported_claim_ids`, `verdict`
(`render` \| `refuse`). Any unsupported claim blocks rendering; the executor
refuses or re-drafts. How strict to be on partial SQL + RAG mixes is plan §16 Q8.

### 5.4 Request carriers

Declared in `executor_contract.py` (families 1, 3, 4) and `tool_contracts.py`
(family 2). Field-level readers are in SDD Appendix A.

**`AssistRequestContext`** — one per request: `request_id`, `session_id`,
`trace_id`, `channel`, `watermarks`, `deadline_at` (absolute ISO-8601 with
offset; no remaining-ms fields anywhere), `resumes_answer_id`, and runtime
scope `patient_id`, `clinician_id` from the verified gateway token. Never
serialized into a model prompt. `validate_request_context()` checks it.

**`ReceiptWatermarks`** — what the request may see, captured once:
`as_of_receipt`, `snapshot_generation`, `transcript_stream_id`,
`draft_version` (null until the first compile).

**`EvidenceBundle`** (§6.4) — one per request, append-only, closed before
synthesis.

**`WorkflowOutcome`** — closed union, `kind` in `completed` (carries `bundle`),
`clarification_needed` (carries `clarify`), `planning_needed` (carries
`plan_request`). `validate_workflow_outcome()` rejects any other shape.

**`PlanRequest`** — immutable handoff: `workflow_id`, `reason`, `goal`,
`scope` (Stage B sub-asks, no scope keys), `unmet_requirements`,
`evidence_ref`. **`EvidenceRef`**: `bundle_id`, `receipt_ids`, `citation_ids`,
the evidence as it stood at handoff (`make_evidence_ref()`). The cutoff and
deadline are read from the context and `sources_checked` from the bundle;
they are not copied here.

**`AssistAnswer`** — `answer_id`, `request_id`, `session_id`, `status`
(`answered` | `refused` | `clarifying` | `still_processing`), `claims`,
`cited`, `bundle_ref`, `grounding`, `clarify`, `coverage`, `watermarks`,
`resumes_answer_id` (the one answer-chain field), `created_at`.
`validate_assist_answer()` enforces that `cited` equals the closure of the
claims' `citation_ids` and derivation inputs, and the per-status rules.

---

## 6. Shared tool registry

Types and validators in `server/app/agents/tool_contracts.py`. The registry
itself is **Phase 1 critical path** under `server/app/agents/tools/`.

### 6.1 One registry, three callers


| Caller           | Who                                           |
| ---------------- | --------------------------------------------- |
| `lane_b_stage`   | a compile stage (§6.3)                        |
| `fixed_executor` | a fixed assist workflow or job (§5.1)         |
| `planning_agent` | a planning agent step or handoff run (§5.2)   |

All three call the same implementations, so ranking, citation rules, and
receipts cannot drift. No tool writes PostgreSQL.

**Scope injection:** `patient_id`, `clinician_id`, and `session_id` are bound
by the runtime from the verified session; `tenant_id` is never a runtime scope
and is rejected so a model cannot supply one. `validate_model_tool_args()` rejects
them anywhere in model-supplied args, including nested objects.

### 6.2 Tool ids

Compute tools (`normalize_units`, `compute_trend`, `compute_delta`) are LLM-free and planner-allowlisted (#85). Safety tools return `not_covered` when outside rule coverage.


| Tool id                   | Category  | Lane B stage          | Fixed executor | Planner allowlist | Writes          | Must cite when ok |
| ------------------------- | --------- | --------------------- | -------------- | ----------------- | --------------- | ----------------- |
| `retrieve_session`        | retrieval | `enrich`              | yes            | yes               | none            | yes               |
| `retrieve_structured`     | retrieval | `enrich`              | yes            | yes               | none            | yes               |
| `retrieve_source_chunks`  | retrieval | `enrich`              | yes            | yes               | none            | yes               |
| `get_patient_profile`     | retrieval | `enrich`              | yes            | yes               | none            | yes               |
| `retrieve_docs`           | retrieval | `enrich`              | yes            | yes               | none            | yes               |
| `retrieve_visits`         | retrieval | `enrich`              | yes            | yes               | none            | yes               |
| `retrieve_for_candidates` | retrieval | `enrich` (primary)    | no             | no                | none            | yes               |
| `ingest_delta`            | ingest    | `ingest_delta`        | no             | no                | session scratch | no                |
| `compare_findings`        | compare   | `enrich`              | yes            | yes               | none            | yes               |
| `generate_note`           | note      | —                     | yes            | no                | session draft   | no                |
| `check_med_conflicts`     | safety    | `safety_and_validate` | yes            | no                | none            | no                |
| `check_dosage`            | safety    | `safety_and_validate` | yes            | no                | none            | no                |
| `check_metric_alerts`     | safety    | `safety_and_validate` | yes            | no                | none            | no                |
| `normalize_units`         | compute   | —                     | yes            | yes               | none            | no                |
| `compute_trend`           | compute   | —                     | yes            | yes               | none            | no                |
| `compute_delta`           | compute   | —                     | yes            | yes               | none            | no                |

### 6.3 Lane B stage names (target)

`ingest_delta` → `compile_candidates` → `enrich` → `materialize_record` →
`safety_and_validate` → `finalize`, plus conditional `repair` /
`conflict_resolution`. `graph.py` keeps its current 16 node names until Phase 3.

### 6.4 `ToolResult`, `Citation`, receipts

`ToolResult`: `tool_id`, `ok`, `data`, `citations`, `error`, `receipt`.

`Citation` (1.2): `citation_id` (`{source_kind}:{source_id}`, stable per source, never a chunk id), `source_kind`, `source_id`, `snippet`, `observed_at`, required `received_at` (when the source entered the system), required `evidence_state` (`received` | `materialized` | `validated` | `authorized`), `locator`, `score`.

`CitationLocator` is a union tagged on `kind`; the shape follows `source_kind`:

| `kind` | Fields | Source kinds |
| ------ | ------ | ------------ |
| `document_span` | `doc_id` (= `source_id`), `chunk_id`, `page`, `char_start`, `char_end` | `document` |
| `transcript_span` | `segment_id` (= `source_id`), `t_start`, `t_end` | `session_transcript` |
| `row_ref` | `table`, `row_id` (= `source_id`), `column` | `observation`, `visit` |
| none | | `session_draft`, `patient_snapshot` |

`Claim` (1.2): `claim_id`, `text`, `claim_type`, `value`, `unit`, `date`, `negated`, `citation_ids`, `derivation`, `evidence_state` (weakest among its citations). `Derivation`: `operation` (compute tool id), `input_citation_ids`, `receipt_id`. All ids are `citation_id`s. The strict grounding validator re-checks a derived value against its compute receipt before allowing it to render (§5.3).

`validate_tool_result()` enforces the presence floor (§5.3 checks correctness):

- A "must cite" tool cannot return `ok=true` without citations.
- A retrieval miss is `ok=false` with `error="no_source"` (`no_source`), so the answer says "no documented value".
- Safety tools return `error="not_covered"` (`not_covered`) when the requested check is outside the current rule set's coverage.
- `compare_findings` refuses if either side has no citations.

`ToolInvocationReceipt` (internal `tool.invocation` event, also appended to
`controls.trace_log`): `contract_version`, `invocation_id`, `session_id`,
`tool_id`, `tool_version`, `caller`, `caller_ref` (stage name or
`intent.decision` event id), `args_hash` (**hash only — no raw args, query
text, or PHI**), `ok`, `error` (equals `ToolResult.error`), `cache_hit`,
`latency_ms`, `source_refs`, `created_at`.

**`EvidenceBundle`**: `bundle_id`, `results`, `citations` (keyed by
`citation_id`, so a source cited twice appears once), `sources_checked`
(`{tool_id}:{args_hash}`), `coverage`, `closed`. `append_result()` validates
each result, drops and logs a repeat of the same tool and args, and raises
`BundleClosedError` after `close_bundle()`. Receipt ids are read from
`results[].receipt`.

**`CoverageBanner`**: `requirements` (list of `RequirementOutcome`),
`unreferenced_inflight_doc_ids`, `partial_sources`. **`RequirementOutcome`**:
`doc_id`, `need` (`received` < `described` < `indexed` < `facts`), `status`
(`met` | `unmet_terminal` | `pending`), `failure_code` (`unreadable_file` |
`ocr_failed` | `extraction_failed` | `timeout`, set only for `unmet_terminal`).

### 6.5 Source kinds


A source kind names what a source is, never when it arrived. Whether a
document came in this session is read from `ingest_documents.session_id`.

| Source kind          | Meaning                                   |
| -------------------- | ----------------------------------------- |
| `session_transcript` | current encounter transcript              |
| `session_draft`      | current structured draft in Redis         |
| `patient_snapshot`   | session-cached patient context (plan §6) |
| `document`           | an ingested document, any session         |
| `observation`        | a structured observation row (labs, vitals, meds, allergies, problems) |
| `visit`              | a visit record                            |

---

## 7. Lane B outputs

Types and helpers in `server/app/agents/compile_contracts.py`. Push alerts ship
in Phase 3; delta compile in Phase 4. The semantics are fixed now.

### 7.1 `LaneBOutputs`


| Field               | Notes                                           |
| ------------------- | ----------------------------------------------- |
| `draft_version`     | increments per successful compile               |
| `candidate_facts`   | `CandidateFact` + `FactIdentity` fields (§7.3) |
| `structured_record` | draft, materialized from`active` facts          |
| `validation_report` | hard validate + soft score + conflicts          |
| `safety_alerts`     | push path;**always present**, may be empty      |

Review items live in Postgres `review_items` (SDD §4.7), not in Lane B output.

Not necessarily a SOAP note.

### 7.2 Push safety

`copilot`-asked `safety` is the pull path. The push path raises alerts without
the clinician asking:

```text
safety_and_validate -> check_med_conflicts / check_dosage / check_metric_alerts -> SafetyAlertCard -> Redis alert channel + UI card
```

`SafetyAlertCard`: `alert_id`, `session_id`, `alert_type`
(`allergy` \| `interaction` \| `contraindication`), `severity`, `message`,
`fact_keys`, `evidence` (citations).

Severity uses the vocabulary `app/core/clinical_suggestions.py` already emits:
`critical`, `major`, `moderate`, `info`. `critical` and `major` render an alert
card (provisional); `moderate` and `info` attach to the draft / review panel
without interrupting. Push alerts never block Lane A and never persist.

### 7.3 Delta compile

Background compiles **merge**; they do not rebuild conflicting drafts.

**Fact identity.** `fact_key = canonical_type:entity[:qualifier]`, e.g.
`allergy:amoxicillin`, `lab:rbc:2024-11-02`, `med:lisinopril`. Build keys with
`make_fact_key()`. Each candidate fact also has `fact_id`, `status`,
`superseded_by`, `confidence` (`FactIdentity`), and `provenance`, a
`FactProvenance`: `evidence` (list of `Citation`), `extractor`,
`prompt_version`. The documents and transcript segments a fact came from are
the `source_id`s of its evidence, read with `fact_source_ids()`.

**Statuses:** `active` · `superseded` · `retracted` · `needs_review`

**Supersession rules**

1. A later correction marks the prior fact `superseded`, or `retracted` if explicitly negated, and sets `superseded_by` to the new `fact_id` (`supersede()`).
2. Provenance stays on both old and new facts so audit shows the self-correction.
3. Materialization uses `active` facts. Superseded rows stay in the working set for trace; nothing is deleted.
4. A draft never holds two `active` facts with the same key (`duplicate_active_keys()` must be empty).

**Interaction with review** (`DELTA_ACTION`). The review state is derived
from `review_items` and the chart write record, never stored; `DELTA_ACTION`
is its only reader.


| Where the fact already is | Action                                                                                                           |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `working_draft`           | `merge` under the rules above                                                                                    |
| `open_review`             | `attach_delta_note`; bump package version and mark UI dirty. Never silently remove or downgrade the queued item. |
| `approved_pending_write`  | `open_new_review_item`; approval is sticky                                                                       |
| `persisted`               | `open_new_review_item`                                                                                           |

**`CompileJob`:** `session_id`, `base_draft_version`, `new_segment_ids`,
`new_doc_ids`, `full_recompute`. If `base_draft_version` is stale, the job
rebases or retries. It never clobbers a newer draft.

**Phase 4 exit:** a gold session where an allergy is stated then corrected
yields one active fact, one superseded or retracted fact, stable review
behavior, and no duplicate actives.

---

## 8. Invariants

Checkable rules for code review.

1. Lane A calls no LLM. `POST /transcribe` does no gate call, retrieval, compile, or PostgreSQL write on the request thread.
2. The gate never emits tool ids, tool order, or scope keys. Stage B emits `sub_asks` (evidence descriptions only).
3. Model-supplied tool args never carry `patient_id`, `clinician_id`, `session_id`, or `tenant_id`.
4. No tool has a PostgreSQL write mode. Only Lane C writes durable patient-record changes, and only approved ones.
5. An assist answer renders only after the grounding check passes. With no source, it says so. A derived value renders only with a compute receipt.
6. The `planning_agent` runs only on dispatch rule 3 or a `planning_needed` outcome, and not at all until #58; a `PlanRequest` is immutable and never re-runs an entry in the bundle's `sources_checked`; every clarify is a structured `ClarifyRequest`.
7. Lane B, fixed executors, and the `planning_agent` call the same tool implementations through one registry (`lane_b_stage`, `fixed_executor`, `planning_agent`).
8. Review never blocks transcript or assist answers. No `interrupt_before` on the normal visit path.
9. Lane B outputs always carry `safety_alerts`. Delta compiles never silently override an open or approved review item.
10. Note generation is a tool/job, never a required compile step.
11. Retrieval never returns evidence received after `as_of_receipt`, read from `AssistRequestContext.watermarks`. Evidence states: `received`, `materialized`, `validated`, `authorized`.
12. The evidence bundle is append-only and closed before synthesis; an answer's `cited` equals the citation closure of its claims.

---

## 9. Golden sets

Split the same way as the gate (§3.2), because the two stages have different
error costs and metrics.

**`intent_task_v2.jsonl`**: explicit-channel rows for Stage B (renamed from v1 in 1.2 PR #50).


| Field                   | Meaning                                                                       |
| ----------------------- | ----------------------------------------------------------------------------- |
| `id`                    | unique row id                                                                 |
| `channel`               | `explicit_ui` \| `wake_word`                                                  |
| `text`                  | typed message or spoken ask                                                   |
| `expected_task_subtype` | §3.3                                                                          |
| `expected_mode`         | policy outcome                                                                |
| `expected_sub_asks`     | list of `SubAsk` objects the gate should produce                              |
| `expected_dispatch`     | `silent` \| `clarify` \| `workflow` \| `fanout` (`planning_agent` not used while the planner is deferred) |
| `expected_dispatch_rule`| row of the §5.2 table, 1 to 6                                                  |
| `source_prefs`, `note`  | optional slot labels                                                          |

**`intent_addressee_v1.jsonl`**: ambient rows for Stage A.


| Field                     | Meaning                                       |
| ------------------------- | --------------------------------------------- |
| `id`                      | `amb-*`                                       |
| `speaker`                 | `Clinician` \| `Patient`                      |
| `text`                    | utterance                                     |
| `expected_addressee`      | §3.3                                         |
| `task_subtype_if_copilot` | required iff`expected_addressee` is `copilot` |
| `note`                    | optional                                      |

**Now:** tests check that every task row yields `expected_mode` and that
`dispatch_assist()` on its `expected_sub_asks` yields `expected_dispatch` and
`expected_dispatch_rule`, and that every addressee row is silent in v1 and
chips only on copilot rows under the research flag.

**Later:** the task set seeds Phase 2 slot-extraction and agent evals (subtype
accuracy, tool coverage, grounding). The addressee set seeds research precision
evals, the primary metric if ambient ever ships.

Hard negatives are included on purpose: "What was your last blood pressure
reading?", history questions about labs and allergies, "compared to your last
visit", patient questions about their own labs, and a goodbye that is not
session control. Append rows to grow the sets. Relabeling a row is a
decision-log entry.

---

## 10. Change control

A PR that changes any of these:

- addressee, channel, task subtype, evidence class, lane, mode, dispatch, clarify, outcome, answer status, or encounter status enums
- `IntentDecision`, `AddresseeDecision`, `TaskSlots`, `IntentDecisionEvent` fields
- tool ids, a tool's row in §6.2, tool callers, Lane B stage names, or source kinds
- `ToolResult`, `Citation`, `CitationLocator`, `ToolInvocationReceipt`, `EvidenceBundle`, `CoverageBanner`, `LaneBOutputs`, `SafetyAlertCard`, `FactIdentity`, `FactProvenance`, `CompileJob` fields
- `AssistRequestContext`, `ReceiptWatermarks`, `DispatchDecision`, `WorkflowOutcome`, `PlanRequest`, `EvidenceRef`, `AssistAnswer` fields
- fact statuses, review states, `DELTA_ACTION`, safety severities
- a rule in §4.1, §5, §6.1, §6.4, or §7, or a row in §4.3

must, in the same PR:

1. bump `RUNTIME_CONTRACT_VERSION` in `tool_contracts.py`
2. update this document and the code in `intent/`, `tool_contracts.py`, `compile_contracts.py`
3. update the golden sets and `test_intent_contract.py`
4. add a row to the decision log in [agent_refactor_plan.md §15](./agent_refactor_plan.md#15-decision-log)

Provisional numbers (chip threshold `0.6`, `SUB_ASK_MIN_CONFIDENCE` `0.75`,
`MAX_FANOUT_WORKFLOWS` `3`, `REFERENCE_RESOLUTION_WAIT_MS` `3000`,
`RECHECK_INTERVAL_MS` `1000`, `POST_BARRIER_RESERVE_MS` `3300`, push-alert
severities) can change
without a version bump when backed by eval or latency evidence. Provisional
numbers live in `agents/config.py` and are imported from there.

`TestContractDocSync` fails if this document stops naming a code enum value or a
current provisional number, or reintroduces a superseded 1.0 name.

---

## 11. Phase 0 exit checklist

- [X]  Lane A / A-assist / B / C defined in product language (§1)
- [X]  Fixed vs bounded agent chosen per lane and task (§2)
- [X]  Two-stage gate typed; no plan field (§3, `schemas.py`)
- [X]  Silence-default policy as rules, table, and tested code (§4, `policy.py`)
- [X]  Executor-owned plans, agent limits, grounding check (§5, `executor_contract.py`)
- [X]  Shared tool registry with scope injection and agent allowlist (§6, `tool_contracts.py`)
- [X]  Lane B outputs, push safety, delta-compile semantics (§7, `compile_contracts.py`)
- [X]  Golden sets split into task and addressee (§9)
- [X]  Linked from `agentic_design.md`, `architecture.md`, `docs/api/assistant.md`, and the refactor plan
- [X]  Team sign-off: §2 matrix and §3 gate contract
- [X]  Team sign-off: §4 intervene rules
- [X]  Team sign-off: §6 tool registry and §7 Lane B outputs

Open questions that **do not block** Phase 0 (numbering from plan §16):

- Q1 wake word vs text box only: the contract supports both channels
- Q2 progress aliases after graph collapse: Phase 3
- Q3 slot-extraction model tier: Phase 2
- Q4 compare "new side" default, Q5 assist ingest triggering compile, Q8 grounding strictness: Phase 2 executor policy
- Q6 where trajectory/compare answers live: Phase 2 UI
- Q7 local addressee model: research only
