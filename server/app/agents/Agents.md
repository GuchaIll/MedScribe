) ingest_node (Preprocessing stage: ingestion + artifact registration)

Purpose: create a session artifact set, sanitize inputs, basic metadata.

Consumes: raw transcript segments, PDFs

Produces: state.transcript, state.documents, initial trace

Deterministic work:

ensure timestamps monotonic

drop empty segments

tag docs by type

Tools used: pdf text extraction tool, table extractor tool

Failure modes: PDF parse fails → mark doc as “unparsed” and continue

B) normalize_transcript_node (Preprocessing stage: complexity + structure analysis)

Purpose: normalize speaker roles, cleanup text, and compute complexity signals that influence later extraction strategy.

Consumes: state.transcript

Produces:

normalized speaker labels (Doctor/Patient/Other)

state.inputs["complexity"] = {...} (e.g., multi-speaker, interruptions)

Deterministic work:

unit normalization (mg, mcg, mmol/L)

expand common abbreviations (optional)

Tools used: optional LLM for diarization correction; rules-based normalizer

Failure modes: speaker unknown → keep as None but tag for extractor

Complexity metrics examples:

num_speakers_detected

avg_segment_length

medical_term_density

contradiction_likelihood (heuristic)

C) segment_and_chunk_node (Preprocessing stage: chunking policy)

Purpose: produce stable chunks for extraction + evidence provenance.

Consumes: normalized transcript + doc texts

Produces: state.chunks

Deterministic work:

chunk transcript by topic/speaker turns (not just fixed token window)

chunk PDFs separately: narrative chunks + table chunks

Tools used: optional semantic splitter (LLM) but preferably deterministic + heuristics

Failure modes: doc too long → cap / multi-pass chunking

Why this matters: good chunking is policy, not capability. It’s a node.

D) extract_candidates_node (Initial Extraction stage)

Purpose: extract candidate facts with confidence + local evidence pointers.

Consumes: state.chunks

Produces: state.candidates (CandidateFact objects)

Deterministic work:

canonicalize entities (drug names, allergies)

assign fact_type with strict schema

Tools used: LLM extraction tool (JSON-only), medical NER tool (optional)

Failure modes: invalid JSON → repair prompt / retry (counts toward budget)

Output quality rule: candidates must always include at least one evidence span (even if weak).

E) retrieve_evidence_node (Evidence Linking stage — “RAG but for provenance”)

Purpose: retrieve additional evidence for each candidate and strengthen traceability.

Consumes: state.candidates, state.chunks, documents

Produces: updates CandidateFact.evidence with stronger spans + ranking

Deterministic work:

deduplicate evidence

enforce snippet length

Tools used: embeddings + vector search, keyword search, reranker

Failure modes: no evidence found → downgrade confidence + flag for review

This is the “anti-chatbot” RAG: retrieval is used to justify fields, not answer questions.

F) fill_structured_record_node (Synthesis stage: record construction)

Purpose: map candidates into a strict structured record schema + build provenance per field.

Consumes: candidates + evidence

Produces: state.record, state.provenance

Deterministic work:

field mapping rules (fact_type → record paths)

merging duplicates (same med, repeated allergy)

prefer higher-confidence facts

Tools used: minimal or none; optionally LLM for complex mapping, but avoid if possible

Failure modes: missing required fields → leave empty but produce validation errors later

G) validate_and_score_node (Validation stage — routing authority)

Purpose: enforce contracts, compute field-level confidence, and detect contradictions.

Consumes: record + provenance + candidates

Produces: state.validation, state.conflicts

Deterministic checks:

schema (types, required fields)

format constraints (DOB ISO date)

sanity constraints (age range, dosages)

cross-field checks (penicillin allergy vs amoxicillin)

Tools used: optional LLM “clinical validator” ONLY for ambiguous cases; deterministic first

Failure modes: too many errors → route to fallback or repair loop

Routing signals set here:

schema_errors → repair

conflicts → conflict resolution

needs_review → human gate

else → generate note

H) repair_node (Refinement stage — bounded)

Purpose: targeted re-extraction or patching based on specific validation failures.

Consumes: validation errors + conflict seeds

Produces: updated candidates/record pieces

Deterministic policy:

max N retries

only retry missing/invalid fields

prohibit rewriting already high-confidence fields

Tools used: constrained LLM prompts (“fill only these fields”), or deterministic regex extraction

Failure modes: budget exceeded → fallback or needs_review

