import os
import sqlite3
import time
from typing import Optional

from src.core.env_store import (
    ENV_BACKED_FIELDS, get_env_field, is_env_backed_field, set_env_field,
)
from src.core.models import Owner, SetupStep

OBSOLETE_SECRET_FIELDS = ("openrouter_key",)

ALLOWED_FIELDS = {
    "jina_api_key", "deepgram_api_key",
    "github_token", "github_mirror_repo",
    "vps_host", "vps_user", "inbox_chat_id", "setup_step",
    "last_backup_at", "last_backup_error", "backup_failure_count",
}

DB_FIELDS = (
    "telegram_id", "vps_host", "vps_user", "inbox_chat_id", "setup_step",
    "last_backup_at", "last_backup_error", "backup_failure_count",
    "created_at",
)


def create_or_get_owner(conn: sqlite3.Connection, telegram_id: int) -> Owner:
    conn.execute(
        "INSERT OR IGNORE INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (telegram_id, int(time.time())),
    )
    conn.commit()
    owner = get_owner(conn, telegram_id)
    assert owner is not None  # row guaranteed to exist after INSERT OR IGNORE
    return owner


def get_owner(conn: sqlite3.Connection, telegram_id: int) -> Optional[Owner]:
    cols = ", ".join(DB_FIELDS)
    cur = conn.execute(
        f"SELECT {cols} FROM owners WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    fields = list(DB_FIELDS)
    values = list(row)
    # backup_failure_count column is non-null in fresh schema but might be
    # NULL on rows created before the migration ran — coerce to 0 so the
    # Pydantic model (which types it as int) doesn't reject the load.
    fc_idx = fields.index("backup_failure_count")
    if values[fc_idx] is None:
        values[fc_idx] = 0
    data = dict(zip(fields, values))
    for env_field in ENV_BACKED_FIELDS:
        data[env_field] = (
            get_env_field(env_field)
            or _read_legacy_field(conn, telegram_id, env_field)
        )
    return Owner(**data)


def update_owner_field(conn: sqlite3.Connection, telegram_id: int, field: str, value) -> None:
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"unknown field: {field}")
    if is_env_backed_field(field):
        set_env_field(field, value)
        _clear_legacy_field(conn, telegram_id, field)
        return
    conn.execute(
        f"UPDATE owners SET {field} = ? WHERE telegram_id = ?",
        (value, telegram_id),
    )
    conn.commit()


def migrate_owner_secrets_to_env(conn: sqlite3.Connection,
                                 telegram_id: int) -> None:
    """Move legacy DB-stored API tokens/config into .env and scrub DB cells.

    Fresh databases no longer have these columns. Existing installs may,
    so startup runs this once after the owner row exists. If .env already
    has a value, it wins and the stale DB value is simply cleared.
    """
    for field in ENV_BACKED_FIELDS:
        value = _read_legacy_field(conn, telegram_id, field)
        if value and not get_env_field(field):
            set_env_field(field, value)
        _clear_legacy_field(conn, telegram_id, field)
    for field in OBSOLETE_SECRET_FIELDS:
        _clear_legacy_field(conn, telegram_id, field)


def advance_setup_step(conn: sqlite3.Connection, telegram_id: int, step: SetupStep) -> None:
    update_owner_field(conn, telegram_id, "setup_step", step)


def record_backup_success(conn: sqlite3.Connection, telegram_id: int,
                           timestamp: str) -> None:
    """Mark a successful nightly backup. Resets the consecutive-failure
    counter so the next failure starts a fresh streak (and the threshold
    DM logic in main.py works as intended)."""
    conn.execute(
        """UPDATE owners
              SET last_backup_at = ?,
                  last_backup_error = NULL,
                  backup_failure_count = 0
            WHERE telegram_id = ?""",
        (timestamp, telegram_id),
    )
    conn.commit()


def record_backup_failure(conn: sqlite3.Connection, telegram_id: int,
                           error: str) -> int:
    """Persist the latest backup error and bump the failure counter.
    Returns the new counter value so the caller can decide whether to
    notify the owner."""
    conn.execute(
        """UPDATE owners
              SET last_backup_error = ?,
                  backup_failure_count = COALESCE(backup_failure_count, 0) + 1
            WHERE telegram_id = ?""",
        (error, telegram_id),
    )
    conn.commit()
    cur = conn.execute(
        "SELECT backup_failure_count FROM owners WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def reset_backup_failure_count(conn: sqlite3.Connection, telegram_id: int) -> None:
    """Used after a threshold-DM has been delivered so the user gets a
    follow-up DM only after another full window of failures, not on every
    nightly tick."""
    conn.execute(
        "UPDATE owners SET backup_failure_count = 0 WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()


def seed_vps_from_env(conn: sqlite3.Connection, telegram_id: int) -> None:
    """Populate vps_user/vps_host from SOROKA_VPS_USER/SOROKA_VPS_HOST env vars
    if the user has set them in .env manually. A manual /setvps still wins:
    we only write fields that are currently empty in the DB."""
    user = (os.environ.get("SOROKA_VPS_USER") or "").strip()
    host = (os.environ.get("SOROKA_VPS_HOST") or "").strip()
    if not user or not host:
        return
    owner = get_owner(conn, telegram_id)
    if owner is None:
        return
    if not owner.vps_user:
        update_owner_field(conn, telegram_id, "vps_user", user)
    if not owner.vps_host:
        update_owner_field(conn, telegram_id, "vps_host", host)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _read_legacy_field(conn: sqlite3.Connection, telegram_id: int,
                       field: str) -> Optional[str]:
    if not _column_exists(conn, "owners", field):
        return None
    row = conn.execute(
        f"SELECT {field} FROM owners WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0]).strip() or None


def _clear_legacy_field(conn: sqlite3.Connection, telegram_id: int,
                        field: str) -> None:
    if not _column_exists(conn, "owners", field):
        return
    conn.execute(
        f"UPDATE owners SET {field} = NULL WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()
