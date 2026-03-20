#!/usr/bin/env python
"""
Seed database with demo data for testing.
Creates demo users and sample patient data.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import uuid

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.session import SessionLocal
from app.database.models import User, Patient, UserRole
from app.auth.oauth2 import get_password_hash


def seed_users(db):
    """Create demo users."""
    print("\n[INFO] Creating demo users...")

    users = [
        {
            "id": "user_001",
            "username": "demo_doctor",
            "email": "doctor@medscribe.com",
            "full_name": "Dr. Jane Smith",
            "password": "demo123",
            "role": UserRole.DOCTOR
        },
        {
            "id": "user_002",
            "username": "demo_nurse",
            "email": "nurse@medscribe.com",
            "full_name": "Sarah Johnson",
            "password": "demo123",
            "role": UserRole.NURSE
        },
        {
            "id": "user_003",
            "username": "demo_admin",
            "email": "admin@medscribe.com",
            "full_name": "Admin User",
            "password": "demo123",
            "role": UserRole.ADMIN
        }
    ]

    created_count = 0
    for user_data in users:
        # Check if user exists
        existing = db.query(User).filter_by(username=user_data["username"]).first()
        if existing:
            print(f"  [WARN] User '{user_data['username']}' already exists, skipping...")
            continue

        user = User(
            id=user_data["id"],
            username=user_data["username"],
            email=user_data["email"],
            full_name=user_data["full_name"],
            hashed_password=get_password_hash(user_data["password"]),
            role=user_data["role"],
            is_active=True
        )
        db.add(user)
        created_count += 1
        print(f"  [OK] Created user: {user_data['username']} ({user_data['role'].value})")

    print(f"\n[OK] Created {created_count} new users")


def seed_patients(db):
    """Create demo patients."""
    print("\n[INFO] Creating demo patients...")

    patients = [
        {
            "id": "patient_001",
            "mrn": "MRN001234",
            "full_name": "John Doe",
            "dob": datetime(1980, 5, 15),
            "age": 44,
            "sex": "Male"
        },
        {
            "id": "patient_002",
            "mrn": "MRN002345",
            "full_name": "Jane Williams",
            "dob": datetime(1975, 8, 22),
            "age": 49,
            "sex": "Female"
        },
        {
            "id": "patient_003",
            "mrn": "MRN003456",
            "full_name": "Robert Brown",
            "dob": datetime(1990, 3, 10),
            "age": 34,
            "sex": "Male"
        }
    ]

    created_count = 0
    for patient_data in patients:
        # Check if patient exists
        existing = db.query(Patient).filter_by(mrn=patient_data["mrn"]).first()
        if existing:
            print(f"  [WARN] Patient '{patient_data['mrn']}' already exists, skipping...")
            continue

        patient = Patient(
            id=patient_data["id"],
            mrn=patient_data["mrn"],
            full_name=patient_data["full_name"],
            dob=patient_data["dob"],
            age=patient_data["age"],
            sex=patient_data["sex"],
            created_by="user_001",
            is_active=True
        )
        db.add(patient)
        created_count += 1
        print(f"  [OK] Created patient: {patient_data['full_name']} (MRN: {patient_data['mrn']})")

    print(f"\n[OK] Created {created_count} new patients")


def main():
    """Seed the database with demo data."""
    print("=" * 60)
    print("DATABASE SEEDING")
    print("=" * 60)

    db = SessionLocal()
    try:
        seed_users(db)
        seed_patients(db)
        db.commit()

        print("\n" + "=" * 60)
        print("SEEDING COMPLETE!")
        print("=" * 60)

        print("\n[AUTH] Demo Login Credentials:")
        print("\n  Doctor:")
        print("    Username: demo_doctor")
        print("    Password: demo123")
        print("\n  Nurse:")
        print("    Username: demo_nurse")
        print("    Password: demo123")
        print("\n  Admin:")
        print("    Username: demo_admin")
        print("    Password: demo123")

        print("\n[DATA] Demo Patients:")
        print("  - John Doe (MRN: MRN001234)")
        print("  - Jane Williams (MRN: MRN002345)")
        print("  - Robert Brown (MRN: MRN003456)")

        return 0

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Error seeding database: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
