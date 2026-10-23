# 92 — Worker lifecycle and provisioning: claim, lease, fence, reconciler on a no-op stage (T2)

**Issue:** #92
**Parent issue:** #77 (agent refactor epic)
**Sub-issues:** none
**Branch:** `feat/92-worker-lifecycle`
**Depends on:** #50 (merged). **Not** on #91. T0 (#91) is first for urgency, not because #92 needs it. The two touch different code.
**Blocks:** #59 (T5 page stage), #54 (T6 finalize), and phase 3 as a whole. Per SDD §9.8, phase 3 does not start until this ticket's conformance suite is green, including kill-mid-lease and commit-past-lease.
**Source docs:** `docs/design/medscribe-runtime-sdd.md` §2.3.3 T2, §3.2, §4.3, §4.4, §5.2.3.3, §5.2.3.4 (fence and notify ordering), §5.2.3.6, §9.8, Appendix C.1 (DDL), C.3 (claim), C.4 (renew and fence), D.4 (metrics). These SDD docs are untracked local files in the main checkout (`/Users/guchaill/Coding/MedScribe/docs/design/`), not in git.

## Goal

A batch worker can be provisioned, claim work, survive being killed, and be
measured, all against a no-op stage, before any OCR code runs on it. The queue
protocol (claim with priority and aging, per-session soft cap, lease token,
renewal, fence-first commit, retry with backoff, exhaustion) is proven by a
conformance suite against real Postgres. The stage interface it exposes is what
T5 (page) and T6 (finalize) plug into.

"Lifecycle before payload": nothing in this ticket knows what a document,
page, chunk, or OCR result is.

## Prerequisites (check before writing code)

1. **Alembic has two heads on `main`.** `004_provenance_receipt_locators` and
   `005_agent_trace_spans` both have `down_revision = "003_nullable_session_patient"`.
   This ticket adds a migration, so the chain must have one head first. Fix it
   in a separate small PR (`fix/alembic-two-heads`): set
   `005.down_revision = "004_provenance_receipt_locators"`, or add an empty
   merge revision. `alembic heads` must print one head. If #91's session
   already fixed it, rebase on that.
2. **Postgres version.** Compose runs `pgvector/pgvector:pg15`. The SDD wants
   17 for `transaction_timeout` (bounds how long a fenced output transaction
   can hold the task row lock). Decision for T2: **stay on 15** and bound the
   hold with `SET LOCAL statement_timeout` plus
   `SET LOCAL idle_in_transaction_session_timeout` inside the output
   transaction. Record this in the PR. The upgrade to 17 belongs to #96 (T16),
   so add a line to #96 instead of upgrading here. Everything else in C.1, C.3
   and C.4 works on 15 (`gen_random_uuid()` is core since 13; partial unique
   indexes, `SKIP LOCKED`, enums, and `clock_timestamp()` are all available).
3. **Local venv.** `/Users/guchaill/Coding/MedScribe/.venv` is missing deps
   (no `sqlalchemy`). Run `.venv/bin/pip install -r server/requirements.txt`.
   Run pytest with `-o addopts=""` (the default `--cov` flags need `pytest-cov`).
4. Read `AGENTS.md`: issue workflow, implementation rules, and the data-model
   proof. The PR body needs Changes / Plan / Test criteria / Self-review.

## Decisions this plan makes (state them in the PR; change them only with a reason)

1. **No FK from `ingest_tasks.doc_id` to `ingest_documents` in this ticket.**
   `ingest_documents` and `ingest_document_readiness` belong to #93 (T4), per
   the SDD F.3 checklist row for #93. T2 creates `ingest_tasks.doc_id uuid not null`
   without the FK. #93 adds
   `foreign key (doc_id) references ingest_documents` (`NOT VALID`, then
   `VALIDATE`). Add a "Revised" note to #93 saying so. This keeps T2 payload-free,
   and the conformance suite can seed arbitrary `doc_id`s.
