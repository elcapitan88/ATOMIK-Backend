# app/database.py
"""
Database module that re-exports Base and other database components.
This provides backward compatibility for models that import from app.database.
"""

from .db.base_class import Base
from .db.base import SessionLocal, engine, get_db

__all__ = ["Base", "SessionLocal", "engine", "get_db"]