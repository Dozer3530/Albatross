"""SQLite persistence for settings, fields and scenes."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "dashboard.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS fields (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    geometry     TEXT NOT NULL,
    area_ha      REAL,
    source_file  TEXT,
    created_at   TEXT,
    last_checked TEXT
);
CREATE TABLE IF NOT EXISTS scenes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id     INTEGER NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    datetime     TEXT,
    cloud_cover  REAL,
    tile_ids     TEXT,
    status       TEXT NOT NULL DEFAULT 'new',
    first_seen   TEXT,
    processed_at TEXT,
    dir          TEXT,
    ndvi_mean    REAL,
    ndvi_min     REAL,
    ndvi_max     REAL,
    ndvi_std     REAL,
    clear_pct    REAL,
    cloud_pct    REAL,
    UNIQUE (field_id, date)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------- settings

def get_settings() -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def save_settings(values: dict) -> None:
    with connect() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def clear_settings() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM settings")


# ------------------------------------------------------------------ fields

def _field_row(row: sqlite3.Row) -> dict:
    field = dict(row)
    field["geometry"] = json.loads(field["geometry"])
    return field


def insert_field(name: str, geometry: dict, area_ha: float, source_file: str) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO fields (name, geometry, area_ha, source_file, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, json.dumps(geometry), area_ha, source_file, utcnow()),
        )
        field_id = cur.lastrowid
    return get_field(field_id)


FIELD_LIST_SQL = """
SELECT f.*,
  (SELECT COUNT(*) FROM scenes s WHERE s.field_id = f.id AND s.status = 'new') AS new_count,
  (SELECT COUNT(*) FROM scenes s WHERE s.field_id = f.id) AS scene_count,
  (SELECT MAX(s.date) FROM scenes s WHERE s.field_id = f.id) AS latest_date,
  (SELECT s.ndvi_mean FROM scenes s
     WHERE s.field_id = f.id AND s.ndvi_mean IS NOT NULL
     ORDER BY s.date DESC LIMIT 1) AS latest_ndvi
FROM fields f
"""


def list_fields() -> list:
    with connect() as conn:
        rows = conn.execute(FIELD_LIST_SQL + " ORDER BY f.id").fetchall()
    return [_field_row(r) for r in rows]


def get_field(field_id: int):
    with connect() as conn:
        row = conn.execute(FIELD_LIST_SQL + " WHERE f.id = ?", (field_id,)).fetchone()
    return _field_row(row) if row else None


def delete_field(field_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM fields WHERE id = ?", (field_id,))


def touch_field_checked(field_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE fields SET last_checked = ? WHERE id = ?", (utcnow(), field_id))


# ------------------------------------------------------------------ scenes

def _scene_row(row: sqlite3.Row) -> dict:
    scene = dict(row)
    scene["tile_ids"] = json.loads(scene["tile_ids"]) if scene["tile_ids"] else []
    return scene


def upsert_scene(field_id: int, date: str, datetime_str: str,
                 cloud_cover, tile_ids: list) -> bool:
    """Insert a scene if unseen. Returns True when the scene is new."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO scenes (field_id, date, datetime, cloud_cover, tile_ids, first_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(field_id, date) DO NOTHING",
            (field_id, date, datetime_str, cloud_cover, json.dumps(tile_ids), utcnow()),
        )
        return cur.rowcount == 1


def list_scenes(field_id: int) -> list:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scenes WHERE field_id = ? ORDER BY date DESC", (field_id,)
        ).fetchall()
    return [_scene_row(r) for r in rows]


def get_scene(scene_id: int):
    with connect() as conn:
        row = conn.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    return _scene_row(row) if row else None


def mark_scenes_seen(field_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE scenes SET status = 'seen' WHERE field_id = ? AND status = 'new'",
            (field_id,),
        )


def update_scene_processed(scene_id: int, result: dict) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE scenes SET status = 'processed', processed_at = ?, dir = ?, "
            "ndvi_mean = ?, ndvi_min = ?, ndvi_max = ?, ndvi_std = ?, "
            "clear_pct = ?, cloud_pct = ? WHERE id = ?",
            (
                utcnow(), result.get("dir"),
                result.get("ndvi_mean"), result.get("ndvi_min"),
                result.get("ndvi_max"), result.get("ndvi_std"),
                result.get("clear_pct"), result.get("cloud_pct"),
                scene_id,
            ),
        )


def timeseries(field_id: int) -> list:
    with connect() as conn:
        rows = conn.execute(
            "SELECT date, ndvi_mean, ndvi_min, ndvi_max, cloud_cover, cloud_pct "
            "FROM scenes WHERE field_id = ? AND ndvi_mean IS NOT NULL ORDER BY date",
            (field_id,),
        ).fetchall()
    return [dict(r) for r in rows]
