#!/usr/bin/env python3
"""
Paired cross-session isolation probe (#91, SDD T0 exit test).

Measures /transcribe and /assistant latency for two "other" sessions while
idle, and again while a third session ingests an 8-page image-only PDF
(real OCR, not a text layer). Run it against main and against the branch on
the same machine and compare.

Load is open-loop: requests fire on a fixed schedule whether or not earlier
ones returned, so an event-loop stall shows up as latency, not as fewer
requests.

Usage:
    python scripts/probe_isolation.py --base-url http://localhost:3091 \\
        --label branch --out docs/benchmarks/t0-isolation/branch.json

Exit criterion (stated in the report, not loosened):
    ingesting p99 /transcribe <= 1.2 x idle p99
    ingesting p95 /assistant  <= 1.2 x idle p95

Needs: httpx, Pillow. The PDF is built from the repo's sample OCR images
(server/tests/ocr_examples/img-sample-*.jpg, Doctor's Handwriting.jpg), not PHI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO / "server" / "tests" / "ocr_examples"
THRESHOLD = 1.2


def make_probe_pdf(dest: Path, pages: int = 8) -> Path:
    """Write an image-only PDF of ``pages`` pages, cycling the sample images."""
    from PIL import Image

    sources = sorted(p for p in FIXTURE_DIR.glob("*.jp*g"))
    if not sources:
        raise SystemExit(f"no sample images under {FIXTURE_DIR}")
    images = [Image.open(sources[i % len(sources)]).convert("RGB") for i in range(pages)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(dest, save_all=True, append_images=images[1:], resolution=150)
    return dest


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = min(len(s) - 1, max(0, round(q / 100 * (len(s) - 1))))
    return round(s[k], 1)


class Recorder:
    def __init__(self) -> None:
        self.lat: list[float] = []
        self.errors: Counter = Counter()

    def summary(self) -> dict:
        return {
            "n": len(self.lat),
            "p50_ms": pct(self.lat, 50),
            "p95_ms": pct(self.lat, 95),
            "p99_ms": pct(self.lat, 99),
            "max_ms": round(max(self.lat), 1) if self.lat else None,
            "stdev_ms": round(statistics.pstdev(self.lat), 1) if len(self.lat) > 1 else None,
            "errors": dict(self.errors),
        }


async def _timed(client: httpx.AsyncClient, rec: Recorder, method: str, url: str, **kw) -> None:
    t0 = time.perf_counter()
    try:
        resp = await client.request(method, url, **kw)
        rec.lat.append((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 400:
            rec.errors[str(resp.status_code)] += 1
    except httpx.HTTPError as exc:
        rec.lat.append((time.perf_counter() - t0) * 1000)
        rec.errors[type(exc).__name__] += 1


async def open_loop(rps: float, duration_s: float, fire) -> None:
    interval = 1.0 / rps
    start = time.perf_counter()
    tasks = []
    i = 0
    while True:
        due = start + i * interval
        if due - start >= duration_s:
            break
        await asyncio.sleep(max(0.0, due - time.perf_counter()))
        tasks.append(asyncio.create_task(fire()))
        i += 1
    await asyncio.gather(*tasks)


async def ingest_loop(client: httpx.AsyncClient, base: str, sid: str, pdf: Path,
                      stop: asyncio.Event, out: dict) -> None:
    data = pdf.read_bytes()
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"{base}/api/session/{sid}/upload",
                files={"files": (pdf.name, data, "application/pdf")},
                timeout=900,
            )
            out["uploads"].append({
                "status": resp.status_code,
                "ms": round((time.perf_counter() - t0) * 1000),
                "offload_header": resp.headers.get("x-medscribe-offload"),
                "file_errors": [f.get("error") for f in resp.json().get("files", []) if f.get("error")]
                if resp.headers.get("content-type", "").startswith("application/json") else None,
            })
        except httpx.HTTPError as exc:
            out["uploads"].append({"status": type(exc).__name__,
                                   "ms": round((time.perf_counter() - t0) * 1000)})


async def phase(client: httpx.AsyncClient, base: str, sids: dict, duration_s: float,
                pdf: Path | None, args) -> dict:
    tr, asst = Recorder(), Recorder()
    ingest = {"uploads": []}
    stop = asyncio.Event()

    async def fire_transcribe():
        await _timed(client, tr, "POST", f"{base}/api/session/{sids['a']}/transcribe",
                     json={"text": "Patient reports mild headache since this morning.", "speaker": "Patient"})

    async def fire_assistant():
        await _timed(client, asst, "POST", f"{base}/api/session/{sids['b']}/assistant",
                     json={"patient_id": args.patient_id, "question": args.question})

    ingest_task = None
    if pdf is not None:
        ingest_task = asyncio.create_task(ingest_loop(client, base, sids["c"], pdf, stop, ingest))
        await asyncio.sleep(args.ingest_lead_s)  # let OCR get going before measuring

    await asyncio.gather(
        open_loop(args.transcribe_rps, duration_s, fire_transcribe),
        open_loop(args.assistant_rps, duration_s, fire_assistant),
    )
    stop.set()
    if ingest_task is not None:
        # Do not wait out a long upload; record what finished.
        try:
            await asyncio.wait_for(asyncio.shield(ingest_task), timeout=1)
        except asyncio.TimeoutError:
            pass
    result = {"transcribe": tr.summary(), "assistant": asst.summary()}
    if pdf is not None:
        result["ingest"] = {
            "uploads_completed": len(ingest["uploads"]),
            "uploads": ingest["uploads"],
            "offload_headers": dict(Counter(u.get("offload_header") for u in ingest["uploads"])),
        }
    if ingest_task is not None and not ingest_task.done():
        result.setdefault("ingest", {})["upload_in_flight_at_end"] = True
        await ingest_task  # keep sessions clean for the next run
    return result


def verdict(idle: dict, ing: dict) -> dict:
    def ratio(metric, key):
        a, b = idle[metric][key], ing[metric][key]
        return round(b / a, 2) if a and b is not None else None

    t = ratio("transcribe", "p99_ms")
    a = ratio("assistant", "p95_ms")
    return {
        "threshold": THRESHOLD,
        "transcribe_p99_ratio": t,
        "assistant_p95_ratio": a,
        "pass": bool(t is not None and a is not None and t <= THRESHOLD and a <= THRESHOLD),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--label", required=True, help="e.g. main or branch")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--duration-s", type=float, default=60)
    ap.add_argument("--transcribe-rps", type=float, default=2)
    ap.add_argument("--assistant-rps", type=float, default=1)
    ap.add_argument("--ingest-lead-s", type=float, default=2)
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--patient-id", default="probe-patient")
    ap.add_argument("--question", default="What medications is the patient currently taking?")
    args = ap.parse_args()

    for name, val in (("duration-s", args.duration_s), ("transcribe-rps", args.transcribe_rps),
                      ("assistant-rps", args.assistant_rps), ("pages", args.pages)):
        if val <= 0:
            raise SystemExit(f"--{name} must be > 0, got {val}")

    base = args.base_url.rstrip("/")
    pdf = make_probe_pdf(Path(tempfile.gettempdir()) / f"medscribe-probe-{args.pages}p.pdf", args.pages)

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            (await client.get(f"{base}/")).raise_for_status()
        except httpx.HTTPError as exc:
            raise SystemExit(f"API not reachable at {base}: {exc}")
        sids = {}
        for k in ("a", "b", "c"):
            r = await client.post(f"{base}/api/session/start")
            r.raise_for_status()
            sids[k] = r.json()["session_id"]
        # Warm-up: first /assistant loads the embedding model, first upload loads OCR.
        await client.post(f"{base}/api/session/{sids['b']}/assistant",
                          json={"patient_id": args.patient_id, "question": args.question})
        await client.post(f"{base}/api/session/{sids['c']}/upload",
                          files={"files": (pdf.name, pdf.read_bytes(), "application/pdf")}, timeout=900)

        print(f"[{args.label}] phase 1: idle {args.duration_s:.0f}s", file=sys.stderr)
        idle = await phase(client, base, sids, args.duration_s, None, args)
        print(f"[{args.label}] phase 2: ingesting {args.pages}-page PDF {args.duration_s:.0f}s", file=sys.stderr)
        ing = await phase(client, base, sids, args.duration_s, pdf, args)

    report = {
        "label": args.label,
        "base_url": base,
        "config": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "idle": idle,
        "ingesting": ing,
        "verdict": verdict(idle, ing),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["verdict"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
