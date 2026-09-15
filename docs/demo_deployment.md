# MedScribe Demo Deployment Guide

This guide gives you a concrete, low-friction way to host MedScribe for a live demo without pretending the repo is already fully productionized.

It is intentionally split into two lanes:

1. `Public demo lane`
   Uses the frontend and Python API path that works end to end today.
2. `Architecture benchmark lane`
   Keeps the Go gateway + Kafka ingestion path available on the same host so you can validate the scalable design separately.

## What This Deploys

- `client/medscribe` as a static frontend behind nginx on port `80`
- `server/` Python API on `127.0.0.1:3001`
- `services/api` Go gateway on `127.0.0.1:8080`
- PostgreSQL, Redis, Kafka, and Kafka topic bootstrap

The `client/v2` Vite-based UI is wired into `docker compose up` (the
**development** stack) on `http://localhost:3100` so it can be brought up
alongside the original CRA client during the migration. It is **not** part
of the demo overlay because it is still mock-driven; see
[v2_integration_plan.md](./v2_integration_plan.md). The demo lane continues
to serve `client/medscribe` only.

## Important Reality Check

For a quick hosted demo, the public UI should call the Python API directly.

Why:

- `client/v2/` (originally `whisperwave-transcribe/`) is still mock-driven and does not call the MedScribe backend yet. See [whisperwave_integration.md](./whisperwave_integration.md) and the migration plan in [v2_integration_plan.md](./v2_integration_plan.md).
- The Go gateway path is strong for ingestion benchmarking, but the checked-in frontend is not fully wired to the secured Go auth flow yet.
- The Python `SessionService` keeps live session state in process memory, so the demo API should run with `1` worker for now.

That is why [`docker-compose.demo.yml`](../docker-compose.demo.yml) serves the frontend through nginx and proxies `/api` to `api:3001`, while still keeping the Go gateway alive on localhost for load tests.

## Recommended Host Sizes

Use synthetic or de-identified data only for internet demos.

### Cheapest setup that still works

- `2 vCPU / 4 GB RAM`
- good for UI walkthroughs, short transcripts, and light record generation
- not recommended for OCR-heavy demos

### Recommended single-host demo box

- `4 vCPU / 8 GB RAM`
- better for live transcription + pipeline + a few OCR documents

### If you want smoother OCR

- `8 vCPU / 16 GB RAM`
- best if your demo includes multiple uploaded PDFs or repeated OCR runs

## Cost-Efficient Hosting Options

### Option A: Cheapest and fastest

Use a single Ubuntu VM and deploy with Docker Compose.

Good fit when:

- you want the fastest path to a public demo
- you are okay with one host running everything
- you want predictable monthly cost

Example pricing references checked on May 13, 2026:

- DigitalOcean Droplets start at `$4/month`: https://www.digitalocean.com/pricing/droplets
- Docker install on Ubuntu: https://docs.docker.com/installation/ubuntulinux/
- Docker Compose plugin install: https://docs.docker.com/compose/install/linux/

### Option B: More managed, less cheap

Use Cloud Run or another managed container platform for the services, plus managed Postgres and Redis.

Good fit when:

- you want easier restarts and less VM management
- you are okay paying more for Cloud SQL / managed Redis
- you want a cleaner path toward future production hardening

References:

- Cloud Run pricing: https://cloud.google.com/run/pricing
- Pub/Sub with Cloud Run: https://docs.cloud.google.com/pubsub/docs/use-with-cloud-run

For a quick demo, Option A is the best tradeoff.

## Files Added For This Guide

- [`docker-compose.demo.yml`](../docker-compose.demo.yml): demo-safe overlay
- [`client/medscribe/Dockerfile.prod`](../client/medscribe/Dockerfile.prod): static production frontend image
- [`client/medscribe/nginx.conf`](../client/medscribe/nginx.conf): SPA hosting + `/api` proxy to Python API

## Before You Start

You need:

- Ubuntu `22.04`, `24.04`, or newer
- a DNS record pointed at the VM if you want a custom domain
- at least one LLM provider key in `.env`
- only synthetic or de-identified demo data

## Step 1: Create the VM

For the recommended path:

- image: `Ubuntu 24.04 LTS`
- size: `4 vCPU / 8 GB RAM`
- disk: `80 GB SSD` minimum
- open inbound ports: `22`, `80`

Keep `8080`, `3001`, `5432`, `6379`, and `9092` closed to the public internet.

## Step 2: Install Docker and Compose

SSH into the server and run:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker

docker --version
docker compose version
```

Optional basic firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw enable
sudo ufw status
```

Note from Docker's Ubuntu docs: container-exposed ports can bypass some host firewall expectations, so only publish the ports you actually want public.

## Step 3: Clone the Repo

```bash
git clone https://github.com/GuchaIll/MedicalTranscriptionApp.git
cd MedicalTranscriptionApp
```

## Step 4: Configure Environment Variables

Start from the checked-in template:

```bash
cp .env.example .env
```

Edit `.env` and set these at minimum:

```env
GROQ_API_KEY=...

SECRET_KEY=...
JWT_SECRET_KEY=...
ENCRYPTION_KEY=...
```

Notes:

- `GROQ_API_KEY` is the best default for quick demos because the repo already leans on Groq for latency-sensitive nodes.
- `JWT_SECRET_KEY` and `ENCRYPTION_KEY` are still required because the Go gateway starts even if the public demo path is using the Python API through nginx.

## Step 5: Start the Stack

Use the base compose file plus the demo overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

Check container status:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml ps
```

Follow logs if needed:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f gateway
docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f client
```

