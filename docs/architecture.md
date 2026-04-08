# MedScribe — System Architecture

## Component Diagram

```mermaid
flowchart TB
    subgraph FE["Browser Client (React 18 + TypeScript)"]
        VAD["Silero VAD\n@ricky0123/vad-react\nONNX speech onset ~50-100ms"]
        UI["MedicalTranscription\nSession lifecycle + pipeline trigger"]
        UPL["Document Upload\nMultipart PDF / image"]
    end

    subgraph GW["Go API Gateway -- port 8080"]
        AUTH["JWT Auth\ngolang-jwt/v5"]
        CACHE["Session Cache\nsync.Map TTL (1h)"]
        KPROD["Kafka Producer\nacks=1, async, linger=10ms"]
        ROUT["chi v5 Router\nproxy to Python backend"]
    end

    subgraph KAFKA["Apache Kafka 4.2 (KRaft)"]
        KT["pipeline.trigger"]
    end

    subgraph API["Python Backend -- port 3001"]
        SESS["Session Router\n/api/session/*"]
        PIPE["Pipeline Consumer\nWorkflowEngine invoke"]
        CLIN["Clinical Router\n/api/clinical/*"]
        REC["Records Router\n/api/records/*"]
    end

    subgraph OCR["OCR Pipeline -- server/app/core/ocr/"]
        direction LR
        S1["1 page_splitter"] --> S2["2 preprocessor"] --> S3["3 layout_detector"] --> S4["4 handwriting_detector"]
        S4 --> S5["5 extractor\nRapidOCR + fallback"] --> S6["6 normalizer"] --> S7["7 document_classifier"] --> S8["8 field_extractor"] --> S9["9 conflict_detector"]
    end

    subgraph LG["LangGraph Pipeline -- 15 nodes (server/app/agents/)"]
        direction TB
        N1["load_patient_context"] --> N2["ingest"] --> N3["clean_transcription"]
        N3 --> N4["normalize_transcript"] --> N5["segment_and_chunk"] --> N6["extract_candidates"]
        N6 --> N7["diagnostic_reasoning"] --> N8["retrieve_evidence"] --> N9["fill_structured_record"]
        N9 --> N10["clinical_suggestions"] --> N11["validate_and_score"]

        N11 -->|"schema errors, attempts < 3"| N12["repair"]
        N12 -->|"retry"| N11

        N11 -->|"conflicts"| N13["conflict_resolution"]
        N13 -->|"unresolved"| N14["human_review_gate"]
        N13 -->|"resolved"| N15["generate_note"]

        N11 -->|"needs_review"| N14
        N11 -->|"valid"| N15

        N14 --> N16["package_outputs"]
        N15 --> N16
        N16 --> N17["persist_results"]
    end

    subgraph DATA["Data Layer"]
        PG[("PostgreSQL 15 + pgvector\nRecords, embeddings, sessions, auth")]
        RD[("Redis Stack\nPipeline status, session cache")]
        GROQ["Groq API\nllama-4-scout-17b-16e-instruct\nLLM inference"]
        EL["ElevenLabs TTS\nbrowser SpeechSynthesis fallback"]
    end

    VAD -->|"utterances"| UI
    UI -->|"POST start, transcribe"| AUTH
    UI -->|"POST pipeline"| AUTH
    UI -->|"GET pipeline/status"| AUTH
    UPL -->|"POST upload"| AUTH

    AUTH --> CACHE
    CACHE -->|"session validated"| ROUT
    ROUT -->|"pipeline trigger"| KPROD
    KPROD -->|"produce"| KT
    KT -->|"consume"| PIPE
    ROUT -->|"proxy"| SESS

    SESS -->|"dispatch file"| OCR
    S9 -->|"DocumentProcessingResult"| SESS

    PIPE --> LG

    N1 -->|"patient history lookup"| PG
    N8 -->|"ANN embedding query"| PG
    N7 -->|"LLM reasoning"| GROQ
    N12 -->|"LLM schema repair"| GROQ
    N15 -->|"LLM SOAP note"| GROQ
    S8 -->|"LLM field disambiguation"| GROQ
    N17 -->|"write record + embeddings"| PG
    KPROD -->|"seed status"| RD
    PIPE -->|"update status"| RD
    AUTH -->|"read status"| RD

    CLIN -->|"allergy / medication lookup"| PG
    REC -->|"fetch record for template"| PG
    REC -->|"TTS synthesis"| EL
    CACHE -->|"cache miss"| PG
```

