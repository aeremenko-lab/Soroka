import pytest
from src.core.db import open_db, init_schema
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field, advance_setup_step,
    seed_vps_from_env,
)

def test_create_or_get_owner_inserts_once(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    o1 = create_or_get_owner(conn, telegram_id=42)
    o2 = create_or_get_owner(conn, telegram_id=42)
    assert o1.telegram_id == o2.telegram_id == 42
    rows = conn.execute("SELECT count(*) FROM owners").fetchone()
    assert rows[0] == 1

def test_update_owner_field_round_trip(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    update_owner_field(conn, 42, "jina_api_key", "abc")
    o = get_owner(conn, 42)
    assert o.jina_api_key == "abc"
    cols = {row[1] for row in conn.execute("PRAGMA table_info(owners)").fetchall()}
    assert "jina_api_key" not in cols
    assert "SOROKA_JINA_API_KEY=abc" in (tmp_path / ".env").read_text()


def test_update_owner_field_writes_github_repo_to_env(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    update_owner_field(conn, 42, "github_mirror_repo", "me/soroka-data")

    owner = get_owner(conn, 42)
    assert owner.github_mirror_repo == "me/soroka-data"
    cols = {row[1] for row in conn.execute("PRAGMA table_info(owners)").fetchall()}
    assert "github_mirror_repo" not in cols
    assert "SOROKA_GITHUB_REPO=me/soroka-data" in (tmp_path / ".env").read_text()


def test_migrate_owner_secrets_to_env_clears_legacy_db(tmp_path):
    from src.core.owners import migrate_owner_secrets_to_env

    db_path = tmp_path / "legacy.db"
    conn = open_db(str(db_path))
    conn.execute("""CREATE TABLE owners (
        telegram_id INTEGER PRIMARY KEY,
        jina_api_key TEXT,
        deepgram_api_key TEXT,
        openrouter_key TEXT,
        primary_model TEXT,
        fallback_model TEXT,
        github_token TEXT,
        github_mirror_repo TEXT,
        vps_host TEXT,
        vps_user TEXT,
        inbox_chat_id INTEGER,
        setup_step TEXT,
        last_backup_at TEXT,
        last_backup_error TEXT,
        backup_failure_count INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL
    )""")
    conn.execute(
        "INSERT INTO owners (telegram_id, jina_api_key, openrouter_key, "
        "github_token, github_mirror_repo, created_at) "
        "VALUES (42, 'jina-old', 'obsolete-old', 'ghp_old', 'me/old-repo', 1)"
    )
    conn.commit()

    migrate_owner_secrets_to_env(conn, 42)

    owner = get_owner(conn, 42)
    assert owner.jina_api_key == "jina-old"
    assert owner.github_token == "ghp_old"
    assert owner.github_mirror_repo == "me/old-repo"
    row = conn.execute(
        "SELECT jina_api_key, openrouter_key, github_token, github_mirror_repo "
        "FROM owners WHERE telegram_id=42"
    ).fetchone()
    assert row == (None, None, None, None)

def test_advance_setup_step_writes_step(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "jina")
    assert get_owner(conn, 42).setup_step == "jina"

def test_update_owner_field_rejects_unknown_field(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    with pytest.raises(ValueError, match="unknown field"):
        update_owner_field(conn, 42, "telegram_id", 99)

def test_get_owner_returns_none_for_missing(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    assert get_owner(conn, 9999) is None


def test_seed_vps_from_env_writes_when_db_empty(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    monkeypatch.setenv("SOROKA_VPS_USER", "ubuntu")
    monkeypatch.setenv("SOROKA_VPS_HOST", "myvps")
    seed_vps_from_env(conn, 42)
    o = get_owner(conn, 42)
    assert o.vps_user == "ubuntu"
    assert o.vps_host == "myvps"


def test_seed_vps_from_env_does_not_overwrite_existing(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    update_owner_field(conn, 42, "vps_user", "manual")
    update_owner_field(conn, 42, "vps_host", "manual.example")
    monkeypatch.setenv("SOROKA_VPS_USER", "ubuntu")
    monkeypatch.setenv("SOROKA_VPS_HOST", "myvps")
    seed_vps_from_env(conn, 42)
    o = get_owner(conn, 42)
    assert o.vps_user == "manual"
    assert o.vps_host == "manual.example"


def test_seed_vps_from_env_noop_when_env_missing(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    monkeypatch.delenv("SOROKA_VPS_USER", raising=False)
    monkeypatch.delenv("SOROKA_VPS_HOST", raising=False)
    seed_vps_from_env(conn, 42)
    o = get_owner(conn, 42)
    assert o.vps_user is None
    assert o.vps_host is None
