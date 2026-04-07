# MedScribe Issue Tracker

Revised issue bodies aligned to the MedScribe Distributed Architecture plan (Go / Rust / Python).

## Issue-to-Phase Mapping

| Issue | Title | Phase | Steps | Status |
|-------|-------|-------|-------|--------|
| [#26](issue-026-go-api-gateway.md) | Go API Gateway | Phase 1 | Step 1 | Revised |
| [#27](issue-027-go-dag-engine.md) | Go DAG Engine | Phase 1 | Step 2 | Revised |
| [#28](issue-028-graphstate-domain-models.md) | GraphState + Domain Models | Phase 1 | Steps 3, 5 | **Rewritten** (had wrong body) |
| [#29](issue-029-pipeline-nodes.md) | Pipeline Nodes (18) | Phase 1 | Step 4 | Revised |
| [#30](issue-030-llm-dispatch.md) | LLM Dispatch System | Phase 1 | Step 6 | **New body** |
| [#31](issue-031-rust-audio-gateway.md) | Rust Audio Gateway | Phase 2 | Steps 8-9, 11 | Revised |
| [#32](issue-032-rust-kafka-consumers.md) | Rust Kafka Consumers | Phase 2 | Step 10 | **New body** |
| [#33](issue-033-whisper-worker.md) | Whisper Worker | Phase 3 | Steps 12-14 | Revised |
| [#34](issue-034-auth-security.md) | Auth + Security | Phase 4 | Steps 15-19 | **Revised** (expanded to cover S3, PHI encryption, audit logging) |
| [#35](issue-035-redis-occ.md) | Redis + OCC | Phase 6 | Steps 23-27 | Revised |
| [#36](issue-036-observability.md) | Observability | Phase 7 | Steps 28-30 | **Revised** (expanded with per-service metrics and dashboard specs) |
| [#37](issue-037-llm-routing.md) | LLM Routing | Phase 5 | Steps 20-22 | Revised |
| [#38](issue-038-eval-framework.md) | Eval Framework | Phase 8 | Steps 31-33 | **New body** |
| [#39](issue-039-rag-benchmark.md) | RAG Benchmark | Phase 9 | Steps 34-36 | **New body** |
| [#40](issue-040-kubernetes-deployment.md) | Kubernetes Deployment | Phase 10 | Steps 37-40 | **New body** |

## Phase Dependencies

```
Phase 1 (Go API + Orchestrator)  ---+
Phase 2 (Rust Audio + Kafka)    ----+---> Phase 10 (K8s)
Phase 3 (Python Whisper)        ----+       ^
                                    |       |
Phase 4 (Go Auth/Security)     ----+  (independent)
Phase 5 (LLM Routing)          ----+  (independent)
Phase 6 (Redis + OCC)          ----+  (independent)
Phase 7 (Observability)        ----+  (independent)
Phase 8 (Eval Framework)       ----+  (independent) ---> Phase 9
Phase 9 (RAG Benchmark)        ----+  (depends on Phase 8)
```

## Changes Summary

- **5 issues received new bodies** (previously empty): #30, #32, #38, #39, #40
- **1 issue was fully rewritten** (had incorrect copy of another issue): #28
- **9 issues were revised** with additional detail from the architecture plan: #26, #27, #29, #31, #33, #34, #35, #36, #37
- Issue #34 was significantly expanded to cover all of Phase 4 (JWT, RBAC, S3 storage, PHI encryption, audit logging) instead of just JWT + RBAC
- Issue #36 was expanded with per-service metric names, Grafana dashboard specifications, and cross-service trace propagation details
