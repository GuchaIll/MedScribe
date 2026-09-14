# UC-02 - Three-Tier Persistence and HIPAA-Oriented Data Management

| Field | Value |
|---|---|
| Use Case ID | UC-02 |
| Name | Three-Tier Persistence and HIPAA-Oriented Data Management |
| Scope | Record persistence, checkpointing, object storage, auditability, encryption, retention |
| Primary Actors | Physician, Compliance Officer, System Administrator |
| Supporting Actors | MedScribe System, PostgreSQL/pgvector, SQLite, Amazon S3-compatible object storage |
| Trigger | The platform stores, retrieves, resumes, exports, or audits clinical session data |

## 1. Goal

Ensure MedScribe stores and manages clinical data through a layered persistence architecture that separates:

- long-term clinical records and embeddings,
- short-term workflow checkpoints,
- and binary artifact storage,

while supporting privacy, auditability, recovery, and HIPAA-oriented deployment expectations.

## 2. Summary

MedScribe is designed around a three-tier persistence model:

1. **PostgreSQL + pgvector** for durable patient records, embeddings, session metadata, and audit logs.
2. **SQLite** for short-lived or resumable LangGraph workflow checkpoints.
3. **Amazon S3 or equivalent object storage** for uploaded source files and generated documents.

The use case describes how these layers cooperate to support clinical operations while preserving governance boundaries and deployment-ready security controls.

Current repository status:

- PostgreSQL/pgvector is the main long-term persistence design.
- SQLite checkpointing is directly documented in the LangGraph flow.
- Storage abstraction exists, with local storage implemented and S3 explicitly anticipated by configuration and dependencies.
- HIPAA-oriented controls are present in the architecture through auditability, provenance, and PHI-aware storage design, while full compliance depends on deployment configuration.

## 3. Preconditions

1. Database schema and migrations are applied.
2. The application has valid database and storage configuration.
3. Access to patient data is gated through authenticated application flows.
4. Environment-specific secrets and encryption materials are configured outside source control.
5. Backup and retention policies are defined for the target deployment.

## 4. Postconditions

### Success

1. Long-term clinical data is persisted in the durable record store.
2. In-flight workflow state is checkpointed for resumability.
3. Binary artifacts are stored in the configured object layer.
4. Audit trails exist for clinically relevant system actions.
5. Sensitive data is protected according to deployment security controls.

### Failure

1. The system retains enough state to diagnose persistence failures.
2. Failed writes do not silently produce incomplete finalized records.
3. Recovery procedures can restore durable data or resume interrupted sessions where supported.

## 5. Actors

### Physician

- Creates and reviews clinical records.
- Expects prior records to be retrievable and current outputs to persist reliably.

### Compliance Officer

- Reviews whether storage, access history, and traceability align with privacy and audit expectations.

### System Administrator

- Configures database endpoints, storage backends, backup jobs, encryption, and retention controls.

### MedScribe System

- Writes and reads across the persistence tiers.
- Preserves workflow checkpoints.
- Maintains audit evidence and provenance metadata.

## 6. Persistence Layers

### 6.1 Tier 1 - Long-Term Clinical Record Store

**Technology:** PostgreSQL with pgvector

**Purpose:**

- patient master data,
- clinical session metadata,
- finalized structured records,
- SOAP notes and validation artifacts,
- semantic embeddings for retrieval,
- audit logs.

**Representative stored entities:**

- patients,
- users,
- sessions,
- medical_records,
- audit_logs,
- chunk_embeddings,
- clinical_embeddings,
- workflow-related metadata.

**Why this layer exists:**

- It keeps structured PHI and retrieval data within one governed database boundary.
- It supports both transactional record handling and semantic search.
- It avoids introducing a separate vector store for the current scale and governance model.

### 6.2 Tier 2 - Short-Term Workflow Checkpoint Store

**Technology:** SQLite via LangGraph `SqliteSaver`

**Purpose:**

- preserve in-progress workflow state,
- support interruption and resume semantics,
- retain graph progress after each node.

**Stored content:**

- `GraphState` snapshots keyed by thread or session identifier,
- node-level progression context,
- resumption data required to continue processing from the last checkpoint.

**Why this layer exists:**

- It isolates transient orchestration state from the durable patient record layer.
- It lets the workflow recover without prematurely writing partially validated clinical outputs into long-term storage.

### 6.3 Tier 3 - Object Storage Layer

**Technology:** Amazon S3 or S3-compatible object storage

**Purpose:**

- uploaded PDFs and images,
- intermediate or derived artifacts,
- generated exports such as PDFs,
- large binary assets not suited for relational storage.

**Current repository status:**

- Storage abstraction is present.
- Local storage is implemented.
- S3 is an intended backend in the design and dependency stack.

**Why this layer exists:**

- It separates large objects from transactional record storage.
- It improves durability and lifecycle management for file-based artifacts.
- It supports future encrypted archival and controlled export workflows.

## 7. Main Success Scenario

### 7.1 Session and Patient Context

1. A physician starts or updates a patient session.
2. The system reads patient data and prior records from PostgreSQL.
3. Relevant embeddings are available for retrieval and grounding.

### 7.2 Upload and Object Persistence

4. The user uploads a clinical document.
5. The system stores the source file in the object layer or configured local equivalent.
6. Metadata linking the artifact to the clinical session is retained by the application.

### 7.3 Workflow Checkpointing

7. The LangGraph workflow starts.
8. After each major node, the current workflow state is checkpointed to SQLite.
9. If processing continues successfully, checkpoints serve as recovery points but do not replace final persistence.

