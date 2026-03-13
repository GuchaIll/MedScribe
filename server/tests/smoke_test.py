"""
Smoke test: exercises the full 17-node LangGraph pipeline against
the live PostgreSQL + pgvector database.

Usage:
    cd server
    python tests/smoke_test.py

Requires:
    - PostgreSQL + pgvector container running (docker compose up -d db)
    - GROQ_API_KEY set in .env for LLM calls
    - BioLord-2023-M will be downloaded on first run (~400 MB)
"""

import sys
import os
import json
import traceback
from pathlib import Path

from dotenv import load_dotenv

# Load env (same order as main.py) — script lives in tests/, server/ is parent
_SERVER_DIR = Path(__file__).parent.parent
load_dotenv(dotenv_path=_SERVER_DIR.parent / ".env")
load_dotenv(dotenv_path=_SERVER_DIR / ".env", override=True)

from app.config.settings import settings

# ── Sample transcript segments (mock medical encounter) ─────────────────────
SAMPLE_SEGMENTS = [
    {
        "start": 0.0, "end": 5.0,
        "speaker": "Clinician", "raw_text": "Good morning, how are you feeling today?",
        "confidence": "0.95",
    },
    {
        "start": 5.0, "end": 12.0,
        "speaker": "Patient", "raw_text": "Not great doctor. I've been having a persistent cough for about two weeks now and some chest tightness.",
        "confidence": "0.92",
    },
    {
        "start": 12.0, "end": 20.0,
        "speaker": "Clinician", "raw_text": "I see. Any fever, shortness of breath, or wheezing?",
        "confidence": "0.96",
    },
    {
        "start": 20.0, "end": 30.0,
        "speaker": "Patient", "raw_text": "Yes, I've had a low grade fever around 100.2 and some shortness of breath especially when climbing stairs.",
        "confidence": "0.91",
    },
    {
        "start": 30.0, "end": 42.0,
        "speaker": "Clinician", "raw_text": "Are you currently on any medications? And do you have any known allergies?",
        "confidence": "0.97",
    },
    {
        "start": 42.0, "end": 55.0,
        "speaker": "Patient", "raw_text": "I take lisinopril 10 milligrams daily for blood pressure and metformin 500 milligrams twice daily for diabetes. I'm allergic to penicillin — gives me hives.",
        "confidence": "0.89",
    },
    {
        "start": 55.0, "end": 68.0,
        "speaker": "Clinician", "raw_text": "Based on your symptoms, I'm going to order a chest x-ray and prescribe azithromycin 250 milligrams for a possible upper respiratory infection. Let's also check your blood pressure today.",
        "confidence": "0.93",
    },
    {
        "start": 68.0, "end": 75.0,
        "speaker": "Patient", "raw_text": "Sounds good, doctor. How long should I take the azithromycin?",
        "confidence": "0.94",
    },
    {
        "start": 75.0, "end": 85.0,
        "speaker": "Clinician", "raw_text": "Five days — take one pill daily. Your blood pressure is 138 over 88. That's slightly elevated, we should keep monitoring it.",
        "confidence": "0.95",
    },
]


