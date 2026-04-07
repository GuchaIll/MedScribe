# Issue #40 -- Kubernetes Deployment with Autoscaling

**Title:** feat(devops): deploy full system on Kubernetes with autoscaling

**Phase:** 10 (Kubernetes Deployment) -- Steps 37-40

**Resume bullets served:** V2#2 (Kubernetes, custom HPA)

**Depends on:** Phases 1-3 (core service topology must be built first)

---

## Overview

Deploy the full MedScribe distributed system on Kubernetes with autoscaling, Helm packaging, and CI/CD. This phase integrates all services from Phases 1-9 into a production-ready deployment.

## Goals

- Deploy all services with appropriate replica counts and resource limits
- Enable GPU-aware autoscaling for Whisper workers via KEDA
- Package deployment as a Helm chart for reproducible installs
- Automate build and deploy via GitHub Actions CI/CD

## Scope

- Directory: `k8s/`, `charts/medscribe/`
- GitHub Actions: `.github/workflows/`
- Covers all services in the target architecture

## Tasks

### Kubernetes Manifests (Step 37)
- [ ] Create `k8s/` directory with manifests for all services:

#### Go API Gateway
- [ ] Deployment: 2+ replicas
- [ ] Service: ClusterIP on port 3001
- [ ] Ingress: HTTP routing for `/api/*` paths
- [ ] Resource limits: CPU and memory requests/limits
- [ ] Environment variables from ConfigMap and Secrets
- [ ] Readiness/liveness probes: `/health` endpoint

#### Go Orchestrator
- [ ] Deployment: 2+ replicas
- [ ] Service: ClusterIP on gRPC port (50051)
- [ ] Resource limits appropriate for LLM HTTP calls (higher memory)
- [ ] Environment variables: PostgreSQL, Redis, LLM API keys from Secrets
- [ ] Readiness probe: gRPC health check

#### Rust Audio Gateway
- [ ] Deployment: 3+ replicas (high-throughput audio path)
- [ ] Service: LoadBalancer or Ingress for WebSocket connections
- [ ] Resource limits: CPU-optimized for VAD inference
- [ ] Anti-affinity: spread across nodes for availability
- [ ] Readiness/liveness probes: HTTP health endpoint

#### Rust Kafka Consumers
- [ ] Deployment: 3+ replicas
- [ ] No Service needed (consumers only, no inbound traffic)
- [ ] Resource limits: CPU-optimized for message routing
- [ ] Environment variables: Kafka bootstrap servers, gRPC endpoints

#### Python Whisper Worker
- [ ] Deployment: 1-10 replicas (autoscaled)
- [ ] nodeSelector: `nvidia.com/gpu` for GPU scheduling
- [ ] Resource requests: `nvidia.com/gpu: 1`
- [ ] Tolerations for GPU node taints
- [ ] Environment variables: model config, Kafka config

#### Infrastructure Services
- [ ] Kafka: Strimzi operator CRD or Bitnami Helm chart
  - [ ] 3 broker replicas
  - [ ] Topic auto-creation or pre-created topics (audio.raw, audio.voiced, transcript.segments, pipeline.trigger, pipeline.results)
  - [ ] Persistent storage for message retention
- [ ] PostgreSQL: CloudNativePG operator or managed (RDS for production)
  - [ ] pgvector extension enabled
  - [ ] Persistent volume for data
  - [ ] Connection pooling (PgBouncer sidecar)
- [ ] Redis: Bitnami Helm chart
  - [ ] Sentinel mode for HA (production)
  - [ ] Persistent volume for data durability
- [ ] MinIO: S3-compatible storage for development
  - [ ] Persistent volume for objects
  - [ ] Pre-created bucket

#### Shared Resources
- [ ] ConfigMap: shared configuration (Kafka brokers, service endpoints)
- [ ] Secrets: API keys, database credentials, JWT secret, encryption key
- [ ] NetworkPolicy: restrict inter-service communication to required paths
- [ ] PodDisruptionBudget: ensure minimum replicas during updates

