"""Utilitários compartilhados."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
QUEUE_DB = ROOT / "queue.db"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def video_id_from_url(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    return hashlib.sha1(url.encode()).hexdigest()[:11]


def slug_from_filename(path: Path) -> str:
    return hashlib.sha1(path.name.encode()).hexdigest()[:11]


def read_manifest(inbox_id: str) -> dict:
    """Lê manifesto opcional inbox/<id>.json."""
    manifest_path = ROOT / "inbox" / f"{inbox_id}.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {}


def get_queue_db() -> sqlite3.Connection:
    conn = sqlite3.connect(QUEUE_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cut_id TEXT NOT NULL UNIQUE,
            source_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('long', 'short')),
            titulo TEXT NOT NULL,
            descricao TEXT,
            tags TEXT,
            scheduled_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','scheduled','published','failed','blocked')),
            source_url TEXT,
            source_authorized INTEGER NOT NULL DEFAULT 0,
            youtube_video_id TEXT,
            error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_status_scheduled ON posts(status, scheduled_at);

        CREATE TABLE IF NOT EXISTS youtube_quota (
            date TEXT PRIMARY KEY,         -- YYYY-MM-DD (Pacific Time)
            units_used INTEGER NOT NULL DEFAULT 0,
            uploads_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


# === YouTube quota tracking ===
# Quota reseta meia-noite PT = ~4h BRT.
# Default: 10.000 unidades/dia. videos.insert custa 1.600. thumbnails.set custa 50.
QUOTA_PER_UPLOAD = 1600
QUOTA_PER_THUMBNAIL = 50
QUOTA_DAILY_LIMIT_DEFAULT = 10000
QUOTA_SAFETY_MARGIN = 500   # deixa essa margem livre


def _quota_date_today() -> str:
    """Data do reset YouTube (Pacific Time → meia-noite PT)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def quota_get_used_today(conn: sqlite3.Connection) -> tuple[int, int]:
    """Retorna (units_used, uploads_count) do dia corrente (PT)."""
    today = _quota_date_today()
    row = conn.execute(
        "SELECT units_used, uploads_count FROM youtube_quota WHERE date=?", (today,)
    ).fetchone()
    return (row[0], row[1]) if row else (0, 0)


def quota_can_upload(conn: sqlite3.Connection, daily_limit: int = QUOTA_DAILY_LIMIT_DEFAULT,
                     extra_units: int = 0) -> bool:
    """Cabe mais 1 upload (+ thumbnail opcional) na quota de hoje?"""
    used, _ = quota_get_used_today(conn)
    needed = QUOTA_PER_UPLOAD + extra_units
    return (used + needed + QUOTA_SAFETY_MARGIN) <= daily_limit


def quota_record_upload(conn: sqlite3.Connection, units: int = QUOTA_PER_UPLOAD,
                        with_thumbnail: bool = False) -> None:
    """Registra consumo após upload bem-sucedido."""
    today = _quota_date_today()
    total = units + (QUOTA_PER_THUMBNAIL if with_thumbnail else 0)
    conn.execute(
        """INSERT INTO youtube_quota (date, units_used, uploads_count)
           VALUES (?, ?, 1)
           ON CONFLICT(date) DO UPDATE SET
             units_used = units_used + excluded.units_used,
             uploads_count = uploads_count + 1,
             updated_at = CURRENT_TIMESTAMP""",
        (today, total),
    )
    conn.commit()
