# MedScribe — System Architecture

## C4 Component Diagram

```mermaid
C4Component
    title MedScribe System Architecture

    Container_Boundary(fe, "Browser Client — React 18 + TypeScript") {
        Component(vad, "Silero VAD + Web Speech API", "ONNX / Browser API", "50-100ms speech onset detection via @ricky0123/vad-react; gates Web Speech to prevent missed utterance starts")
        Component(ui, "MedicalTranscription", "React Component", "Session lifecycle, segment accumulation, pipeline trigger, record display")
        Component(upload, "Document Upload", "React Component", "Multipart PDF and image upload")
    }

    Container_Boundary(api, "FastAPI Backend — Port 3001") {
        Component(sess, "Session Router", "FastAPI Router", "/api/session/* — start, end, transcribe, upload, queue, pipeline/status")
        Component(pipe, "Pipeline Endpoint", "FastAPI Router", "POST /api/session/{id}/pipeline — initialises GraphState and invokes WorkflowEngine")
        Component(clin, "Clinical Router", "FastAPI Router", "/api/clinical/* — on-demand allergy and interaction checks")
        Component(rec, "Records Router", "FastAPI Router", "/api/records/* — Jinja2 template selection and WeasyPrint document generation")
    }

    Container_Boundary(lg, "LangGraph Workflow Engine — server/app/agents/") {

        Container_Boundary(phase0, "Preamble") {
            Component(greet, "greeting", "LangGraph Node", "Seeds initial state; sets welcome message for physician")
            Component(loadctx, "load_patient_context", "LangGraph Node", "Loads prior patient facts, demographics, and visit history from PostgreSQL into GraphState")
        }

        Container_Boundary(phase1, "Ingestion Phase") {
            Component(ingest, "ingest", "LangGraph Node", "Loads transcript segments and OCR DocumentArtifacts into GraphState.chunks")
            Component(clean, "clean_transcription", "LangGraph Node", "Removes disfluencies, expands medical abbreviations")
            Component(norm, "normalize_transcript", "LangGraph Node", "Standardises medical terminology")
            Component(segment, "segment_and_chunk", "LangGraph Node", "Splits conversation into topical clinical chunks")
        }

        Container_Boundary(phase2, "Extraction Phase") {
            Component(extract, "extract_candidates", "LangGraph Node", "NLP entity extraction — medications, diagnoses, lab values, ICD-10 codes → CandidateFact list")
            Component(diagr, "diagnostic_reasoning", "LangGraph Node", "LLM-assisted differential diagnosis reasoning over extracted candidates")
            Component(evidence, "retrieve_evidence", "LangGraph Node", "pgvector ANN search anchors each CandidateFact to source utterance or document chunk")
            Component(fill, "fill_structured_record", "LangGraph Node", "Maps candidate facts to typed StructuredRecord Pydantic schema")
        }

        Container_Boundary(phase3, "Validation and Safety Phase") {
            Component(sugg, "clinical_suggestions", "LangGraph Node", "Structured lookup against patient allergy list and medication history; LLM used only for disambiguation")
            Component(validate, "validate_and_score", "LangGraph Node", "Pydantic + contract validation, per-field confidence threshold checking, cross-visit contradiction detection. Sets needs_review=True on any error, conflict, or missing required field")
            Component(repair, "repair [loop max 3x]", "LangGraph Node", "LLM-guided schema repair on validation failure; routes back to validate_and_score")
            Component(conflict, "conflict_resolution", "LangGraph Node", "Resolves value discrepancies between extracted facts and stored patient history")
            Component(gate, "human_review_gate", "LangGraph Node — INTERRUPT", "Pauses graph execution (interrupt_before) for physician approval. Currently enable_interrupts=False at the /pipeline endpoint — node runs but does not pause.")
        }

        Container_Boundary(phase4, "Output Phase") {
            Component(generate, "generate_note", "LangGraph Node", "LLM generates structured SOAP clinical note from filled record and patient context")
            Component(pkg, "package_outputs", "LangGraph Node", "Assembles final response payload from generate_note or human_review_gate branch")
            Component(persist, "persist_results", "LangGraph Node", "Writes StructuredRecord, embeddings, and full node-level audit trace (controls.trace_log) to PostgreSQL")
        }
    }

    Container_Boundary(ocr, "OCR Pipeline — server/app/core/ocr/") {
        Component(splitter, "page_splitter", "Stage 1", "Converts PDF pages and images to normalised page images")
        Component(pre, "preprocessor", "Stage 2", "Deskew, denoise, contrast enhancement")
        Component(layout, "layout_detector", "Stage 3", "Region segmentation")
        Component(hw, "handwriting_detector", "Stage 4", "Classifies handwritten vs printed text regions for engine selection")
        Component(ocreng, "extractor", "Stage 5", "RapidOCR with engine fallback for per-region text extraction")
        Component(ocrnorm, "normalizer", "Stage 6", "Medical spelling correction")
        Component(docclass, "document_classifier", "Stage 7", "Document type classification (lab report, discharge summary, referral, etc.)")
        Component(field, "field_extractor", "Stage 8", "Medical NLP patterns and LLM extraction of structured fields with per-field confidence scores")
        Component(confdet, "conflict_detector", "Stage 9", "Flags value conflicts between OCR fields and active patient record")
    }

    Container_Boundary(data, "Data Layer") {
        Component(pg, "PostgreSQL + pgvector", "Primary Database", "Patient profiles, sessions, structured records, embeddings, audit logs")
        Component(chk, "SQLite Checkpoints", "LangGraph SqliteSaver", "Graph state snapshot after every node — keyed by thread_id (session_id). Enables interrupt/resume: graph.invoke(None, config) continues from last checkpoint.")
        Component(groq, "Groq API — llama-3.3-70b-versatile", "External LLM", "SOAP note generation, diagnostic reasoning, schema repair, field disambiguation")
        Component(elevenlabs, "ElevenLabs TTS", "External API", "Clinical note text-to-speech readback (ELEVEN_LABS_API_KEY); browser SpeechSynthesis fallback")
    }

    Rel(vad, ui, "Utterances with timestamps")
    Rel(ui, sess, "POST /api/session/start, /transcribe")
    Rel(ui, pipe, "POST /api/session/{id}/pipeline with accumulated segments")
    Rel(upload, sess, "POST /api/session/{id}/upload multipart")
    Rel(ui, sess, "GET /api/session/{id}/pipeline/status (polls every ~500ms)")

    Rel(sess, ocr, "Dispatches uploaded file to OCR pipeline")
    Rel(splitter, pre, "")
    Rel(pre, layout, "")
    Rel(layout, hw, "")
    Rel(hw, ocreng, "")
    Rel(ocreng, ocrnorm, "")
    Rel(ocrnorm, docclass, "")
    Rel(docclass, field, "")
    Rel(field, confdet, "")
    Rel(confdet, sess, "DocumentProcessingResult stored in session queue")

    Rel(pipe, greet, "Initialises GraphState and invokes WorkflowEngine")
    Rel(greet, loadctx, "")
    Rel(loadctx, ingest, "")
    Rel(ingest, clean, "")
    Rel(clean, norm, "")
    Rel(norm, segment, "")
    Rel(segment, extract, "")
    Rel(extract, diagr, "")
    Rel(diagr, evidence, "")
    Rel(evidence, fill, "")
    Rel(fill, sugg, "")
    Rel(sugg, validate, "")
    Rel(validate, repair, "schema_errors=true AND repair_attempts < 3")
    Rel(repair, validate, "retry")
    Rel(validate, conflict, "conflicts present")
    Rel(validate, gate, "needs_review=true (no schema errors)")
    Rel(validate, generate, "valid, no interrupt required")
    Rel(conflict, gate, "unresolved conflicts")
    Rel(conflict, generate, "all conflicts resolved")
    Rel(gate, pkg, "physician approved (or interrupts disabled)")
    Rel(generate, pkg, "")
    Rel(pkg, persist, "")

    Rel(loadctx, pg, "Load prior patient facts + visit history")
    Rel(evidence, pg, "pgvector ANN embedding query")
    Rel(generate, groq, "LLM completion for SOAP note")
    Rel(diagr, groq, "LLM differential diagnosis reasoning")
    Rel(repair, groq, "LLM schema repair")
    Rel(field, groq, "LLM field disambiguation")
    Rel(persist, pg, "SQLAlchemy ORM — patient record + embeddings write")
    Rel(persist, chk, "LangGraph checkpoint commit after each node")

    Rel(clin, pg, "Patient allergy and medication history lookup")
    Rel(rec, pg, "Fetch structured record for template rendering")
    Rel(rec, elevenlabs, "TTS synthesis on generated note")
```

