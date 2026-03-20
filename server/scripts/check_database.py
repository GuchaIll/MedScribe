#!/usr/bin/env python
"""
Database connection checker.
Run this script to verify database connectivity before running migrations.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.session import check_db_connection
from app.config.settings import settings


def main():
    """Check database connection and print status."""
    print("=" * 60)
    print("DATABASE CONNECTION CHECK")
    print("=" * 60)
    print(f"\nEnvironment: {settings.ENVIRONMENT}")
    print(f"Database URL: {settings.DATABASE_URL}")
    print(f"\nAttempting to connect to database...")

    if check_db_connection():
        print("\n[SUCCESS] Database connection established!")
        print("\nYou can now run:")
        print("  1. python scripts/init_database.py")
        print("  2. python scripts/seed_data.py")
        print("\nOr use Alembic migrations:")
        print("  1. alembic revision --autogenerate -m 'Initial schema'")
        print("  2. alembic upgrade head")
        return 0
    else:
        print("\n[FAILED] Could not connect to database")
        print("\nPlease check:")
        print("  1. Is PostgreSQL running?")
        print("     - Docker: docker-compose up -d db")
        print("     - Local: Check PostgreSQL service status")
        print("  2. Is DATABASE_URL correct in .env?")
        print("     - Current: " + settings.DATABASE_URL)
        print("  3. For quick testing, use SQLite:")
        print("     - Edit .env: DATABASE_URL=sqlite:///./medscribe.db")
        return 1


if __name__ == "__main__":
    sys.exit(main())