2. **Terminal transitions are a stage hook, not hard-coded.** C.1 / §5.2.3.6
   say that at max attempts the reconciler marks the task `failed` "plus the
   document's terminal transition, in one transaction". The document readiness
   table does not exist yet, so the engine calls `stage.on_exhausted(conn, task)`
   inside the same transaction that sets `state = 'failed'`. The no-op stage
   implements it as a no-op that writes one outbox row (so the suite can assert
   it ran exactly once). #93 / #59 implement the readiness transition.
3. **Progress fan-out, the Stats loop, retention purge, orphan GC, and the
   Kubernetes `Lease` sharding (§5.2.3.6) are out of scope.** They read
   readiness and streams that T4 / T12 create. T2 ships the three loops the issue
   names: lease expiry (5 s), outbox relay (1 s), and repair (60 s). Repair in T2
   checks only queue-internal invariants (below), because the document-level
   repair checks need T4 tables.
4. **Sync SQLAlchemy Core plus psycopg2**, matching the repo
   (`server/app/database/session.py`, `sqlalchemy==2.0.25`, `psycopg2-binary`).
   Statements are `text()` with bound parameters, taken verbatim from C.3 / C.4.
   No ORM models for queue rows: the queue is a protocol over SQL, and the
   ORM's unit-of-work would hide the statement ordering the fence depends on.
   Add a SQLAlchemy `Table` definition only if Alembic autogenerate needs it.
5. **Outbox relay publishes through an interface.** `OutboxPublisher.publish(topic, key, payload, event_id)`
   has a Kafka implementation and an in-memory fake for tests. Python has no
   Kafka client in `requirements.txt` today. Add `confluent-kafka` (pinned)
   **only if** the compose run of the relay is part of this PR. Otherwise ship
   the fake plus a logging publisher, and open a follow-up. Prefer shipping the
   Kafka publisher: compose already runs Kafka (`apache/kafka:4.2.0`), and the
   relay is a named deliverable.
6. **Defaults** (all config, validated):
   - `lease_seconds = 30`
   - renew every `lease / 3` (10 s)
   - `aging_step_seconds = 240` (SDD: backfill waits "about four minutes" behind fresh active work)
   - per-session soft cap `page_task_cap = 4` (applies to `stage = 'page'` only; `blocking` exempt)
   - claim `batch = 1`
   - `max_attempts = 5`
   - backoff `not_before = now() + min(2^attempts, 60) s` with ±20% jitter
   - poll interval 250 ms when idle (back off to 2 s after 10 empty polls), wake immediately on `LISTEN ingest_tasks` if added. LISTEN for new tasks is optional in T2; polling is enough to pass the suite.

## Files