## Step 6: Verify Health

From the VM:

```bash
curl http://127.0.0.1:3001/
curl http://127.0.0.1:8080/health
curl -I http://127.0.0.1/
```

From your laptop or browser:

```text
http://YOUR_SERVER_IP/
```

Expected:

- port `80` serves the MedScribe frontend
- `/api/*` requests from the browser are proxied to the Python API
- the Go gateway stays reachable only from the server on `127.0.0.1:8080`

## Step 7: Restart and Update Workflow

When you change backend or frontend code:

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

To restart only one service:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml restart api
docker compose -f docker-compose.yml -f docker-compose.demo.yml restart client
```

To stop the deployment:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml down
```

To stop and also remove persistent volumes:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml down -v
```

## Optional: Monitoring Stack

If you want live dashboards during testing:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.demo.yml \
  -f docker-compose.monitoring.yml \
  up -d
```

Then open:

- Prometheus: `http://YOUR_SERVER_IP:9090`
- Grafana: `http://YOUR_SERVER_IP:3100`

Only open those ports temporarily during testing.

## Demo Runbook

For the smoothest public demo:

1. Bring the stack up at least `10-15` minutes before the demo.
2. Open the app once and run one warm-up session.
3. Trigger one pipeline run before the audience joins.
4. If OCR is part of the demo, upload a sample file once in advance to warm dependencies.
5. Keep two fallback stories ready:
   - transcript-only flow
   - preprocessed document flow

## Recommended Demo Scope

Use these features confidently:

- start a session
- capture transcript
- trigger structured record generation
- generate SOAP/discharge output
- ask assistant questions

Treat these as higher-risk:

- multiple large PDF uploads in one demo
- repeated OCR runs back to back
- high-concurrency public usage from many people at once

## Benchmarking Strategy

You want three distinct benchmarks, because they answer different questions.

### 1. Smoke test

Use this before every demo or deploy:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:3001/
curl -I http://127.0.0.1/
```

Goal:

- verify routing is up
- verify gateway is alive
- verify Python API is alive

### 2. Ingestion benchmark

This measures the scalable architecture claim:

- HTTP request accepted
- JWT/session validation
- Kafka enqueue
- Redis seed
- `202 Accepted`

Run:

```bash
chmod +x scripts/bench-qps.sh
./scripts/bench-qps.sh --url http://127.0.0.1:8080 --qps 50 --duration 1m --vus 50 --sessions 50
```

Use this for:

- validating the Go gateway path
- checking whether Kafka and Redis are healthy
- measuring enqueue latency independent of full pipeline time

Start targets for a single demo VM:

- `p95 < 250ms`
- success rate `> 99%`

### 3. Full pipeline benchmark

This measures what a demo user actually feels after clicking generate.

Run:

```bash
chmod +x scripts/load-test.sh
./scripts/load-test.sh --url http://127.0.0.1:8080 --vus 5 --duration 5m
```

What it measures:

- full gateway -> Kafka -> Python pipeline path
- end-to-end status polling until `completed` or `failed`

Reasonable first targets for demo readiness:

- transcript-only pipeline p50 `< 30s`
- transcript-only pipeline p95 `< 60s`
- failure rate `< 5%`

### 4. OCR benchmark

This should be tested separately because document size dominates runtime.

Create three sample sets:

- `small`: 1 page PDF or image
- `medium`: 3-5 pages
- `large`: 10+ pages

For each set, measure:

- upload accepted time
- OCR completion time
- total pipeline completion time after OCR artifacts are injected

Track:

- p50 / p95 wall-clock time
- extracted fields count
- failure count
- memory pressure on the host

Use only synthetic docs.

## Benchmark Commands

### Ingestion benchmark

```bash
./scripts/bench-qps.sh --url http://127.0.0.1:8080 --qps 100 --duration 2m --vus 100 --sessions 100
```

### Full pipeline benchmark

```bash
./scripts/load-test.sh --url http://127.0.0.1:8080 --vus 10 --duration 10m
```

### Monitoring during benchmark

```bash
docker stats
docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f gateway
docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f api
```

## What To Watch During Benchmarks

- `gateway` CPU spikes: ingestion bottleneck or auth/cache overhead
- `api` CPU spikes: pipeline node bottleneck, usually extraction or OCR
- memory growth: Python embeddings/OCR load, Kafka, or DB pressure
- long gaps between node completions: slow LLM node or OCR stage
- Redis/Grafana status lag: progress visibility bottleneck

## Demo-Friendly Thresholds

Use these as practical go/no-go numbers:

- `/health` under `100ms`
- pipeline trigger p95 under `250ms`
- transcript-only full run under `30s` median
- single-page OCR under `20s` median
- no crash or OOM during `5` concurrent full-pipeline users

## Known Limitations

- `client/v2/` is not the hosted demo frontend yet (it is dev-only on `:3100`).
- Public demo traffic is proxied to the Python API because that path is the one currently wired for end-to-end UI behavior.
- The Python API must stay at `1` worker because active session state is process-local today.
- The Go upload path is still incomplete, so document upload validation should happen through the Python-backed public demo path, not the gateway path.
- This deployment is `demo-safe`, not HIPAA-compliant production.

## If You Need A More Prod-Like Next Step

After the demo succeeds, the next upgrades should be:

1. move public traffic to the Go gateway
2. finish frontend auth integration against gateway JWT flow
3. finish gateway upload implementation
4. move live session state out of Python process memory
5. split OCR workers from transcript pipeline workers
6. add TLS termination and real secret management
