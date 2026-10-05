"""Operator tools: safe migration, backup and restore of the SQLite database.

  python -m app.cli migrate --db PATH [--backup-dir DIR]
  python -m app.cli backup  --db PATH [--uploads DIR] --out DIR
  python -m app.cli restore --backup FILE --db PATH --yes

`migrate` never edits a database it has not first backed up and verified. It applies only the additive migration
(new nullable columns, new tables), then checks that every existing value is unchanged; on ANY mismatch it puts the
backup back and exits non-zero. It never prints secrets and never touches uploads.
"""
import argparse
import hashlib
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

CORE_TABLES = ("users", "farms", "analyses")


class CliError(Exception):
    pass


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(path))


def integrity_ok(path: Path) -> bool:
    con = _connect(path)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


def _tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def snapshot(path: Path) -> dict:
    """Row counts and a checksum over every column that exists NOW, per table (the 'before' picture)."""
    con = _connect(path)
    try:
        out = {}
        for t in _tables(con):
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            h = hashlib.sha256()
            n = 0
            for row in con.execute(f'SELECT {",".join(chr(34) + c + chr(34) for c in cols)} FROM "{t}" ORDER BY rowid'):
                h.update(repr(row).encode("utf-8"))
                n += 1
            out[t] = {"rows": n, "cols": cols, "sha": h.hexdigest()}
        return out
    finally:
        con.close()


def _same_on_old_columns(before: dict, path: Path) -> list[str]:
    """Differences between the 'before' snapshot and the database now, looking ONLY at the old columns."""
    con = _connect(path)
    bad: list[str] = []
    try:
        for t, b in before.items():
            if t not in _tables(con):
                bad.append(f"table {t} disappeared")
                continue
            h = hashlib.sha256()
            n = 0
            for row in con.execute(f'SELECT {",".join(chr(34) + c + chr(34) for c in b["cols"])} FROM "{t}" ORDER BY rowid'):
                h.update(repr(row).encode("utf-8"))
                n += 1
            if n != b["rows"]:
                bad.append(f"{t}: {b['rows']} rows became {n}")
            elif h.hexdigest() != b["sha"]:
                bad.append(f"{t}: existing values changed")
    finally:
        con.close()
    return bad


def backup_db(db: Path, out_dir: Path, label: str = "backup") -> Path:
    """A consistent copy via SQLite's online backup API, verified before it is trusted."""
    if not db.is_file():
        raise CliError(f"Database file not found: {db}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = out_dir / f"{db.stem}.{label}.{stamp}.db"
    src, dst = _connect(db), sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if not integrity_ok(dest):
        dest.unlink(missing_ok=True)
        raise CliError("The backup failed its integrity check, so nothing was changed.")
    if snapshot(dest) != snapshot(db):
        dest.unlink(missing_ok=True)
        raise CliError("The backup does not match the database, so nothing was changed.")
    return dest


def migrate_db(db: Path, backup_dir: Path | None = None) -> dict:
    """Backup -> additive migration -> verify -> (rollback on any problem). Returns a report."""
    from sqlalchemy import create_engine

    from . import models  # noqa: F401  (registers the tables)
    from .database import Base, migrate

    if not db.is_file():
        raise CliError(f"Database file not found: {db}")
    if not integrity_ok(db):
        raise CliError("The database fails SQLite's integrity check; not touching it.")
    backup = backup_db(db, backup_dir or db.parent / "backups", "pre-migration")
    before = snapshot(db)
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        Base.metadata.create_all(engine)  # new tables only; never alters existing ones
        added = migrate(engine)  # ALTER TABLE ... ADD COLUMN (nullable) only
    except Exception as e:  # noqa: BLE001
        engine.dispose()
        shutil.copyfile(backup, db)
        raise CliError(f"Migration failed ({type(e).__name__}); the backup was restored.") from None
    finally:
        engine.dispose()
    problems = _same_on_old_columns(before, db)
    if not integrity_ok(db):
        problems.append("integrity check failed after migration")
    con = _connect(db)
    try:
        if con.execute("PRAGMA foreign_key_check").fetchall():
            problems.append("foreign key check failed after migration")
    finally:
        con.close()
    if problems:
        shutil.copyfile(backup, db)
        raise CliError("Verification failed, the backup was restored: " + "; ".join(problems))
    after = snapshot(db)
    return {
        "backup": str(backup),
        "added_columns": added,
        "new_tables": sorted(set(after) - set(before)),
        "rows": {t: before[t]["rows"] for t in CORE_TABLES if t in before},
        "unchanged": True,
    }


def backup_all(db: Path, uploads: Path | None, out_dir: Path) -> Path:
    """One archive: a verified database copy plus the uploads folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    copy = backup_db(db, out_dir, "snapshot")
    archive = out_dir / (copy.stem + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(copy, arcname="database.db")
        if uploads and uploads.is_dir():
            tar.add(uploads, arcname="uploads")
    copy.unlink(missing_ok=True)
    return archive


def restore_db(backup: Path, db: Path) -> None:
    """Put a verified database backup in place (the current file is kept next to it as .before-restore)."""
    if not backup.is_file():
        raise CliError(f"Backup file not found: {backup}")
    if not integrity_ok(backup):
        raise CliError("That backup fails SQLite's integrity check; not restoring it.")
    if db.exists():
        shutil.copyfile(db, db.with_suffix(db.suffix + ".before-restore"))
    shutil.copyfile(backup, db)
    if not integrity_ok(db):
        raise CliError("The restored database failed its integrity check.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate")
    m.add_argument("--db", required=True)
    m.add_argument("--backup-dir")
    b = sub.add_parser("backup")
    b.add_argument("--db", required=True)
    b.add_argument("--uploads")
    b.add_argument("--out", required=True)
    r = sub.add_parser("restore")
    r.add_argument("--backup", required=True)
    r.add_argument("--db", required=True)
    r.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "migrate":
            rep = migrate_db(Path(a.db), Path(a.backup_dir) if a.backup_dir else None)
            print("Migration finished and verified.")
            print(f"  backup:        {rep['backup']}")
            print(f"  added columns: {', '.join(rep['added_columns']) or 'none (already up to date)'}")
            print(f"  new tables:    {', '.join(rep['new_tables']) or 'none'}")
            print(f"  rows:          {rep['rows']} (unchanged)")
        elif a.cmd == "backup":
            print(f"Backup written: {backup_all(Path(a.db), Path(a.uploads) if a.uploads else None, Path(a.out))}")
        else:
            if not a.yes:
                raise CliError("Restore replaces the current database. Re-run with --yes to confirm.")
            restore_db(Path(a.backup), Path(a.db))
            print(f"Restored {a.backup} -> {a.db}")
    except CliError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
