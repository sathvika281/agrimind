from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_url = settings.database_url
_is_sqlite = _url.startswith("sqlite")

engine = create_engine(_url, connect_args={"check_same_thread": False} if _is_sqlite else {})

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate(eng=None) -> list[str]:
    """Minimal dev migration: add columns that exist in the models but not yet in the DB.

    Non-destructive (ALTER TABLE ... ADD COLUMN only). Returns the columns added.
    """
    from sqlalchemy import inspect, text

    eng = eng or engine
    added: list[str] = []
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(eng.dialect)}'
                if col.server_default is not None:
                    ddl += f" DEFAULT '{col.server_default.arg}'"
                    if not col.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(engine)
    migrate()
