"""Database engine and session factory."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

from llmcouncil.persistence.models import Base


def build_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(db_path: Path) -> sessionmaker[Session]:
    """Create all tables and return a session factory. DB file is created mode 0600."""
    import os

    engine = build_engine(db_path)
    Base.metadata.create_all(engine)
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass
    return sessionmaker(bind=engine)
