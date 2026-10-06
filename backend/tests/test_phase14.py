"""Deployment readiness: production safety checks, the single-origin production entry, account export/delete,
and the migration/backup tools. Scratch databases only; never the live one."""
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import asgi_prod, cli, production

GOOD = {"JWT_SECRET": "k" * 5 + "Qz7vN2pLw9RtYb4HcX8mUd3GfJ6sAe1KoWi0VnBq5ZyTrEu", "COOKIE_SECURE": "true", "CORS_ORIGINS": "", "AI_PROVIDER": "gemini", "GEMINI_API_KEY": "present-not-printed"}


# ---------------- production settings ----------------
def test_a_safe_production_environment_has_no_problems():
    assert production.problems(GOOD) == []


@pytest.mark.parametrize(
    "change, fragment",
    [
        ({"JWT_SECRET": "short"}, "JWT_SECRET"),
        ({"JWT_SECRET": "change-me-" * 6}, "placeholder"),
        ({"COOKIE_SECURE": "false"}, "COOKIE_SECURE"),
        ({"COOKIE_SECURE": ""}, "COOKIE_SECURE"),
        ({"CORS_ORIGINS": "http://example.com"}, "CORS_ORIGINS"),
        ({"CORS_ORIGINS": "*"}, "CORS_ORIGINS"),
        ({"CORS_ORIGINS": "https://ok.example.com,http://bad.example.com"}, "CORS_ORIGINS"),
        ({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": ""}, "GEMINI_API_KEY"),
        ({"AI_PROVIDER": "demo"}, "demo"),
        ({"AI_PROVIDER": "other"}, "AI_PROVIDER"),
        ({"RATE_LIMIT_ENABLED": "false"}, "RATE_LIMIT"),
    ],
)
def test_each_unsafe_setting_is_reported(change, fragment):
    got = production.problems({**GOOD, **change})
    assert got and any(fragment.lower() in g.lower() for g in got), got


def test_demo_is_allowed_in_production_only_on_purpose():
    assert production.problems({**GOOD, "AI_PROVIDER": "demo", "ALLOW_DEMO_IN_PRODUCTION": "true"}) == []
    assert production.problems({**GOOD, "CORS_ORIGINS": "https://app.example.com"}) == []


def test_startup_refuses_in_production_without_leaking_secrets(monkeypatch):
    for k, v in {**GOOD, "JWT_SECRET": "short-secret-value-123", "APP_ENV": "production", "GEMINI_API_KEY": ""}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(RuntimeError) as e:
        production.validate_production()
    msg = str(e.value)
    assert "Refusing to start in production" in msg and "short-secret-value-123" not in msg


def test_validation_is_a_no_op_outside_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    production.validate_production()


# ---------------- the single-origin production entry ----------------
@pytest.fixture()
def site(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>AgriMind</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log('x')", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    monkeypatch.setattr(asgi_prod, "DIST", dist.resolve())
    from app.database import Base, engine

    Base.metadata.drop_all(engine)
    with TestClient(asgi_prod.app) as c:
        yield c


def test_site_serves_index_assets_and_spa_routes_with_the_right_cache_and_security_headers(site):
    r = site.get("/")
    assert r.status_code == 200 and "AgriMind" in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert "default-src 'self'" in r.headers["content-security-policy"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    a = site.get("/assets/app-abc123.js")
    assert a.status_code == 200 and "immutable" in a.headers["cache-control"]
    assert "AgriMind" in site.get("/farms/12").text and "AgriMind" in site.get("/analyses/5").text  # app routes -> the app
    assert site.get("/robots.txt").text.startswith("User-agent")
    assert site.get("/missing.js").status_code == 404


def test_api_lives_under_api_and_errors_stay_json(site):
    assert site.get("/health").json() == {"status": "ok"}
    assert site.get("/api/health").json() == {"status": "ok"}
    me = site.get("/api/auth/me")
    assert me.status_code == 401 and me.headers["content-type"].startswith("application/json")
    nope = site.get("/api/nothing/here")
    assert nope.status_code == 404 and nope.headers["content-type"].startswith("application/json") and nope.json()["code"] == "not_found"
    bad = site.post("/somewhere", json={})
    assert bad.status_code == 404 and bad.json()["code"] == "not_found"


def test_files_outside_the_build_folder_are_never_served(site):
    for path in ("/assets/../../app/config.py", "/..%2f..%2fapp%2fconfig.py", "/%2e%2e/%2e%2e/app/config.py", "/assets/..%5c..%5capp%5cconfig.py"):
        r = site.get(path)
        assert "class Settings" not in r.text and "jwt_secret" not in r.text, path


def test_register_and_login_work_through_the_api_prefix_and_the_cookie_can_be_secure(site, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    r = site.post("/api/auth/register", json={"email": "prod@example.com", "password": "password123"})
    assert r.status_code == 201
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "max-age=31536000" in r.headers["strict-transport-security"]  # HSTS only when the cookie is secure
    assert "strict-transport-security" in site.get("/").headers


def test_no_hsts_when_cookies_are_not_secure(site, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    assert "strict-transport-security" not in site.get("/").headers
    assert "strict-transport-security" not in site.get("/api/health").headers


def test_the_upload_size_guard_still_applies_behind_the_prefix(site):
    site.post("/api/auth/register", json={"email": "big@example.com", "password": "password123"})
    fid = site.post("/api/farms", json={"name": "F"}).json()["id"]
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (3 * 1024 * 1024)  # MAX_IMAGE_MB=1 in tests
    r = site.post("/api/analyses", data={"farm_id": str(fid), "crop": "Rice", "symptoms": "x"}, files={"image": ("a.png", big, "image/png")})
    assert r.status_code == 413 and r.json()["code"] == "image_too_large"


def test_missing_build_is_a_clear_503_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(asgi_prod, "DIST", (tmp_path / "nope").resolve())
    with TestClient(asgi_prod.app) as c:
        assert c.get("/").status_code == 503 and c.get("/health").json() == {"status": "ok"}


# ---------------- account export and deletion ----------------
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _mk(register, email):
    c = register(email)
    fid = c.post("/farms", json={"name": f"{email}-farm", "location": "Guntur", "primary_crop": "Tomato", "notes": "PRIVATE"}).json()["id"]
    chk = c.post("/analyses", data={"farm_id": str(fid), "crop": "Tomato", "symptoms": "yellow leaves"}, files={"image": ("a.png", PNG, "image/png")}).json()
    c.post(f"/farms/{fid}/events", json={"kind": "sprayed", "note": "morning"})
    return c, fid, chk


def _rows(table):
    from app.database import SessionLocal
    from sqlalchemy import text

    with SessionLocal() as db:
        return db.execute(text(f"select count(*) from {table}")).scalar()


def test_export_contains_only_my_data_and_no_secrets(register, client):
    a, fa, ca = _mk(register, "a@example.com")
    b, fb, cb = _mk(register, "b@example.com")
    r = a.get("/auth/me/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    j = r.json()
    assert j["user"]["email"] == "a@example.com" and [f["id"] for f in j["farms"]] == [fa]
    assert [c["id"] for c in j["checks"]] == [ca["id"]] and len(j["diary"]) == 1 and j["diary"][0]["farm_id"] == fa
    text = r.text
    for banned in ("b@example.com", "b@example.com-farm", "$2b$", "password_hash", "image_path"):
        assert banned not in text, banned
    assert "PRIVATE" in text  # the farmer's own profile notes are theirs to download
    assert client.get("/auth/me/export").status_code == 401


def test_delete_needs_the_password_and_changes_nothing_when_it_is_wrong(register):
    a, fa, ca = _mk(register, "a@example.com")
    before = (_rows("users"), _rows("farms"), _rows("analyses"), _rows("farm_events"))
    r = a.request("DELETE", "/auth/me", json={"password": "wrong-password"})
    assert r.status_code == 403 and "Incorrect password" in r.json()["detail"]
    assert (_rows("users"), _rows("farms"), _rows("analyses"), _rows("farm_events")) == before
    assert a.get("/auth/me").status_code == 200
    assert a.request("DELETE", "/auth/me", json={}).status_code == 422
    assert a.request("DELETE", "/auth/me", json={"password": "p" * 201}).status_code == 422


def test_delete_removes_everything_of_mine_including_photos_and_nothing_of_anyone_else(register, client):
    from app.config import settings

    a, fa, ca = _mk(register, "a@example.com")
    b, fb, cb = _mk(register, "b@example.com")
    files_before = set(os.listdir(settings.uploads_dir))
    assert len(files_before) == 2
    r = a.request("DELETE", "/auth/me", json={"password": "password123"})
    assert r.status_code == 204
    assert "agrimind_token" in r.headers.get("set-cookie", "") and ("max-age=0" in r.headers["set-cookie"].lower() or "expires" in r.headers["set-cookie"].lower())
    assert (_rows("users"), _rows("farms"), _rows("analyses"), _rows("farm_events")) == (1, 1, 1, 1)  # only B's rows remain
    assert len(set(os.listdir(settings.uploads_dir))) == 1  # A's photo file is gone, B's is kept
    assert a.get("/auth/me").status_code == 401
    assert client.post("/auth/login", json={"email": "a@example.com", "password": "password123"}).status_code == 401
    assert b.get("/auth/me").status_code == 200 and len(b.get("/analyses").json()) == 1 and b.get(f"/analyses/{cb['id']}/image").status_code == 200
    assert a.request("DELETE", "/auth/me", json={"password": "password123"}).status_code == 401  # already gone / signed out


def test_delete_is_throttled_like_login(register):
    a, *_ = _mk(register, "a@example.com")
    codes = [a.request("DELETE", "/auth/me", json={"password": f"wrong-{i}"}).status_code for i in range(20)]
    assert 403 in codes and 429 in codes and _rows("users") == 1


def test_signed_out_cannot_delete(client):
    assert client.request("DELETE", "/auth/me", json={"password": "password123"}).status_code == 401


# ---------------- migration, backup and restore tools ----------------
def _old_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), password_hash VARCHAR(255), created_at DATETIME);
        CREATE TABLE farms (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(120), location VARCHAR(200), soil_type VARCHAR(100), created_at DATETIME);
        CREATE TABLE analyses (id INTEGER PRIMARY KEY, user_id INTEGER, farm_id INTEGER, crop VARCHAR(100), symptoms TEXT, language VARCHAR(10),
          result_json JSON, created_at DATETIME, image_path VARCHAR(255), input_type VARCHAR(20) DEFAULT 'text' NOT NULL, weather_json JSON,
          weather_note VARCHAR(300), idempotency_key VARCHAR(64), request_hash VARCHAR(64));
        INSERT INTO users VALUES (1,'old@example.com','x','2026-10-01 10:00:00'),(2,'two@example.com','y','2026-10-02 10:00:00');
        INSERT INTO farms VALUES (1,1,'Old Farm','Guntur','Red soil','2026-10-01 10:00:00'),(2,2,'Other','','','2026-10-02 10:00:00');
        INSERT INTO analyses (id,user_id,farm_id,crop,symptoms,language,result_json,created_at) VALUES
          (1,1,1,'Rice','x','en','{"likely_issue":"Keep me"}','2026-10-01 11:00:00'),
          (2,1,1,'Rice','ఆకులు','te','{"likely_issue":"ఉంచండి"}','2026-10-01 12:00:00');
        """
    )
    con.commit()
    con.close()


def test_migrate_backs_up_first_adds_only_new_things_and_changes_no_existing_value(tmp_path):
    db = tmp_path / "live.db"
    _old_db(db)
    before = cli.snapshot(db)
    rep = cli.migrate_db(db, tmp_path / "bk")
    assert os.path.isfile(rep["backup"]) and cli.snapshot(Path(rep["backup"])) == before  # the backup IS the old database
    assert "farms.primary_crop" in rep["added_columns"] and "analyses.parent_id" in rep["added_columns"] and rep["new_tables"] == ["farm_economics", "farm_events", "farm_plans", "weather_alerts"]
    assert rep["rows"] == {"users": 2, "farms": 2, "analyses": 2} and rep["unchanged"] is True
    assert cli._same_on_old_columns(before, db) == []  # every old value byte-identical (incl. Telugu text)
    again = cli.migrate_db(db, tmp_path / "bk")
    assert again["added_columns"] == [] and again["new_tables"] == []  # idempotent


def test_migrate_restores_the_backup_if_the_migration_itself_fails(tmp_path, monkeypatch):
    db = tmp_path / "live.db"
    _old_db(db)
    before = cli.snapshot(db)

    def boom(engine):
        raise RuntimeError("disk full")

    monkeypatch.setattr("app.database.migrate", boom)
    with pytest.raises(cli.CliError, match="backup was restored"):
        cli.migrate_db(db, tmp_path / "bk")
    assert cli.snapshot(db) == before


def test_migrate_restores_the_backup_if_verification_finds_any_difference(tmp_path, monkeypatch):
    db = tmp_path / "live.db"
    _old_db(db)
    before = cli.snapshot(db)
    monkeypatch.setattr(cli, "_same_on_old_columns", lambda b, p: ["analyses: existing values changed"])
    with pytest.raises(cli.CliError, match="Verification failed"):
        cli.migrate_db(db, tmp_path / "bk")
    assert cli.snapshot(db) == before and "primary_crop" not in str(cli.snapshot(db)["farms"]["cols"])


def test_migrate_refuses_a_missing_or_corrupt_database(tmp_path):
    with pytest.raises(cli.CliError, match="not found"):
        cli.migrate_db(tmp_path / "nope.db")
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite file" * 100)
    before = bad.read_bytes()
    with pytest.raises(Exception):
        cli.migrate_db(bad)
    assert bad.read_bytes() == before  # untouched


def test_cli_entry_point_return_codes_and_restore_needs_confirmation(tmp_path, capsys):
    db = tmp_path / "live.db"
    _old_db(db)
    assert cli.main(["migrate", "--db", str(db), "--backup-dir", str(tmp_path / "bk")]) == 0
    assert "Migration finished and verified" in capsys.readouterr().out
    assert cli.main(["migrate", "--db", str(tmp_path / "missing.db")]) == 1
    backups = list((tmp_path / "bk").glob("*.db"))
    assert backups
    assert cli.main(["restore", "--backup", str(backups[0]), "--db", str(db)]) == 1  # no --yes: refuses
    assert "farms" in cli.snapshot(db) and "primary_crop" in cli.snapshot(db)["farms"]["cols"]  # still the migrated one
    assert cli.main(["restore", "--backup", str(backups[0]), "--db", str(db), "--yes"]) == 0
    assert "primary_crop" not in cli.snapshot(db)["farms"]["cols"]  # back to the pre-migration database
    assert (tmp_path / "live.db.before-restore").exists()


def test_backup_archive_holds_a_verified_database_copy_and_the_uploads(tmp_path):
    db = tmp_path / "live.db"
    _old_db(db)
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "a.png").write_bytes(PNG)
    archive = cli.backup_all(db, up, tmp_path / "out")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert "database.db" in names and "uploads/a.png" in names
        tar.extract("database.db", tmp_path / "x", filter="data")
    assert cli.snapshot(tmp_path / "x" / "database.db") == cli.snapshot(db)
    assert not list((tmp_path / "out").glob("*.db"))  # only the archive is left
