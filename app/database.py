from __future__ import annotations

from collections.abc import Generator
from typing import Any

from fastapi import Request

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    else:
        connect_args = {"connect_timeout": 10, "application_name": "smartattend-ai"}
    return create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5 if not database_url.startswith("sqlite") else 1,
        max_overflow=10 if not database_url.startswith("sqlite") else 0,
        connect_args=connect_args,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE", "message": "Database is not configured."})
    db: Session = factory()
    try:
        yield db
    finally:
        db.close()