---

## Persistence Model

Two separate persistence mechanisms serve distinct purposes:

| Store | Technology | What it holds | When written |
|-------|-----------|---------------|--------------|
| **Checkpoints** | SQLite (`storage/checkpoints.db`) | Full `GraphState` snapshot | After every node completes |
| **Patient records** | PostgreSQL + pgvector | `StructuredRecord`, embeddings, audit trace | Only in `persist_results` (final node) |

**Interrupt/resume flow:**
1. Graph runs node-by-node; `SqliteSaver` snapshots `GraphState` to SQLite keyed by `thread_id` (= `session_id`) after each node
2. When `interrupt_before=["human_review_gate"]` is active, the graph pauses and returns before executing that node
3. The partial state lives in SQLite; the pipeline endpoint returns the intermediate state to the caller
4. To resume: call `engine.resume(thread_id)` — internally calls `graph.invoke(None, config={"configurable": {"thread_id": ...}})`, which LangGraph replays from the last checkpoint
5. **Current status:** `enable_interrupts=False` in the `/pipeline` endpoint — the interrupt infrastructure is in place but the gate runs non-interactively

---

## LangGraph Node Reference

All 18 nodes in execution order:

| # | Node | File | Description |
|---|------|------|-------------|
| 1 | `greeting` | `nodes/` (inline in graph.py) | Seeds initial state, sets physician welcome message |
| 2 | `load_patient_context` | `nodes/load_patient_context.py` | Loads prior patient facts from PostgreSQL into `patient_record_fields` |
| 3 | `ingest` | `nodes/ingest.py` | Loads transcript segments + OCR artifacts into `GraphState.chunks` |
| 4 | `clean_transcription` | `nodes/clean.py` | Removes disfluencies, expands abbreviations |
| 5 | `normalize_transcript` | `nodes/normalize.py` | Standardises medical terminology |
| 6 | `segment_and_chunk` | `nodes/segment.py` | Splits transcript into topical clinical chunks |
| 7 | `extract_candidates` | `nodes/extract.py` | NLP entity recognition → `candidate_facts` list |
| 8 | `diagnostic_reasoning` | `nodes/diagnostic_reasoning.py` | LLM differential diagnosis over extracted candidates |
| 9 | `retrieve_evidence` | `nodes/evidence.py` | pgvector ANN search → `evidence_map` (fact_id → source chunks) |
| 10 | `fill_structured_record` | `nodes/fill_record.py` | Maps candidates to typed `StructuredRecord` schema |
| 11 | `clinical_suggestions` | `nodes/clinical_suggestions.py` | Allergy + drug interaction lookup; LLM for disambiguation |
| 12 | `validate_and_score` | `nodes/validate.py` | Pydantic + contract validation; cross-visit contradiction detection; sets `validation_report.needs_review` |
| — | `repair` | `nodes/repair.py` | LLM schema repair (loops back to validate, max 3 iterations) |
| — | `conflict_resolution` | `nodes/conflicts.py` | Resolves discrepancies against stored patient history |
| — | `human_review_gate` | `nodes/review_gate.py` | Interrupt point for physician approval |
| 13+ | `generate_note` | `nodes/generate_note.py` | LLM SOAP note generation |
| 14+ | `package_outputs` | `nodes/package.py` | Assembles final response payload |
| 15+ | `persist_results` | `nodes/persist_results.py` | Writes record, embeddings, audit trace to PostgreSQL |

