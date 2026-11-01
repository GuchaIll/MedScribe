#!/usr/bin/env python
"""
Enqueue no-op ingest tasks by hand, to watch a worker and reconciler run them.

    DATABASE_URL=postgresql://... python scripts/enqueue_noop.py --count 20
"""

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text

from app.ingest.claim import PRIORITIES, enqueue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--session", default="manual-session")
    parser.add_argument("--priority", choices=PRIORITIES, default="active")
    args = parser.parse_args()
    if not 1 <= args.count <= 100000:
        parser.error(f"--count must be in [1, 100000], got {args.count}")
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is not set")

    engine = create_engine(url)
    with engine.begin() as conn:
        ids = [
            enqueue(conn, doc_id=uuid.uuid4(), session_id=args.session, stage="noop", priority=args.priority)
            for _ in range(args.count)
        ]
    with engine.connect() as conn:
        states = dict(conn.execute(text("select state, count(*) from ingest_tasks group by state")).fetchall())
    print(f"enqueued {len([i for i in ids if i is not None])} noop tasks; queue states now: {states}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