New:
- `server/app/ingest/__init__.py`
- `server/app/ingest/config.py`: `IngestQueueConfig` (pydantic), validated: `lease_seconds` in `[5, 600]`, `aging_step_seconds > 0`, `page_task_cap` in `[1, 64]`, `max_attempts` in `[1, 20]`, `batch` in `[1, 16]`. On invalid values raise `IngestConfigError` naming the field, value, and range.
- `server/app/ingest/errors.py`: `IngestConfigError`, `LeaseLostError` (renew returned zero rows), `FenceRejectedError` (fence returned zero rows), `UnknownStageError`, `StageContractError` (stage returned or raised something the engine does not accept). All subclass a new `IngestError`.
- `server/app/ingest/claim.py`: `claim(conn, stage, pod, cfg) -> list[ClaimedTask]` (C.3 verbatim, parameters bound), `renew(conn, task) -> bool` (C.4), `fence(conn, task) -> bool` (C.4, must be the first statement of the output transaction), `bump_to_blocking(conn, doc_id)`.
- `server/app/ingest/stage.py`: the `Stage` protocol (below) and the stage registry.
- `server/app/ingest/engine.py`: `Worker`. Poll, claim, run compute with no transaction open, renew on a heartbeat thread, open the output transaction, fence, run `stage.commit(conn, task, output)`, commit. Handles retry and exhaustion paths.
- `server/app/ingest/reconciler.py`: the three loops, each a `SKIP LOCKED` sweep, safe with two replicas.
- `server/app/ingest/outbox.py`: `OutboxPublisher` protocol, `KafkaOutboxPublisher`, `InMemoryOutboxPublisher`, and `write_outbox(conn, topic, key, payload)` used inside output transactions.
- `server/app/ingest/noop_stage.py`: the no-op stage (configurable sleep, configurable failure injection for tests).
- `server/app/ingest/metrics.py`: optional `prometheus_client` the same way `server/app/agents/tracing/sinks.py` does it (no-op when not installed).
- `server/app/ingest/__main__.py`: `python -m app.ingest worker --stage noop` and `python -m app.ingest reconciler`.
- `server/migrations/versions/006_ingest_queue.py`: `task_priority` enum, `ingest_tasks`, `ingest_outbox`, the two partial unique indexes, the claim index (C.1 verbatim, minus the `doc_id` FK; see decision 1). `downgrade()` drops them in reverse order.
- `server/harness/` (shared harness infra, SDD §2.3.3): `runner.py` (runs a named suite, collects metrics), `report.py` (writes `docs/benchmarks/<suite>/<date>-baseline.md` plus JSON). T3 (#98) extends it, so keep it small and generic.
- `server/tests/ingest/` conformance suite (below).
- `infra/k8s/services/ingest-worker/deployment.yaml` and `infra/k8s/services/ingest-reconciler/deployment.yaml` (2 replicas), following the shape of `infra/k8s/services/ocr-worker/deployment.yaml` (labels, prometheus annotations, `envFrom` config and secret, readiness probe).

Changed:
- `docker-compose.yml`: add `ingest-worker` (same image as `api`, command `python -m app.ingest worker --stage noop`) and `ingest-reconciler`, depending on `db` (and `kafka` if decision 5 ships Kafka).
- `server/requirements.txt`: `confluent-kafka` (if decision 5), nothing else.

## Stage interface (what #59 and #54 implement)

```python
class Stage(Protocol):
    name: str                       # matches ingest_tasks.stage; registry key
    lease_seconds: int | None       # per-stage override; None = config default

    def compute(self, task: ClaimedTask) -> StageOutput:
        """Pure work. No DB transaction is open. May take long; the engine renews the lease."""

    def commit(self, conn: Connection, task: ClaimedTask, output: StageOutput) -> None:
        """Runs inside the output transaction, after the fence returned a row.
        Every effect is a Postgres row: outputs, follow-on tasks, outbox rows, pg_notify.
        Must not call Redis, Kafka, HTTP, or the object store."""

    def on_exhausted(self, conn: Connection, task: ClaimedTask, last_error: str) -> None:
        """Runs in the transaction that marks the task failed at max attempts."""
```

`ClaimedTask` is exactly what the C.3 `returning` clause gives: `task_id`,
`doc_id`, `page`, `lease_token`. Plus `session_id`, `stage` and `attempts`,
which the engine needs for logging, the per-stage lease override, and backoff.
**Extend the `returning` clause with those three columns.** Do not re-read the
row. Data-model proof for `ClaimedTask`, per field: `task_id`, `lease_token`
(renew, fence, retry update); `doc_id`, `page` (read by `stage.compute`);
`session_id` (log context, metric labels); `stage` (registry lookup);
`attempts` (backoff, exhaustion). No other fields.

`StageOutput` is opaque to the engine (each stage defines its own). The engine
never inspects it.

## Engine flow (one task)

1. **Claim** (own short transaction): C.3. Zero rows -> sleep the poll interval.
2. **Compute** with no transaction open. A heartbeat thread runs `renew()` every
   `lease / 3`. On a renew that returns zero rows: set a `lease_lost` event;
   `compute` is not interrupted (it cannot be safely), but its output is
   discarded. Log `warning` "lease lost" with task id, stage, session id, doc id,
   attempts. Increment `ingest_lease_lost_total{stage}`. Write nothing.
3. **Output transaction:** `begin` -> `SET LOCAL statement_timeout`,
   `SET LOCAL idle_in_transaction_session_timeout` (decision on pg15) ->
   **fence (first data statement)** -> zero rows: `rollback`, log `warning`
   "fence rejected", increment `ingest_fence_rejections_total{stage}`, write
   nothing -> otherwise `stage.commit(...)` -> `commit`.
   Note: C.4's fence sets `state = 'done'` itself, so the task's own completion
   and the stage outputs commit atomically.
4. **Compute raised:** in a new transaction, run the fence-style guard (token
   match, still leased). If it matches: `attempts < max_attempts` ->
   `state = 'queued'`, `lease_token = null`, `lease_expires_at = null`,
   `not_before = backoff`, `last_error = <exception class and message, truncated to 2000 chars, no payload text>`.
   Otherwise -> `state = 'failed'` plus `stage.on_exhausted` in the same
   transaction. Zero rows (lease already gone) -> write nothing; the reconciler
   owns it. Log every retry at `warning` and every exhaustion at `error`.
5. **`stage.commit` raised:** the transaction rolls back (fence included, so
   the task stays `leased` with our token). Then run step 4's retry path.
   Increment `ingest_task_retries_total{stage,reason}`.

`SET LOCAL app.patient_id` (from C.4) is not needed for the no-op stage. The
engine exposes a `before_commit(conn, task)` hook so T5 can set it when RLS
tables are written. Note this in the stage docstring.

## Reconciler loops (T2 subset)

- **Lease expiry, 5 s.** `select ... from ingest_tasks where state = 'leased' and lease_expires_at < clock_timestamp() for update skip locked limit 100`.
  For each: under `max_attempts` -> back to `queued` with backoff and
  `last_error = 'lease_expired'`; at max -> `failed` plus `on_exhausted` in the
  same transaction. Log each at `warning` (task id, stage, `lease_owner`,
  attempts).
- **Outbox relay, 1 s.** `select ... from ingest_outbox where sent_at is null order by created_at for update skip locked limit 100`, copy the rows, and commit before publish. Publish outside the transaction, then `update sent_at` in its own transaction. Publish succeeded but the update failed -> the row is re-sent next tick (at-least-once; consumers dedupe on `event_id`). Publish failed -> leave `sent_at` null, log `warning` with `event_id` and topic, increment `ingest_outbox_publish_failures_total`, keep going with the next row. Never block lease expiry on one bad row or a slow broker: expiry runs on its own thread. Age alarm: the oldest unsent row's age is the metric `ingest_outbox_oldest_unsent_seconds`.
- **Repair, 60 s (queue-internal only in T2).** Log at `warning`, do not fix
  automatically:
  - tasks `queued` with `attempts >= max_attempts` (should have been `failed`)
  - rows that violate the leased-state CHECK cannot exist, so instead count
    `leased` rows whose `lease_expires_at` is more than 10x the lease length in
    the past (lease expiry loop stuck)
  - outbox rows unsent for more than 5 min

  The document-level repair checks from §5.2.3.6 arrive with #93 / #59.
- Two reconciler replicas run in compose and k8s. Every loop uses
  `SKIP LOCKED`, so there is no leader election (verify in the suite).

## Metrics (SDD D.4 names; add only these)

`ingest_queue_depth{stage,priority}` (reconciler samples every 5 s),
`ingest_task_age_seconds{stage}` (claim time minus `enqueued_at`),
`ingest_claims_total{stage,priority}`, `ingest_task_retries_total{stage,reason}`,
`ingest_fence_rejections_total{stage}`, `ingest_lease_lost_total{stage}`,
`ingest_outbox_publish_failures_total`, `ingest_outbox_oldest_unsent_seconds`.

## Data models (proof for the PR)

- `ingest_tasks`, `ingest_outbox`: columns exactly as SDD C.1 (minus the
  `doc_id` FK, decision 1). Per-field readers are listed in SDD §4.3 / §4.4;
  copy that table into the Self-review. `last_error` is diagnostic (read by an
  engineer and by repair logging). Keep it, as the SDD does.
- No new runtime contract types in `tool_contracts.py`. The queue is internal
  to ingestion.
- Check consistency: `task_priority` values `blocking | active | backfill` are
  used everywhere (SDD revision 2026-09-28). `stage` values: only `noop` is
  registered in T2. The SDD set (`split | page | finalize | embed_backfill`) is
  what #93 / #59 / #54 register. The column is `text`, so no enum migration is
  needed later. Do not add `noop` to any enum.

## Conformance suite (`server/tests/ingest/`, marker `db`, real Postgres)

Runs against compose `db` (`docker compose up -d db`, then
`alembic upgrade head`). Each test gets a clean schema (truncate the queue
tables in a fixture). Concurrency comes from real OS processes
(`multiprocessing`, spawn) or threads with separate connections, never one
shared connection.

1. **No double commit.** 8 concurrent workers, 2,000 no-op tasks across 50
   sessions. Every task ends `done` exactly once. The no-op stage's commit
   inserts one row into a test-only `noop_commits(task_id unique)` table created
   by the fixture, not the migration. A duplicate is a unique violation, which
   fails the test.
2. **Kill mid-lease.** A worker claims, starts a 5 s compute, and is SIGKILLed
   at 1 s. After lease expiry plus one reconciler tick, the task is `queued`
   with `attempts = 1`, `last_error = 'lease_expired'`. A second worker commits
   it once. Exactly one `noop_commits` row.
3. **Commit past lease.** Compute sleeps longer than the lease, with renewal
   disabled. A second worker re-claims and commits. The first worker's fence
   returns zero rows, it writes nothing, and `ingest_fence_rejections_total`
   increments. Exactly one `noop_commits` row, from the second worker's token.
4. **Restart under the same pod name.** A worker with `lease_owner = pod-a` is
   killed; a new process also named `pod-a` claims a different task. The old
   token cannot commit (fence is by token, not owner).
5. **Renewal keeps a long task alive.** A 3x-lease compute with renewal on
   commits once; `ingest_lease_lost_total` stays 0.
6. **Priority and aging.** Seed `backfill` tasks enqueued 10 min ago and fresh
   `active` tasks. The backfill tasks are claimed before fresh active tasks once
   their age exceeds `aging_step`. `blocking` always leads. Measure and report
   the starvation bound (max wait for `backfill` under a continuous `active`
   stream).
7. **Per-session cap.** One session with 100 page-stage tasks, others with 5
   each, 8 workers. Leased page tasks for the big session never exceed
   `cap + workers` (the documented overshoot). `blocking` tasks bypass the cap.
   Uses `stage = 'page'` rows with the no-op registered under that name for the
   test, because the cap applies to page tasks.
8. **Bump.** `bump_to_blocking(doc_id)` on queued tasks; the next claim takes them first.
9. **Retry and exhaustion.** Compute raises on attempts 1-4 and succeeds on 5
   -> `done`. Compute always raises -> `failed` at `max_attempts`,
   `on_exhausted` ran exactly once (its outbox row exists once), `last_error`
   set, no payload text in it.
10. **Commit raises.** `stage.commit` raises after the fence -> rollback; the
    task retries; no partial output rows.
11. **Two reconcilers.** Both replicas running; each expired lease is handled
    exactly once (attempts incremented once).
12. **Outbox at-least-once.** The publisher fails for one row; the relay moves
    on and retries it next tick; `sent_at` is set after success; with a forced
    failure between publish and `sent_at`, the row is published twice with the
    same `event_id`.
13. **Uniqueness.** Inserting a duplicate `(doc_id, stage)` with `page is null`,
    or a duplicate `(doc_id, stage, page)`, conflicts on the matching partial
    index (`on conflict ... where page is null do nothing` is a no-op).
    CHECKs: `stage = 'page'` with a null page, and `leased` with a null token,
    are both rejected.

Unit tests (no DB): config validation errors name the field; the stage registry
rejects an unknown stage (`UnknownStageError`); the backoff function stays in
range with jitter; engine paths with a fake connection (lease lost -> no
writes; fence zero rows -> rollback).

**Baseline report (harness):** throughput (tasks/s) at 1, 4, 8 workers; claim
latency p50/p95; fence rejection rate under induced churn (kill a random worker
every 10 s for 2 min); starvation bound; cap overshoot observed. Write it with
`server/harness/report.py` to `docs/benchmarks/ingest-queue/<date>-baseline.md`
and commit it.

## Non-happy path summary (for the plan gate in AGENTS.md)

| Case | Behavior |
| --- | --- |
| Invalid config | `IngestConfigError` at startup naming field, value, range; process exits non-zero |
| DB unavailable at startup | Retry connect with backoff for 30 s, logging each attempt at `warning`; then exit non-zero (k8s restarts it). Never start polling without a DB |
| DB drops mid-claim | Claim transaction fails; log `warning`; next poll retries. Nothing was leased (the statement is atomic) |
| DB drops mid-compute | Renewals fail -> treated as lease lost after the lease expires locally; output discarded; the reconciler re-queues |
| Unknown stage in a claimed row | Cannot happen (claim filters by stage); the registry raises `UnknownStageError` at worker startup if `--stage` is not registered |
| Empty queue | Poll backoff to 2 s; `debug` log only |
| Oversized `last_error` | Truncated to 2000 chars |
| Duplicate enqueue | Partial unique index plus `on conflict ... do nothing`; enqueue is idempotent |
| Out-of-order completion | Irrelevant to the queue; each task fences independently |
| Kafka down | Outbox rows accumulate; relay logs and retries; `ingest_outbox_oldest_unsent_seconds` rises; the worker is unaffected (it never talks to Kafka) |

## Steps

1. (Prerequisite PR) Fix the Alembic two-heads problem.
2. Commit this plan as the first commit on `feat/92-worker-lifecycle`.
3. Migration `006_ingest_queue.py`; `alembic upgrade head` and `downgrade -1` both work against compose Postgres.
4. `config.py`, `errors.py`, `claim.py` plus unit tests.
5. `stage.py`, `noop_stage.py`, `engine.py` plus unit tests with a fake connection.
6. `reconciler.py`, `outbox.py` plus unit tests.
7. Conformance suite 1-13 against compose Postgres.
8. `__main__.py`, compose services, k8s manifests; run `docker compose up ingest-worker ingest-reconciler` and enqueue tasks by hand (`scripts/enqueue_noop.py`), checking that they complete.
9. `server/harness/` runner and report writer; produce and commit the baseline report.
10. Add a "Revised" note to #93 (FK added there, `on_exhausted` hook to implement) and a line on #96 (Postgres 17 for `transaction_timeout`).
11. Self-review against AGENTS.md, then push and open the PR. The Test criteria list each conformance case with pass/fail.

## Acceptance (from the issue)

- [ ] `ingest_tasks` and `ingest_outbox` per SDD C.1, with both partial unique indexes
- [ ] One-statement claim with `SKIP LOCKED`, priority with aging, per-session soft cap (`blocking` exempt)
- [ ] New `lease_token` per claim; renew every `lease / 3`; zero rows on renew = abandon, write nothing
- [ ] Fence is the first statement of the output transaction, using `clock_timestamp()`; zero rows = roll back
- [ ] Engine with a registered no-op stage; stage interface ready for T5 and T6
- [ ] Reconciler: lease expiry (5 s), outbox relay (1 s), repair (60 s); `SKIP LOCKED`; two replicas, no leader election
- [ ] Metrics: `ingest_task_age_seconds`, `ingest_fence_rejections_total`, claims per priority (plus the D.4 set above)
- [ ] Compose service and k8s manifest for one batch worker, landed together
- [ ] Harness infra (runner, baseline report writer)
- [ ] Conformance suite green, including kill-mid-lease and commit-past-lease (the §9.8 gate)

## Implementation notes (revised 2026-10-20, during the work)

Changes from the plan above, each with its reason:

1. **`blocking` sorts strictly first in the claim.** C.3's formula alone lets a
   `backfill` task older than `2 * aging_step` (8 min at defaults) outrank a
   fresh `blocking` task, which contradicts "blocking always leads"
   (§5.2.3.3). The claim orders by `(priority <> 'blocking')` first, then the
   C.3 aging term. Conformance case 6 asserts the exact order.
2. **`ClaimedTask` also carries `priority` and `age_seconds`**, read by
   `ingest_claims_total{priority}` and `ingest_task_age_seconds`. Both come from
   the claim's `returning` clause, so the engine still never re-reads the row.
3. **The per-session cap applies to `stage = 'page'` only**, as §5.2.3.3 says
   ("leased page tasks"). Other stages bind `cap = null`.
4. **Migration adds two CHECKs and two indexes beyond C.1:**
   `state in (queued, leased, done, failed)` and `attempts >= 0`;
   `ingest_tasks_lease_expiry` (partial on `state = 'leased'`, read by the
   5 s expiry sweep) and `ingest_outbox_unsent` (partial on `sent_at is null`,
   read by the 1 s relay).
5. **Backoff base and cap are config** (`backoff_base_seconds = 2`,
   `backoff_cap_seconds = 60`, so the defaults match "min(2^attempts, 60)").
   The suite uses 0.05 s so retry cases run in seconds.
6. **`prometheus-client` is added to the requirements** along with
   `confluent-kafka`: the worker serves `/metrics` on 8080 for the k8s scrape
   annotations. Both are also in `requirements.docker.txt`, which the image
   installs.
7. **The reconciler leaves an expired task leased if its stage is not
   registered in that reconciler** (logged at error every sweep). It cannot
   run that stage's `on_exhausted`, and marking the task failed without it
   would skip the document's terminal transition.
8. **Measured soft-cap overshoot is large for short tasks.** With cap 2 and 8
   workers on 50 ms tasks, the big session peaked at 8 leased tasks
   (p95 8, time-averaged 4.6). The documented bound (`cap + workers`) holds,
   but at this task length the cap barely binds. T5 should re-measure with real
   page times before choosing an advisory lock per session.
9. **Harness location:** `server/harness/` (`runner.py`, `report.py`,
   `suites/ingest_queue.py`). The queue suite reuses the conformance helpers in
   `server/tests/ingest/helpers.py`.
10. **Claim cost grows with queue depth.** The C.3 sort key is an expression, so
    every claim sorts all queued rows of the stage: claim p50 was about 0.9 ms
    with 500 queued and 3.5 ms (p95 7.5 ms) with 4,000 queued. This is fine at
    T2 volumes; T5 should watch it under a large backfill.
11. **Lease expiry is not on the relay thread.** A Kafka `flush` inside the
    outbox transaction stalled both replicas' 5 s expiry sweep. The relay now
    commits the `SKIP LOCKED` read before `publish`, and `run_forever` runs
    expiry on its own thread. Two replicas may both publish one `event_id`
    during that window; delivery stays at-least-once.
12. **Kubernetes image stays `ghcr.io/medscribe/server`.** `ghcr.io/medscribe/api`
    is the Go gateway binary and has no Python. Pods rewrite the shared
    secret's `postgres://` URL to `postgresql+psycopg2://` and apply Alembic
    head in an initContainer, because that secret is lib/pq-shaped and no other
    manifest migrates the Python schema.

## Out of scope

- `ingest_documents`, `ingest_document_readiness`, intake, object storage -> #93
- Real stages (`split`, `page`, `finalize`, `embed_backfill`) -> #93, #59, #54
- Progress fan-out (`LISTEN ingest` -> Redis stream), Kubernetes `Lease` sharding, Stats, retention purge, orphan GC -> #93 / #94
- Retiring the Go `ocr-worker` and the `ocr.jobs` topic -> #59 / #96
- Postgres 17 upgrade -> #96
- KEDA autoscaling on queue depth -> #96

## Risks and open questions

- **Soft cap overshoot** equals the number of concurrent claimers. The suite
  measures it. If it is too loose for T5, use an advisory lock per session
  around the claim, but measure the cost first.
- **Lease length versus real page time.** 30 s suits no-op tasks. T5 sets a
  per-stage override from measured OCR page time. A sustained
  `ingest_fence_rejections_total` rate means leases are too short (SDD D.4).
- **`compute` cannot be interrupted** on lease loss. The output is discarded,
  but CPU is wasted until compute returns. Acceptable; T5 can check the
  `lease_lost` event between pages of work.
- **Clock skew** does not matter: every comparison uses the database's
  `clock_timestamp()`, never the worker's clock. Keep it that way, and never
  compute `lease_expires_at` in Python.
- **pg15 lock-hold bound** uses `statement_timeout` plus
  `idle_in_transaction_session_timeout` instead of `transaction_timeout`. A
  long sequence of fast statements can still hold the lock longer than the
  bound. Acceptable for T2 (the no-op commit is one statement); revisit in #96.