**Routing from `validate_and_score`** (conditional edges, in priority order):
1. `schema_errors` present AND `repair_attempts < 3` → `repair` → back to `validate_and_score`
2. `conflicts` present → `conflict_resolution` → `human_review_gate` (if unresolved) or `generate_note`
3. `needs_review` true → `human_review_gate` → `package_outputs`
4. Default (valid record) → `generate_note` → `package_outputs`

---

## GraphState Schema

Defined in `server/app/agents/state.py`:

```python
class GraphState(TypedDict):
    # Session identifiers
    session_id: str
    patient_id: str
    doctor_id: str

    # Raw input
    conversation_log: List[ConversationTurn]
    new_segments: List[TranscriptSegment]       # incoming transcript
    documents: List[DocumentArtifact]           # OCR-processed uploads

    # Intermediate state
    session_summary: Optional[Dict[str, Any]]
    patient_record_fields: Optional[Dict[str, Any]]  # loaded from DB by load_patient_context
    chunks: List[ChunkArtifact]                 # segmented text chunks
    candidate_facts: List[CandidateFact]        # extracted clinical facts
    evidence_map: Dict[str, List[EvidenceItem]] # fact_id → source references

    # Validated output
    structured_record: Dict[str, Any]           # filled StructuredRecord
    validation_report: Optional[ValidationReport]
    conflict_report: Optional[ConflictReport]
    clinical_suggestions: Optional[Dict[str, Any]]
    diagnostic_reasoning: Optional[Dict[str, Any]]

    # Final output
    clinical_note: Optional[str]                # generated SOAP note

    # Control flow
    flags: Dict[str, bool]                      # awaiting_human_review, processing_error, etc.
    is_new_patient: bool
    message: Optional[str]
    inputs: Dict[str, Any]
    controls: Controls                          # attempts, budget, trace_log
```

