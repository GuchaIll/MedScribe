**Checklist**

### P0: Fix public claims vs actual implementation
- [ ] Replace any claim that says transcription is powered by `Whisper + pyannote` unless that path is actually running in production.
- [ ] Replace any claim that ties `23.5s` latency to Whisper/diarization.
- [ ] Rewrite README/project bullets so they describe the current browser-side `Silero VAD + Web Speech API` flow.
- [ ] Move unimplemented items like server-side Whisper, diarization, and Kubernetes to a clearly labeled roadmap section.

Targets:
[README.md](/Users/guchaill/Coding/MedScribe/README.md:89)
[docs/design-decisions.md](/Users/guchaill/Coding/MedScribe/docs/design-decisions.md:27)
[client/medscribe/src/hooks/useVoiceCapture.js](/Users/guchaill/Coding/MedScribe/client/medscribe/src/hooks/useVoiceCapture.js:4)
[server/app/models/sst.py](/Users/guchaill/Coding/MedScribe/server/app/models/sst.py:23)

### P0: Make pipeline topology consistent everywhere
- [ ] Pick one canonical pipeline node count from the actual graph implementation.
- [ ] Update README, API docs, architecture docs, and internal route comments to use the same count.
- [ ] Remove nonexistent node names from the progress store or add the missing nodes to the real graph.
- [ ] Ensure frontend progress labels are generated from the same source as the graph definition.

Targets:
[server/app/agents/graph.py](/Users/guchaill/Coding/MedScribe/server/app/agents/graph.py:103)
[server/app/core/pipeline_progress.py](/Users/guchaill/Coding/MedScribe/server/app/core/pipeline_progress.py:33)
[README.md](/Users/guchaill/Coding/MedScribe/README.md:92)
[docs/api/session.md](/Users/guchaill/Coding/MedScribe/docs/api/session.md:224)
[server/app/api/routes/internal_pipeline.py](/Users/guchaill/Coding/MedScribe/server/app/api/routes/internal_pipeline.py:11)

### P0: Remove or prove unsupported performance numbers
- [ ] Audit every public number: `23.5s`, `20 QPS`, `85% accuracy`, `500 QPS`, `<1ms p50`.
- [ ] For each number, either add reproducible benchmark evidence or remove it from public-facing docs.
- [ ] Create a `docs/benchmarks/` folder with benchmark method, date, environment, and raw outputs.
- [ ] Make resume bullets use only numbers that are traceable to repo artifacts.

Targets:
[README.md](/Users/guchaill/Coding/MedScribe/README.md:27)
[docs/design-decisions.md](/Users/guchaill/Coding/MedScribe/docs/design-decisions.md:29)
[scripts/qps_bench.js](/Users/guchaill/Coding/MedScribe/scripts/qps_bench.js:1)
[scripts/bench-qps.sh](/Users/guchaill/Coding/MedScribe/scripts/bench-qps.sh:1)

### P1: Clarify the actual Go/Kafka service boundary
- [x] Decide: **split-image, one binary** — keep a single Go image but run it in
      modes so the gateway and consumers deploy as separate workloads. (chosen 2026-06-04)
- [x] Extract consumers into independently deployable units: `--mode` dispatch in
      [app.go](/Users/guchaill/Coding/MedScribe/services/api/internal/app/app.go)
      (`gateway`, `pipeline-worker`, `ocr-worker`, `audio-worker`, `all`) + flag in
      `cmd/app/main.go`. Gateway no longer runs consumers in-process (except `all`).
      Builds clean (`go build ./...`). Workers expose `/health`,`/healthz`,`/readyz`,`/metrics`.
- [x] Real K8s manifests written under [infra/k8s/](/Users/guchaill/Coding/MedScribe/infra/k8s/):
      gateway Deployment/Service/Ingress/HPA + pipeline/ocr/audio worker Deployments
      with KEDA lag-based ScaledObjects + base namespace/config/secret + README.
      (Replaces the previously empty 0-byte scaffold files.)
- [x] Diagrams/docs updated to match: README architecture mermaid now shows the
      Go consumer-proxy hop between Kafka and Python; README/design-decisions/revision_plan
      describe the one-image/multi-mode topology.

Note: `docker compose` still runs `--mode=all` (single process) for dev; production splits via the manifests. Compose was intentionally left unsplit.

Targets:
[services/api/internal/app/app.go](/Users/guchaill/Coding/MedScribe/services/api/internal/app/app.go:75)
[services/api/internal/usecase/pipelineproxy/handler.go](/Users/guchaill/Coding/MedScribe/services/api/internal/usecase/pipelineproxy/handler.go:1)
[services/api/internal/usecase/ocrproxy/handler.go](/Users/guchaill/Coding/MedScribe/services/api/internal/usecase/ocrproxy/handler.go:1)
[infra/k8s/](/Users/guchaill/Coding/MedScribe/infra/k8s/)
[docs/revision_plan.md](/Users/guchaill/Coding/MedScribe/docs/revision_plan.md:21)