def main():
    print("=" * 70)
    print("  MedScribe — Smoke Test (17-node LangGraph Pipeline)")
    print("=" * 70)

    # ── Step 1: Verify database ──────────────────────────────────────────
    print("\n[1/5] Checking database connection...")
    try:
        from app.database.session import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            r = conn.execute(text("SELECT 1"))
            assert r.fetchone()[0] == 1
            r = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
            assert r.fetchone() is not None, "pgvector extension not found!"
        print("      ✓ PostgreSQL + pgvector connected")
    except Exception as e:
        print(f"      ✗ Database error: {e}")
        sys.exit(1)

    # ── Step 2: Verify GROQ_API_KEY ──────────────────────────────────────
    print("\n[2/6] Checking API keys...")
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key or groq_key.startswith("your_"):
        print("      ✗ GROQ_API_KEY not set — LLM calls will fail")
        print("        Set it in server/.env or root .env")
        sys.exit(1)
    print(f"      ✓ GROQ_API_KEY present ({groq_key[:8]}...)")

    # ── Step 2b: Seed required DB rows (User, Patient, Session) ─────────
    print("\n[3/6] Seeding test data (User, Patient, Session)...")
    try:
        from app.database.session import SessionLocal
        from app.database.models import User, Patient, Session as SessionModel
        from datetime import datetime

        seed_db = SessionLocal()

        # Ensure User exists
        if not seed_db.get(User, "doctor-smoke-001"):
            seed_db.add(User(
                id="doctor-smoke-001",
                username="smoke_doctor",
                email="smoke_doctor@test.local",
                hashed_password="not-a-real-hash",
                full_name="Dr. Smoke Test",
                role="doctor",
            ))
            seed_db.flush()

        # Ensure Patient exists
        if not seed_db.get(Patient, "patient-smoke-001"):
            seed_db.add(Patient(
                id="patient-smoke-001",
                mrn="MRN-SMOKE-001",
                full_name="Jane Smoketest",
                dob=datetime(1985, 6, 15),
                sex="female",
                created_by="doctor-smoke-001",
            ))
            seed_db.flush()

        # Ensure Session exists
        if not seed_db.get(SessionModel, "smoke-test-001"):
            seed_db.add(SessionModel(
                id="smoke-test-001",
                patient_id="patient-smoke-001",
                doctor_id="doctor-smoke-001",
                status="active",
                visit_type="follow_up",
            ))
            seed_db.flush()

        seed_db.commit()
        seed_db.close()
        print("      ✓ Test data seeded (User + Patient + Session)")
    except Exception as e:
        print(f"      ✗ Seed error: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── Step 3: Build workflow engine ────────────────────────────────────
    print("\n[4/6] Building WorkflowEngine with DB session...")
    try:
        from app.core.workflow_engine import WorkflowEngine

        db = SessionLocal()
        engine_wf = WorkflowEngine(
            enable_checkpointing=True,
            enable_interrupts=False,
            db_session=db,
        )
        print("      ✓ WorkflowEngine built (17-node graph)")
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── Step 5: Execute pipeline ─────────────────────────────────────────
    print("\n[5/6] Executing pipeline with sample transcript...")
    print(f"      ({len(SAMPLE_SEGMENTS)} segments, ~85s encounter)")
    try:
        state = engine_wf.create_initial_state(
            session_id="smoke-test-001",
            patient_id="patient-smoke-001",
            doctor_id="doctor-smoke-001",
            inputs={"segments": SAMPLE_SEGMENTS},
        )
        # Populate new_segments for pipeline
        state["new_segments"] = SAMPLE_SEGMENTS

        final = engine_wf.execute(state)
        print("      ✓ Pipeline completed")
    except Exception as e:
        print(f"      ✗ Pipeline error: {e}")
        traceback.print_exc()
        db.close()
        sys.exit(1)

    # ── Step 6: Inspect results ──────────────────────────────────────────
    print("\n[6/6] Results:")
    print(f"      Session:       {final.get('session_id')}")
    print(f"      Message:       {final.get('message')}")
    print(f"      Flags:         {json.dumps(final.get('flags', {}), indent=8)}")

    sr = final.get("structured_record", {})
    if sr:
        print("\n      Structured Record:")
        for section, data in sr.items():
            if data:
                preview = json.dumps(data, indent=2)[:200]
                print(f"        {section}: {preview}")
    else:
        print("      Structured Record: (empty)")

    note = final.get("clinical_note")
    if note:
        print(f"\n      Clinical Note ({len(note)} chars):")
        for line in note.split("\n")[:10]:
            print(f"        {line}")
        if note.count("\n") > 10:
            print("        ... (truncated)")
    else:
        print("      Clinical Note: (none)")

    vr = final.get("validation_report")
    if vr:
        print(f"\n      Validation Report:")
        print(f"        Valid:  {vr.get('valid')}")
        print(f"        Issues: {len(vr.get('issues', []))}")

    sug = final.get("clinical_suggestions")
    if sug:
        print(f"\n      Clinical Suggestions:")
        for k, v in sug.items():
            print(f"        {k}: {v}")

    # ── Check DB persistence ─────────────────────────────────────────────
    print("\n      Database persistence:")
    try:
        from sqlalchemy import text as sa_text
        with engine.connect() as conn:
            for tbl in ("medical_records", "clinical_embeddings", "chunk_embeddings", "audit_logs"):
                r = conn.execute(sa_text(f"SELECT count(*) FROM {tbl}"))
                count = r.fetchone()[0]
                print(f"        {tbl}: {count} rows")
    except Exception as e:
        print(f"        ✗ Error checking DB: {e}")

    db.close()
    print("\n" + "=" * 70)
    print("  Smoke test complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
