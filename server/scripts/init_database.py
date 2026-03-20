#!/usr/bin/env python
"""
Initialize database with tables (development only).
This creates all tables without using migrations.
For production, use Alembic migrations instead.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.session import init_db, check_db_connection


def main():
    """Initialize the database."""
    print("=" * 60)
    print("DATABASE INITIALIZATION (Development Only)")
    print("=" * 60)

    # Check connection first
    print("\n1. Checking database connection...")
    if not check_db_connection():
        print("[ERROR] Cannot connect to database. Please check your configuration.")
        print("\nMake sure:")
        print("  - PostgreSQL is running (docker-compose up -d db)")
        print("  - DATABASE_URL is correct in .env")
        return 1

    print("[OK] Database connection successful")

    # Create tables
    print("\n2. Creating database tables...")
    try:
        init_db()
        print("[OK] All tables created successfully!")

        print("\n" + "=" * 60)
        print("DATABASE READY!")
        print("=" * 60)
        print("\nCreated tables:")
        print("  - patients")
        print("  - users")
        print("  - sessions")
        print("  - medical_records")
        print("  - audit_logs")
        print("  - workflow_checkpoints")

        print("\nNext steps:")
        print("  1. Run: python scripts/seed_data.py (to add demo users)")
        print("  2. Start the API: python app/main.py")

        return 0

    except Exception as e:
        print(f"[ERROR] Error creating tables: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
