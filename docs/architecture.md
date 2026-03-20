# MedScribe — System Architecture

## Component Diagram

```mermaid
flowchart TB
    subgraph FE["Browser Client (React 18 + TypeScript)"]
        VAD["Silero VAD\n@ricky0123/vad-react\nONNX speech onset ~50-100ms"]
        UI["MedicalTranscription\nSession lifecycle + pipeline trigger"]
        UPL["Document Upload\nMultipart PDF / image"]
    end

    subgraph API["FastAPI Backend — port 3001"]
        SESS["Session Router\n/api/session/*"]
        PIPE["POST /api/session/{id}/pipeline\nWorkflowEngine invoke"]
        CLIN["Clinical Router\n/api/clinical/*"]
        REC["Records Router\n/api/records/*"]
    end

    subgraph OCR["OCR Pipeline — server/app/core/ocr/"]
        direction LR
        S1["1 page_splitter"] --> S2["2 preprocessor"] --> S3["3 layout_detector"] --> S4["4 handwriting_detector"]
        S4 --> S5["5 extractor\nRapidOCR + fallback"] --> S6["6 normalizer"] --> S7["7 document_classifier"] --> S8["8 field_extractor"] --> S9["9 conflict_detector"]
    end

    subgraph LG["LangGraph Pipeline — 18 nodes (server/app/agents/)"]
        direction TB
        N1["greeting"] --> N2["load_patient_context"] --> N3["ingest"] --> N4["clean_transcription"]
        N4 --> N5["normalize_transcript"] --> N6["segment_and_chunk"] --> N7["extract_candidates"]
        N7 --> N8["diagnostic_reasoning"] --> N9["retrieve_evidence"] --> N10["fill_structured_record"]
        N10 --> N11["clinical_suggestions"] --> N12["validate_and_score"]

        N12 -->|"schema errors, attempts < 3"| N13["repair"]
        N13 -->|"retry"| N12

        N12 -->|"conflicts"| N14["conflict_resolution"]
        N14 -->|"unresolved"| N15["human_review_gate"]
        N14 -->|"resolved"| N16["generate_note"]

        N12 -->|"needs_review"| N15
        N12 -->|"valid"| N16

        N15 --> N17["package_outputs"]
        N16 --> N17
        N17 --> N18["persist_results"]
    end

    subgraph DATA["Data Layer"]
        PG[("PostgreSQL + pgvector\nRecords, embeddings, audit logs")]
        SQ[("SQLite\nLangGraph checkpoints\nper-node state snapshots")]
        GROQ["Groq API\nllama-3.3-70b-versatile\nLLM inference"]
        EL["ElevenLabs TTS\nbrowser SpeechSynthesis fallback"]
    end

    VAD -->|"utterances"| UI
    UI -->|"POST start, transcribe"| SESS
    UI -->|"POST pipeline"| PIPE
    UI -->|"GET pipeline/status"| SESS
    UPL -->|"POST upload"| SESS

    SESS -->|"dispatch file"| OCR
    S9 -->|"DocumentProcessingResult"| SESS

    PIPE --> LG

    N2 -->|"patient history lookup"| PG
    N9 -->|"ANN embedding query"| PG
    N8 -->|"LLM reasoning"| GROQ
    N13 -->|"LLM schema repair"| GROQ
    N16 -->|"LLM SOAP note"| GROQ
    S8 -->|"LLM field disambiguation"| GROQ
    N18 -->|"write record + embeddings"| PG
    N18 -->|"checkpoint commit"| SQ

    CLIN -->|"allergy / medication lookup"| PG
    REC -->|"fetch record for template"| PG
    REC -->|"TTS synthesis"| EL
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
