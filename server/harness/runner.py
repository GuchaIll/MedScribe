"""
Harness runner: run a named suite, collect its rows, write the baseline.

    python -m harness.runner ingest_queue --db-url postgresql://... \
        --out ../docs/benchmarks/ingest-queue

A suite is a module in harness/suites exposing
`run(args: argparse.Namespace) -> harness.report.Report` and
`add_arguments(parser)`. T3 (#98) adds its suite the same way.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from .report import write_baseline

logger = logging.getLogger("harness")

SUITES = {
    "ingest_queue": "harness.suites.ingest_queue",
}


class UnknownSuiteError(KeyError):
    pass


def load_suite(name: str):
    if name not in SUITES:
        raise UnknownSuiteError(f"unknown suite {name!r}; known: {', '.join(sorted(SUITES))}")
    return importlib.import_module(SUITES[name])


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("suite", choices=sorted(SUITES))
    known, _ = pre.parse_known_args(argv)
    suite = load_suite(known.suite)

    parser = argparse.ArgumentParser(prog="python -m harness.runner")
    parser.add_argument("suite", choices=sorted(SUITES))
    parser.add_argument("--out", type=Path, required=True, help="directory for <date>-baseline.md/.json")
    suite.add_arguments(parser)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # The queue logs every claim at INFO; keep the harness output readable.
    logging.getLogger("app.ingest").setLevel(logging.WARNING)
    started = time.monotonic()
    logger.info("suite starting suite=%s", args.suite)
    report = suite.run(args)
    md, js = write_baseline(report, args.out, title=getattr(suite, "TITLE", None))
    logger.info("suite done suite=%s rows=%d seconds=%.1f report=%s json=%s",
                args.suite, len(report.rows), time.monotonic() - started, md, js)
    return 0


if __name__ == "__main__":
    sys.exit(main())
