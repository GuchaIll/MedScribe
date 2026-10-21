"""Ingest queue: task_priority enum, ingest_tasks, ingest_outbox (T2, #92).

DDL from SDD Appendix C.1, minus the ingest_tasks.doc_id foreign key:
ingest_documents belongs to #93, which adds the FK (NOT VALID, then VALIDATE).

Revision ID: 006_ingest_queue
Revises: 005_agent_trace_spans
Create Date: 2026-10-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006_ingest_queue"
down_revision: Union[str, None] = "005_agent_trace_spans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ordered: claim rank is the enum position (0 blocking, 1 active, 2 backfill).
    op.execute("create type task_priority as enum ('blocking', 'active', 'backfill')")

    op.execute(
        """
        create table ingest_tasks (
          task_id           bigserial primary key,
          doc_id            uuid not null,
          session_id        text not null,
          stage             text not null,
          page              int,
          priority          task_priority not null,
          state             text not null,
          attempts          smallint not null default 0,
          lease_token       uuid,
          lease_owner       text,
          lease_expires_at  timestamptz,
          not_before        timestamptz not null default now(),
          enqueued_at       timestamptz not null default now(),
          last_error        text,
          constraint ingest_tasks_page_iff_page_stage
            check ((stage = 'page') = (page is not null)),
          constraint ingest_tasks_leased_has_lease
            check ((state = 'leased') = (lease_token is not null and lease_expires_at is not null)),
          constraint ingest_tasks_state_known
            check (state in ('queued', 'leased', 'done', 'failed')),
          constraint ingest_tasks_attempts_nonneg
            check (attempts >= 0)
        )
        """
    )
    # NULLs are distinct in a plain unique constraint, so each stage kind needs its own.
    op.execute(
        "create unique index ingest_tasks_doc_stage on ingest_tasks (doc_id, stage) "
        "where page is null"
    )
    op.execute(
        "create unique index ingest_tasks_page_stage on ingest_tasks (doc_id, stage, page) "
        "where page is not null"
    )
    op.execute(
        "create index ingest_tasks_claim on ingest_tasks (stage, priority, enqueued_at) "
        "where state = 'queued'"
    )
    # Not in C.1: the lease-expiry sweep reads leased rows by expiry every 5 s.
    op.execute(
        "create index ingest_tasks_lease_expiry on ingest_tasks (lease_expires_at) "
        "where state = 'leased'"
    )

    op.execute(
        """
        create table ingest_outbox (
          event_id    uuid primary key,
          topic       text not null,
          key         text not null,
          payload     jsonb not null,
          created_at  timestamptz not null default now(),
          sent_at     timestamptz
        )
        """
    )
    op.execute(
        "create index ingest_outbox_unsent on ingest_outbox (created_at) where sent_at is null"
    )


def downgrade() -> None:
    op.execute("drop index if exists ingest_outbox_unsent")
    op.execute("drop table if exists ingest_outbox")
    op.execute("drop index if exists ingest_tasks_lease_expiry")
    op.execute("drop index if exists ingest_tasks_claim")
    op.execute("drop index if exists ingest_tasks_page_stage")
    op.execute("drop index if exists ingest_tasks_doc_stage")
    op.execute("drop table if exists ingest_tasks")
    op.execute("drop type if exists task_priority")