### KEDA Autoscaling for Whisper Workers (Step 38)
- [ ] Install KEDA operator (Helm chart or manifest)
- [ ] Create ScaledObject for Whisper worker deployment:
  - [ ] Trigger: Kafka consumer lag on `audio.voiced` topic
  - [ ] Min replicas: 1
  - [ ] Max replicas: 10
  - [ ] Lag threshold: configurable (e.g., scale up when lag > 100 messages)
  - [ ] Cooldown period: 300 seconds (prevent rapid scale-down)
  - [ ] Polling interval: 30 seconds
- [ ] Validate autoscaler responds to increased audio load

### Helm Chart (Step 39)
- [ ] Create `charts/medscribe/` Helm chart:
  - [ ] `Chart.yaml` with version and dependencies
  - [ ] `values.yaml` with configurable overrides:
    - Replica counts per service
    - Resource limits
    - Image tags and registry
    - PostgreSQL connection string
    - Redis connection string
    - Kafka bootstrap servers
    - LLM API keys (reference to external Secret)
    - Feature flags (enable/disable whisper GPU, KEDA, etc.)
  - [ ] Templates for all Kubernetes resources
  - [ ] Subchart dependencies: Kafka (Bitnami), Redis (Bitnami), PostgreSQL (optional)
  - [ ] `NOTES.txt` with post-install instructions
- [ ] Support overrides for different environments:
  - [ ] `values-dev.yaml` -- local development (MinIO, single replica, no GPU)
  - [ ] `values-staging.yaml` -- staging environment
  - [ ] `values-prod.yaml` -- production (managed DB, multi-replica, GPU nodes)

### CI/CD Pipeline (Step 40)
- [ ] GitHub Actions workflow `.github/workflows/deploy.yml`:
  - [ ] Build stage:
    - [ ] Build Go services (api-gateway, orchestrator) -- multi-stage Docker build
    - [ ] Build Rust services (audio-gateway, kafka-consumers) -- multi-stage Docker build
    - [ ] Build Python service (whisper-worker) -- GPU Docker image
    - [ ] Build React client -- static asset Docker image
  - [ ] Push images to container registry (GitHub Container Registry or configurable)
  - [ ] Tag images with git SHA and branch name
  - [ ] Deploy stage:
    - [ ] `helm upgrade --install` with appropriate values file
    - [ ] Environment-specific deployment (dev/staging/prod)
    - [ ] Rollback on health check failure
  - [ ] Integration test stage (optional):
    - [ ] Run eval harness against deployed environment
    - [ ] Verify end-to-end pipeline execution

## Acceptance Criteria

- `helm install medscribe charts/medscribe/` deploys the full stack
- `kubectl get pods` shows all services running and healthy
- `kubectl get hpa` shows Whisper worker autoscaler active and responding to load
- Ingress routes HTTP traffic to API gateway and WebSocket traffic to audio gateway
- Secrets are not exposed in manifests or logs
- CI/CD pipeline builds, pushes, and deploys on merge to main branch
- Rollback works: `helm rollback medscribe` restores previous version

## Implementation Notes

- Start with `k8s/` raw manifests for initial testing, then wrap in Helm chart
- Use `kustomize` overlays as an alternative to Helm if preferred
- GPU node pools must be provisioned separately in the cloud provider
- KEDA Kafka trigger uses the `kafka` trigger type with `lagThreshold` parameter
- For local development, use `kind` or `minikube` with the `k8s/` manifests (without GPU/KEDA)
- Docker multi-stage builds keep images small: Go services approximately 20MB, Rust services approximately 30MB, Python whisper approximately 4GB (includes model)

## Files to Create

```
k8s/
  api-gateway/
    deployment.yaml
    service.yaml
    ingress.yaml
  orchestrator/
    deployment.yaml
    service.yaml
  audio-gateway/
    deployment.yaml
    service.yaml
  kafka-consumers/
    deployment.yaml
  whisper/
    deployment.yaml
    keda-scaledobject.yaml
  infrastructure/
    kafka.yaml
    postgresql.yaml
    redis.yaml
    minio.yaml
  shared/
    configmap.yaml
    secrets.yaml
    networkpolicy.yaml

charts/medscribe/
  Chart.yaml
  values.yaml
  values-dev.yaml
  values-staging.yaml
  values-prod.yaml
  templates/
    ...
  NOTES.txt

.github/workflows/
  deploy.yml
```