### P1: Finish the physician review and persistence flow
- [x] Decide model: review is a real gate, but discrepancies are **queued** for
      end-of-session sign-off, not blocking mid-pipeline. (chosen 2026-06-04)
- [x] Make the gate real (Python side): `persist_results` stages flagged runs in
      the Redis review queue (`core/review_queue.py`) instead of mutating the
      patient record. No mid-pipeline interrupt; the encounter keeps flowing.
- [~] Add the missing review-persist worker path — **Python staging done**; Go
      review API (`GET/POST /session/{id}/review[/signoff]`) + commit-on-sign-off
      worker still pending (follow-up).
- [x] Verify approved OCR/pipeline changes persist only after explicit review —
      covered by `server/tests/unit/test_review_queue.py` (gate stages and does
      NOT call the record repo when review is needed). End-to-end sign-off persist
      lands with the Go worker.

Targets:
[server/app/agents/nodes/review_gate.py](/Users/guchaill/Coding/MedScribe/server/app/agents/nodes/review_gate.py:93)
[server/app/agents/nodes/persist_results.py](/Users/guchaill/Coding/MedScribe/server/app/agents/nodes/persist_results.py)
[server/app/core/review_queue.py](/Users/guchaill/Coding/MedScribe/server/app/core/review_queue.py)
[server/app/agents/graph.py](/Users/guchaill/Coding/MedScribe/server/app/agents/graph.py:148)
[docs/revision_plan.md](/Users/guchaill/Coding/MedScribe/docs/revision_plan.md:111)

### P1: Align the demo story with the documented architecture
- [ ] Pick one canonical “main app path” for demos.
- [ ] If the public demo should hit Python directly, say that clearly in README too.
- [ ] If the Go gateway is the official entry point, finish wiring the frontend and deployment around it.
- [ ] Remove conflicting statements about which backend the UI talks to.

Targets:
[docs/demo_deployment.md](/Users/guchaill/Coding/MedScribe/docs/demo_deployment.md:28)
[README.md](/Users/guchaill/Coding/MedScribe/README.md:237)
[docker-compose.yml](/Users/guchaill/Coding/MedScribe/docker-compose.yml:143)

### P2: Clean up Kubernetes messaging
- [ ] Remove “deployed on Kubernetes” style claims unless working manifests exist.
- [ ] Either add real manifests and instructions or keep K8s in roadmap-only language.
- [ ] Fill or remove empty files under `infra/k8s/services/*`.

Targets:
[infra/k8s/services/api/deployment.yaml](/Users/guchaill/Coding/MedScribe/infra/k8s/services/api/deployment.yaml:1)
[infra/k8s/services/ingest/deployment.yaml](/Users/guchaill/Coding/MedScribe/infra/k8s/services/ingest/deployment.yaml:1)
[infra/k8s/services/orchestrator/deployment.yaml](/Users/guchaill/Coding/MedScribe/infra/k8s/services/orchestrator/deployment.yaml:1)
[README.md](/Users/guchaill/Coding/MedScribe/README.md:271)

### P2: Standardize OCR pipeline wording
- [ ] Pick one stage count for OCR and use it everywhere.
- [ ] Ensure docs match the actual preprocessing, extraction, normalization, conflict, and packaging steps.
- [ ] Keep the “confidence scoring + conflict detection + review” description, since that part is mostly supported.

Targets:
[README.md](/Users/guchaill/Coding/MedScribe/README.md:95)
[server/app/core/ocr/pipeline.py](/Users/guchaill/Coding/MedScribe/server/app/core/ocr/pipeline.py:4)

### P2: Add evidence for retrieval quality
- [ ] Add an eval harness or benchmark artifact for source-grounded retrieval quality.
- [ ] Document dataset, metric definition, and pass/fail threshold.
- [ ] Remove the `85%` claim until measured and committed.

Targets:
[server/app/services/embedding_service.py](/Users/guchaill/Coding/MedScribe/server/app/services/embedding_service.py:183)
[server/app/agents/nodes/evidence.py](/Users/guchaill/Coding/MedScribe/server/app/agents/nodes/evidence.py:206)
[server/tests/unit/test_retrieve_evidence.py](/Users/guchaill/Coding/MedScribe/server/tests/unit/test_retrieve_evidence.py:1)
[server/tests/unit/test_rag_enhancements.py](/Users/guchaill/Coding/MedScribe/server/tests/unit/test_rag_enhancements.py:1)

If you want, I can convert this into a tighter execution board with `Priority | Task | Why it matters | Effort | Proof of done`.