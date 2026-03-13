"""
Session Repository — database queries for Session aggregate.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from app.database.models import Session


class SessionRepository:
    """Encapsulates all Session-related database queries."""

    def __init__(self, db: DBSession):
        self.db = db

    def get_by_id(self, session_id: str) -> Optional[Session]:
        return self.db.query(Session).filter(Session.id == session_id).first()

    def get_active_for_patient(self, patient_id: str) -> List[Session]:
        return (
            self.db.query(Session)
            .filter(
                Session.patient_id == patient_id,
                Session.status == "active",
            )
            .order_by(Session.started_at.desc())
            .all()
        )

    def list_recent(self, limit: int = 50) -> List[Session]:
        return (
            self.db.query(Session)
            .order_by(Session.started_at.desc())
            .limit(limit)
            .all()
        )

    def create(self, session: Session) -> Session:
        self.db.add(session)
        self.db.flush()
        return session

    def update_status(self, session_id: str, status: str) -> Optional[Session]:
        session = self.get_by_id(session_id)
        if session:
            session.status = status
            self.db.flush()
        return session

    def end_session(self, session_id: str) -> Optional[Session]:
        return self.update_status(session_id, "completed")