`Controls.trace_log` accumulates a structured entry per node (node name, action, timestamp, detail) and is written to PostgreSQL by `persist_results` as the audit trail.

---

## Confidence Scoring

Per-field confidence is **not** derived from LLM logits. It follows a deterministic rule-based approach:

1. Each `CandidateFact` carries a `confidence: float` set during extraction (0.0–1.0)
2. `validation_contracts.py` defines a `CONTRACT` dict with per-field rules including optional `min_confidence` thresholds
3. `validate_and_score_node` checks each field against its contract — if `fact.confidence < rules["min_confidence"]`, a schema error is recorded
4. `validation_report.needs_review` is set to `True` if **any** of the following are present: schema errors, missing required fields, or intra-session or cross-visit conflicts

---

## OCR Pipeline Reference

| Stage | File | Description |
|-------|------|-------------|
| 1 — Page Splitter | `core/ocr/page_splitter.py` | Converts PDF pages and images to normalised page images |
| 2 — Preprocessor | `core/ocr/preprocessor.py` | Deskew, denoise, contrast enhancement |
| 3 — Layout Detector | `core/ocr/layout_detector.py` | Region segmentation |
| 4 — Handwriting Detector | `core/ocr/handwriting_detector.py` | Classifies handwritten vs printed regions for engine selection |
| 5 — Extractor | `core/ocr/extractor.py` | RapidOCR with engine fallback |
| 6 — Normalizer | `core/ocr/normalizer.py` | Medical spelling correction |
| 7 — Document Classifier | `core/ocr/document_classifier.py` | Document type classification (lab report, discharge summary, etc.) |
| 8 — Field Extractor | `core/ocr/field_extractor.py` | Structured field extraction with per-field confidence scores |
| 9 — Conflict Detector | `core/ocr/conflict_detector.py` | Flags value conflicts against active patient record |

"9 processing stages" refers to these 9 sequential files. Stages 2+3 and 6+7 are logically related pairs but are implemented as separate modules.