I) conflict_resolution_node (Refinement stage — policy-based)

Purpose: resolve contradictions using policies + evidence.

Consumes: conflict report items + evidence

Produces: resolved conflicts or escalations; patched record/provenance

Deterministic policy examples:

prefer most recent dated source

prefer “med list” doc over transcript mention

if tie → keep both + mark needs_review

Tools used: optional LLM for “resolution rationale”, not for the decision

Failure modes: unresolved → human gate

J) human_review_gate_node (Terminal decision)

Purpose: produce “needs_review” output with crisp questions.

Consumes: unresolved conflicts / low confidence fields

Produces: outputs.status="needs_review", outputs.review_questions

Deterministic behavior:

generate minimal set of questions (1–5)

include evidence snippets in UI (not as questions)

Tools used: optionally LLM to draft question text, but can be template-driven

K) generate_note_node (Synthesis stage)

Purpose: generate final clinical note from structured record only (no hallucinating).

Consumes: state.record

Produces: outputs.clinical_note

Deterministic constraints:

disallow adding concepts not in record

include warnings/conflicts section if present

Tools used: LLM summarizer with strict grounding (“use only provided JSON”)

L) package_outputs_node (Packaging / export stage)

Purpose: assemble final artifacts.

Consumes: record + provenance + validation + conflicts + note

Produces: outputs.*, set done/needs_review/failed

Deterministic work:

JSON export

markdown note export

audit log export

trace summary

3) “Agents” with purpose and boundaries (who does what)

In LangGraph terms, “agent” = a node’s internal reasoning module(s) + tools. Here’s a crisp set of agents that map cleanly to nodes:

Agent A — Transcript Analyst (Preprocessing)

Used by: normalize_transcript_node

Purpose: determine transcript complexity, speaker roles, noisy segments

Output: normalized transcript + complexity report

Hard constraint: never invent medical facts

Agent B — Candidate Extractor (Initial Extraction)

Used by: extract_candidates_node

Purpose: produce typed candidate facts (JSON) with initial evidence spans

Output: CandidateFact[]

Hard constraint: must include evidence spans; no evidence → low confidence

Agent C — Evidence Linker (Provenance Retrieval)

Used by: retrieve_evidence_node

Purpose: strengthen evidence for each candidate across PDFs/transcript

Output: updated candidate evidence ranking

Hard constraint: evidence snippets must be short + exact

Agent D — Record Compiler (Schema Mapper)

Used by: fill_structured_record_node

Purpose: assemble canonical structured record + field provenance

Output: StructuredClinicalRecord, provenance list

Hard constraint: only compile from candidates with evidence

Agent E — Validator (Rules-first)

Used by: validate_and_score_node

Purpose: schema + sanity + cross-field checks; produce validation/conflicts

Output: validation report, conflict report, routing signals

Hard constraint: deterministic rules are primary; LLM only for ambiguity

Agent F — Repair Specialist (Targeted)

Used by: repair_node

Purpose: fix only specific missing/invalid fields; bounded iterations

Output: patched candidates/record, updated confidence

Hard constraint: cannot rewrite already-validated high-confidence fields

Agent G — Conflict Arbiter (Policy-based)

Used by: conflict_resolution_node

Purpose: resolve contradictions using evidence + policy; else escalate

Output: updated record + conflict decisions

Hard constraint: if policy can’t decide, escalate

Agent H — Note Generator (Grounded)

Used by: generate_note_node

Purpose: produce human-readable note grounded in structured record

Output: note text

Hard constraint: no new entities not present in record

Agent I — Review Gatekeeper (HITL)

Used by: human_review_gate_node

Purpose: ask minimal questions needed to resolve uncertainty

Output: review questions + what evidence triggered them

Hard constraint: questions must be answerable and specific

4) Implementation tips that make this “systems” (not chatbot)
Add a simple state.controls.attempts[node] += 1 helper

Every node increments attempts; repair checks this.

Keep a trace entry per node

Store:

what changed (counts, confidences)

time spent

llm calls used

Enforce “grounding” at the schema boundary

Only allow generate_note_node to read state.record, not raw docs.

5) Mapping to your existing “Fallback Node”

Your fallback is a separate route when:

too many schema errors after repair budget

extraction JSON repeatedly invalid

transcript complexity too high

Fallback behavior:

skip conflict resolution loops

extract only “core fields” (dx, meds, allergies, follow-up)

mark needs_review=True