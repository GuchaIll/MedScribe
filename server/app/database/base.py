"""
SQLAlchemy declarative base and database utilities.
"""

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import DeclarativeBase


# SQLAlchemy 2.0 style declarative base
class Base(DeclarativeBase):
    """Base class for all database models."""
    pass
