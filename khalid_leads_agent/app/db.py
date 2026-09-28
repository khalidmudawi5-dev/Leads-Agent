"""SQLite engine, session factory, schema init and lightweight migrations."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# (table, column, DDL type) – columns added after the first release go here so
# existing local databases are upgraded in place without losing data.
MIGRATIONS: list[tuple[str, str, str]] = []


class Database:
    """Owns the engine and session factory for one SQLite file."""

    def __init__(self, db_path: Path | str) -> None:
        url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{db_path}"
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if str(db_path) == ":memory:":
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, future=True, **kwargs)
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def init(self) -> None:
        """Create tables and apply pending column migrations (idempotent)."""
        import app.models  # noqa: F401  (register all models)

        Base.metadata.create_all(self.engine)
        insp = inspect(self.engine)
        with self.engine.begin() as conn:
            for table, column, ddl in MIGRATIONS:
                cols = {c["name"] for c in insp.get_columns(table)}
                if column not in cols:
                    log.info("DB migration: add %s.%s", table, column)
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            conn.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # pragma: no cover - trivial
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
