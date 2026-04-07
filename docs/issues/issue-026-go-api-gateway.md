# Issue #26 -- Go API Gateway

**Title:** feat(api): scaffold Go API gateway with chi router and PostgreSQL integration

**Phase:** 1 (Go API Gateway + Orchestrator Core) -- Step 1

**Resume bullets served:** V2#1 (high-throughput pipeline), V1#1 (decoupling ingestion from serving)

---

## Overview

Replace the existing Python FastAPI backend with a Go-based API gateway to improve concurrency, performance, and maintainability. The Go gateway exposes the same REST endpoints as the current FastAPI app and connects to the existing PostgreSQL database using the same 7-table schema.

## Goals

- Maintain full API parity with the current FastAPI backend
- Improve throughput and latency via Go goroutine concurrency
- Establish the foundation for a service-oriented architecture
- Enable single-binary deployment for the API layer

## Scope

- Directory: `services/api/`
- Replaces:
  - `main.py` (FastAPI app)
  - `routes/*.py` (12 route files)
  - `models.py`, `session.py`, `repositories/` (data access layer)
  - `storage/` (file storage backend)
  - `monitoring.py` (telemetry)

## Tasks

### Project Setup
- [ ] Initialize Go module in `services/api/`
- [ ] Configure `chi` router with middleware stack (logging, CORS, recovery, request ID)
- [ ] Set up project directory structure:
  - [ ] `handlers/` -- HTTP request handlers
  - [ ] `store/` -- PostgreSQL data access via `pgx`
  - [ ] `llm/` -- LLM provider dispatch (see Issue #30)
  - [ ] `auth/` -- JWT and RBAC middleware (see Issue #34)
  - [ ] `storage/` -- S3/MinIO file backend
  - [ ] `telemetry/` -- Prometheus and OpenTelemetry instrumentation
  - [ ] `middleware/` -- shared middleware (audit, auth, logging)

### REST Endpoints
- [ ] Implement session endpoints:
  - [ ] `POST /api/session/start`
  - [ ] `POST /api/session/{id}/end`
  - [ ] `POST /api/session/{id}/transcribe`
  - [ ] `POST /api/session/{id}/pipeline`
  - [ ] `GET /api/session/{id}/pipeline/status`
  - [ ] `POST /api/session/{id}/upload`
- [ ] Implement patient endpoints:
  - [ ] `POST /api/patient/`
  - [ ] `GET /api/patient/{id}`
  - [ ] `PUT /api/patient/{id}`
  - [ ] `GET /api/patient/search`
- [ ] Implement auth endpoints:
  - [ ] `POST /api/auth/login`
  - [ ] `POST /api/auth/register`
  - [ ] `POST /api/auth/refresh`
- [ ] Implement LLM configuration endpoints:
  - [ ] `GET /api/llm/providers`
  - [ ] `PUT /api/llm/config`
- [ ] Implement clinical endpoints:
  - [ ] `GET /api/clinical/allergies/{patient_id}`
  - [ ] `GET /api/clinical/medications/{patient_id}`
- [ ] Add `GET /health` endpoint
- [ ] Add `GET /metrics` endpoint (Prometheus via `prometheus/client_golang`)

### Database Integration
- [ ] Set up `pgx` connection pool (`pgxpool.Pool`)
- [ ] Port the existing 7-table schema without modification (managed by Alembic migrations)
- [ ] Write repository layer (raw SQL or `sqlc`-generated Go types from existing schema):
  - [ ] `SessionRepository` -- session CRUD
  - [ ] `PatientRepository` -- patient CRUD
  - [ ] `RecordRepository` -- medical record CRUD
  - [ ] `UserRepository` -- user auth queries
  - [ ] `AuditRepository` -- audit log writes
- [ ] Validate pgvector extension compatibility for embedding queries

### Kafka Integration
- [ ] Wire `/api/session/{id}/pipeline` to publish to Kafka `pipeline.trigger` (async mode)
- [ ] Support direct gRPC call to orchestrator (sync mode) as alternative

## Acceptance Criteria

- All endpoints return correct responses matching the current FastAPI implementation
- Database reads and writes are functional against existing schema
- Health check and Prometheus metrics endpoints are operational
- Connection pooling handles concurrent requests without exhaustion
- Behavior matches existing FastAPI implementation on the same test fixtures

## Implementation Notes

- Prefer `pgx` over GORM: raw SQL or `sqlc` gives full control over pgvector queries. GORM cannot express `embedding <-> $1` operator syntax.
- Keep handlers thin; move business logic into service/repository layers
- Use middleware for logging, authentication, and request tracing
- Use `text/template` or `fmt.Sprintf` for any dynamic SQL (parameterized queries only)
- The 7-table schema (users, patients, sessions, medical_records, transcript_segments, documents, audit_logs) is unchanged

## Files to Create

```
services/api/
  main.go
  handlers/
    session.go
    patient.go
    clinical.go
    auth.go
    llm_config.go
    health.go
  store/
    pool.go
    session_repo.go
    patient_repo.go
    record_repo.go
    user_repo.go
    audit_repo.go
  middleware/
    logging.go
    cors.go
    recovery.go
  telemetry/
    prometheus.go
    otel.go
  Dockerfile
  go.mod
  go.sum
```

## Dependencies

- `github.com/go-chi/chi/v5` -- HTTP router
- `github.com/jackc/pgx/v5` -- PostgreSQL driver with connection pool
- `github.com/prometheus/client_golang` -- Prometheus metrics
- `go.opentelemetry.io/otel` -- OpenTelemetry SDK