---

## Persistence Model

Three persistence mechanisms serve distinct purposes:

| Store | Technology | What it holds | When written |
|-------|-----------|---------------|--------------|
| **Session / Auth** | PostgreSQL 15 (pgxpool via Go gateway) | Users, sessions, auth tokens | On register, login, session start/end |
| **Patient records** | PostgreSQL 15 + pgvector (SQLAlchemy via Python) | `StructuredRecord`, embeddings, audit trace | Only in `persist_results` (final node) |
| **Pipeline status** | Redis Stack | Per-node progress, pipeline state | Seeded by Go gateway on trigger, updated by Python after each node |
| **Session cache** | In-process sync.Map (Go gateway) | Session ID -> session object, 1h TTL | On first session lookup (cache miss fills from PG) |

**Pipeline trigger flow:**
1. Client sends `POST /api/session/{id}/pipeline` to Go gateway (port 8080)
2. Gateway validates JWT, checks session cache (sync.Map), falls back to PG on cache miss
3. Gateway seeds pipeline status in Redis (async goroutine) and produces a Kafka message to `pipeline.trigger` (acks=1, async delivery, micro-batched)
4. Gateway returns `202 Accepted` immediately
5. Python backend consumes from Kafka, invokes `WorkflowEngine.run()` which executes the 15-node LangGraph pipeline
6. Each node completion updates Redis pipeline status
7. Frontend polls `GET /api/session/{id}/pipeline/status` (served by Go gateway reading from Redis)

**Interrupt/resume flow:**
1. When `interrupt_before=["human_review_gate"]` is active, the graph pauses before executing that node
2. The partial state lives in the Python process; the pipeline status in Redis reflects the paused state
3. To resume: the gateway publishes a resume trigger to Kafka
4. **Current status:** `enable_interrupts=False` -- the infrastructure is in place but the gate runs non-interactively

---

## LangGraph Node Reference

All 15 nodes in execution order:

| # | Node | File | Description |
|---|------|------|-------------|
| 1 | `load_patient_context` | `nodes/load_patient_context.py` | Loads prior patient facts from PostgreSQL into `patient_record_fields` |
| 2 | `ingest` | `nodes/ingest.py` | Loads transcript segments + OCR artifacts into `GraphState.chunks` |
| 3 | `clean_transcription` | `nodes/clean.py` | Removes disfluencies, expands abbreviations |
| 4 | `normalize_transcript` | `nodes/normalize.py` | Standardises medical terminology |
| 5 | `segment_and_chunk` | `nodes/segment.py` | Splits transcript into topical clinical chunks |
| 6 | `extract_candidates` | `nodes/extract.py` | NLP entity recognition -> `candidate_facts` list |
| 7 | `diagnostic_reasoning` | `nodes/diagnostic_reasoning.py` | LLM differential diagnosis over extracted candidates |
| 8 | `retrieve_evidence` | `nodes/evidence.py` | pgvector ANN search -> `evidence_map` (fact_id -> source chunks) |
| 9 | `fill_structured_record` | `nodes/fill_record.py` | Maps candidates to typed `StructuredRecord` schema |
| 10 | `clinical_suggestions` | `nodes/clinical_suggestions.py` | Allergy + drug interaction lookup; LLM for disambiguation |
| 11 | `validate_and_score` | `nodes/validate.py` | Pydantic + contract validation; cross-visit contradiction detection; sets `validation_report.needs_review` |
| -- | `repair` | `nodes/repair.py` | LLM schema repair (loops back to validate, max 3 iterations) |
| -- | `conflict_resolution` | `nodes/conflicts.py` | Resolves discrepancies against stored patient history |
| -- | `human_review_gate` | `nodes/review_gate.py` | Interrupt point for physician approval |
| 12+ | `generate_note` | `nodes/generate_note.py` | LLM SOAP note generation |
| 13+ | `package_outputs` | `nodes/package.py` | Assembles final response payload |
| 14+ | `persist_results` | `nodes/persist_results.py` | Writes record, embeddings, audit trace to PostgreSQL |

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
