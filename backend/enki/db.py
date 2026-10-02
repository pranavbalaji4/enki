from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})
    if is_sqlite:
        # The background worker writes while requests read; WAL + busy timeout avoids lock errors.
        @event.listens_for(engine, "connect")
        def _pragmas(conn, _record):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def configure(url: str) -> None:
    """Rebind to another database (used by tests)."""
    global engine
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all never alters existing tables; add new nullable columns so older dev databases keep working.
    (Stand-in until the project adopts Alembic.)"""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