### 7.4 Final Record Persistence

10. After validation and output packaging, the finalized structured record is written to PostgreSQL.
11. Associated SOAP note and validation details are stored with the record.
12. Session and evidence metadata are updated.
13. Embeddings derived from chunks and clinically useful facts are written to pgvector-backed tables.

### 7.5 Audit Completion

14. The workflow trace and audit-relevant details are persisted.
15. The system can later answer who accessed or changed what, when, and in what context.

## 8. Retrieval Scenario

1. A physician opens a patient record.
2. The system retrieves structured patient and visit history from PostgreSQL.
3. Semantic retrieval uses pgvector embeddings to find prior relevant facts or chunks.
4. If supporting documents are needed, the object layer provides the associated files.

## 9. Resume and Recovery Scenario

1. A workflow is interrupted or fails mid-execution.
2. SQLite retains the last checkpointed workflow state.
3. The application resumes from the checkpoint where the runtime supports interrupt or resume behavior.
4. Only validated and packaged outputs are written to the durable PostgreSQL layer as finalized records.

## 10. Security and HIPAA-Oriented Controls

This use case is designed to support HIPAA-oriented deployment, not to claim compliance by code alone.

### 10.1 Required Protections

1. **Encryption in transit** must protect all application, database, and storage traffic.
2. **Encryption at rest** must protect PostgreSQL storage volumes, SQLite checkpoint media where applicable, and S3 buckets or equivalents.
3. **Access control** must restrict PHI access to authorized roles only.
4. **Audit logging** must capture clinically relevant reads, writes, updates, exports, and failures.
5. **Key management** must keep encryption material outside source control and outside application code.

### 10.2 Data Governance Intent by Tier

#### PostgreSQL/pgvector

- Holds durable PHI and derived structured data.
- Requires strong access control, backup, and encryption controls.
- Supports audit history and provenance querying.

#### SQLite

- Holds transient but sensitive workflow state.
- Requires host-level protections because workflow snapshots may contain PHI during processing.
- Should be treated as sensitive operational data even if retention is shorter.

#### S3/Object Storage

- Holds raw uploaded and generated binary artifacts that may include PHI.
- Requires bucket encryption, strict IAM, lifecycle rules, and controlled access URLs.

## 11. Alternative and Exception Flows

### A1. Database Write Failure

1. Final record persistence to PostgreSQL fails.
2. The system does not mark the record as successfully finalized.
3. Logs and checkpoint information are retained for investigation or retry.

### A2. Checkpoint Store Failure

1. SQLite is not writable during workflow execution.
2. The workflow may continue if allowed, but resumability is degraded.
3. The failure is logged because recoverability guarantees are reduced.

### A3. Object Storage Unavailable

1. S3 or equivalent storage is unreachable.
2. The system may fall back to local storage where configured.
3. Artifact ingestion or export is flagged if no safe storage path exists.

### A4. Audit Logging Failure

1. An action completes but audit persistence partially fails.
2. The event is surfaced as an operational issue because compliance evidence is incomplete.
3. The deployment must treat repeated audit failure as a high-severity incident.

### A5. Encryption Misconfiguration

1. Required encryption or secret configuration is missing.
2. The deployment should fail safe rather than operate in a non-compliant mode for PHI-bearing environments.

## 12. Business Rules

1. Finalized clinical records belong in the durable PostgreSQL layer, not only in workflow checkpoints.
2. Workflow checkpoints must not be treated as the system of record.
3. Large binary artifacts should be stored in the object layer instead of bloating relational tables.
4. Audit evidence must remain queryable by user, resource, action, and time.
5. Sensitive patient data must be encrypted using deployment-managed controls.
6. Provenance and confidence metadata must remain linked to persisted outputs when available.

## 13. Non-Functional Requirements

### Durability

- Durable records must survive service restarts and host replacement through database and storage backups.

### Recoverability

- In-flight workflows should be resumable from the last checkpoint where checkpointing is enabled and healthy.

### Performance

- Retrieval of patient records and evidence should remain fast enough for point-of-care workflows.

### Auditability

- Storage actions must leave sufficient evidence for internal review and regulatory response.

### Separation of Concerns

- Long-term records, transient workflow state, and binary artifacts must remain logically separated.

## 14. Data Classification by Layer

| Layer | Data Class | Examples |
|---|---|---|
| PostgreSQL/pgvector | Durable PHI and derived clinical data | patient record, session metadata, SOAP note, embeddings, audit logs |
| SQLite checkpoints | Transient sensitive workflow state | graph state, in-progress extracted facts, pending validation context |
| S3/object storage | Binary PHI artifacts and exports | uploaded scans, PDFs, generated note exports |

## 15. Assumptions

1. Clinics need a single governed data architecture rather than several loosely coupled stores with unclear ownership.
2. Semantic retrieval over patient history is valuable enough to justify storing embeddings beside structured records.
3. Workflow interruptions are operationally normal and should not force complete restart.
4. Object storage is the appropriate target for source documents and generated files in production deployments.

## 16. Acceptance Criteria

This use case is satisfied when MedScribe can:

1. persist finalized clinical records and embeddings in PostgreSQL/pgvector,
2. preserve in-progress workflow checkpoints in SQLite,
3. store or abstract large clinical artifacts through an object storage layer,
4. maintain audit-friendly traceability for sensitive actions,
5. and operate under deployment controls that provide encryption, access restriction, backup, and recovery for PHI-bearing data.
