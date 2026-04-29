"""SQLite database layer for VeniceBeach auto-booker."""
import sqlite3
import os
import time
import datetime
from contextlib import contextmanager

import pytz

_BERLIN = pytz.timezone("Europe/Berlin")

DB_PATH = os.environ.get("DB_PATH", "fitness.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            -- Course occurrences fetched from Actinate API
            CREATE TABLE IF NOT EXISTS occurrences (
                id          INTEGER PRIMARY KEY,  -- Actinate occurrence ID
                name        TEXT NOT NULL,
                description TEXT,
                category    TEXT,
                room        TEXT,
                start_at    INTEGER NOT NULL,     -- Unix timestamp
                end_at      INTEGER NOT NULL,
                max_participants  INTEGER,
                attendees_count  INTEGER,
                join_mandatory   INTEGER DEFAULT 0,
                join_open_prior_seconds INTEGER DEFAULT 86400,
                studio_id   INTEGER NOT NULL,
                canceled_at INTEGER,
                joined      INTEGER DEFAULT 0,    -- 1 = user is booked (from API)
                joined_source TEXT,               -- 'app' = booked by this service, 'api' = already joined when fetched
                waitlist_position INTEGER,        -- NULL = not on waitlist, N = position
                fetched_at  INTEGER NOT NULL      -- when we last saw this
            );

            -- Which occurrences the user wants to auto-register for
            CREATE TABLE IF NOT EXISTS subscriptions (
                occurrence_id INTEGER PRIMARY KEY REFERENCES occurrences(id),
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Job execution log
            CREATE TABLE IF NOT EXISTS booking_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                occurrence_id INTEGER NOT NULL,
                status        TEXT NOT NULL,  -- 'scheduled','booked','failed','canceled'
                message       TEXT,
                attempted_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Rules for recurring auto-subscriptions
            CREATE TABLE IF NOT EXISTS recurring_subscriptions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name_substr       TEXT    NOT NULL,
                weekday           INTEGER NOT NULL,  -- 0=Mon … 6=Sun
                hour              INTEGER,           -- NULL = any time
                minute            INTEGER DEFAULT 0,
                tolerance_minutes INTEGER DEFAULT 30,
                studio_id         INTEGER NOT NULL DEFAULT 43,
                active            INTEGER NOT NULL DEFAULT 1,
                created_at        TEXT    DEFAULT CURRENT_TIMESTAMP,
                last_matched_at   TEXT
            );
        """)
        # Migrations for existing databases
        cols = [r[1] for r in conn.execute("PRAGMA table_info(occurrences)").fetchall()]
        if "joined" not in cols:
            conn.execute("ALTER TABLE occurrences ADD COLUMN joined INTEGER DEFAULT 0")
        if "attendees_count" not in cols:
            conn.execute("ALTER TABLE occurrences ADD COLUMN attendees_count INTEGER")
        if "waitlist_position" not in cols:
            conn.execute("ALTER TABLE occurrences ADD COLUMN waitlist_position INTEGER")
        if "joined_source" not in cols:
            conn.execute("ALTER TABLE occurrences ADD COLUMN joined_source TEXT")


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ── Occurrences ───────────────────────────────────────────────────────────────

def upsert_occurrences(occurrences: list[dict]):
    """Insert or update a list of occurrence dicts from the API."""
    now = int(time.time())
    with db() as conn:
        for o in occurrences:
            conn.execute(
                """
                INSERT INTO occurrences
                    (id, name, description, category, room, start_at, end_at,
                     max_participants, attendees_count, join_mandatory, join_open_prior_seconds,
                     studio_id, canceled_at, joined, joined_source, waitlist_position, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    category=excluded.category,
                    room=excluded.room,
                    start_at=excluded.start_at,
                    end_at=excluded.end_at,
                    max_participants=excluded.max_participants,
                    attendees_count=excluded.attendees_count,
                    join_mandatory=excluded.join_mandatory,
                    join_open_prior_seconds=excluded.join_open_prior_seconds,
                    studio_id=excluded.studio_id,
                    canceled_at=excluded.canceled_at,
                    joined=excluded.joined,
                    joined_source=CASE WHEN joined_source='app' THEN 'app' ELSE excluded.joined_source END,
                    waitlist_position=COALESCE(excluded.waitlist_position, waitlist_position),
                    fetched_at=excluded.fetched_at
                """,
                (
                    o["id"],
                    o["name"],
                    o.get("description", ""),
                    o.get("category", ""),
                    o.get("room", ""),
                    o["start_at"],
                    o["end_at"],
                    o.get("max_participants"),
                    o.get("attendees_count"),
                    1 if o.get("join_mandatory") else 0,
                    o.get("join_open_prior_seconds", 86400),
                    o["studio_id"],
                    o.get("canceled_at"),
                    1 if o.get("joined") else 0,
                    "api" if o.get("joined") else None,
                    o.get("waitlist_position"),
                    now,
                ),
            )


def get_occurrences(from_ts: int, to_ts: int, studio_id: int = 43):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT o.*, s.occurrence_id IS NOT NULL AS subscribed
            FROM occurrences o
            LEFT JOIN subscriptions s ON s.occurrence_id = o.id
            WHERE o.studio_id=? AND o.start_at>=? AND o.start_at<=?
              AND o.canceled_at IS NULL
            ORDER BY o.start_at
            """,
            (studio_id, from_ts, to_ts),
        ).fetchall()
        return [dict(r) for r in rows]


def get_occurrence(occurrence_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT o.*, s.occurrence_id IS NOT NULL AS subscribed FROM occurrences o LEFT JOIN subscriptions s ON s.occurrence_id=o.id WHERE o.id=?",
            (occurrence_id,),
        ).fetchone()
        return dict(row) if row else None


# ── Subscriptions ─────────────────────────────────────────────────────────────

def add_subscription(occurrence_id: int):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscriptions(occurrence_id) VALUES(?)",
            (occurrence_id,),
        )


def remove_subscription(occurrence_id: int):
    with db() as conn:
        conn.execute("DELETE FROM subscriptions WHERE occurrence_id=?", (occurrence_id,))


def set_joined(occurrence_id: int, joined: bool):
    with db() as conn:
        conn.execute(
            "UPDATE occurrences SET joined=?, joined_source=? WHERE id=?",
            (1 if joined else 0, "app" if joined else None, occurrence_id),
        )


def set_waitlisted(occurrence_id: int, position=None):
    """Mark occurrence as waitlisted (joined=True, joined_source=NULL)."""
    with db() as conn:
        conn.execute(
            "UPDATE occurrences SET joined=1, joined_source=NULL, waitlist_position=? WHERE id=?",
            (position, occurrence_id),
        )


def set_waitlist_position(occurrence_id: int, position):
    """Set waitlist position (None = not on waitlist)."""
    with db() as conn:
        conn.execute(
            "UPDATE occurrences SET waitlist_position=? WHERE id=?",
            (position, occurrence_id),
        )


def get_upcoming_subscriptions(from_ts: int):
    """Return subscribed occurrences that haven't started yet."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT o.*
            FROM occurrences o
            JOIN subscriptions s ON s.occurrence_id = o.id
            WHERE o.start_at > ? AND o.canceled_at IS NULL
            ORDER BY o.start_at
            """,
            (from_ts,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Booking log ───────────────────────────────────────────────────────────────

def log_booking(occurrence_id: int, status: str, message: str = ""):
    with db() as conn:
        conn.execute(
            "INSERT INTO booking_log(occurrence_id,status,message) VALUES(?,?,?)",
            (occurrence_id, status, message),
        )


def get_booking_log(occurrence_id: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM booking_log WHERE occurrence_id=? ORDER BY id DESC LIMIT 10",
            (occurrence_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def cleanup_log(keep_days: int = 30, max_rows: int = 500):
    """Delete log entries older than keep_days, then cap total rows at max_rows."""
    with db() as conn:
        conn.execute(
            "DELETE FROM booking_log WHERE attempted_at < datetime('now', ?)",
            (f"-{keep_days} days",),
        )
        conn.execute(
            """DELETE FROM booking_log WHERE id NOT IN (
                SELECT id FROM booking_log ORDER BY id DESC LIMIT ?
            )""",
            (max_rows,),
        )


def get_recent_log(limit: int = 50):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT l.*, o.name, o.start_at
            FROM booking_log l
            JOIN occurrences o ON o.id = l.occurrence_id
            ORDER BY l.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Recurring subscriptions ───────────────────────────────────────────────────

_RECURRING_FIELDS = {"name_substr", "weekday", "hour", "minute", "tolerance_minutes", "studio_id", "active"}


def get_recurring_rules(active_only: bool = False) -> list[dict]:
    with db() as conn:
        q = "SELECT * FROM recurring_subscriptions"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY id"
        return [dict(r) for r in conn.execute(q).fetchall()]


def get_recurring_rule(rule_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM recurring_subscriptions WHERE id=?", (rule_id,)
        ).fetchone()
        return dict(row) if row else None


def add_recurring_rule(name_substr: str, weekday: int, hour: int | None,
                       minute: int, tolerance_minutes: int,
                       studio_id: int, active: bool) -> int:
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM recurring_subscriptions WHERE name_substr=? AND weekday=? AND hour=? AND minute=?",
            (name_substr, weekday, hour, minute),
        ).fetchone()
        if existing:
            raise ValueError(f"Eine Buchungsregel für diesen Kurs und Termin existiert bereits.")
        cur = conn.execute(
            """INSERT INTO recurring_subscriptions
               (name_substr, weekday, hour, minute, tolerance_minutes, studio_id, active)
               VALUES (?,?,?,?,?,?,?)""",
            (name_substr, weekday, hour, minute, tolerance_minutes, studio_id, 1 if active else 0),
        )
        return cur.lastrowid


def update_recurring_rule(rule_id: int, **kwargs) -> bool:
    fields = {k: v for k, v in kwargs.items() if k in _RECURRING_FIELDS}
    if not fields:
        return False
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [rule_id]
    with db() as conn:
        conn.execute(
            f"UPDATE recurring_subscriptions SET {set_clause} WHERE id=?", values
        )
        changed = conn.execute("SELECT changes()").fetchone()[0]
        return changed > 0


def delete_recurring_rule(rule_id: int):
    with db() as conn:
        conn.execute("DELETE FROM recurring_subscriptions WHERE id=?", (rule_id,))


def _matches_rule(rule: dict, occ: dict) -> bool:
    if occ["studio_id"] != rule["studio_id"]:
        return False
    if rule["name_substr"].lower() not in occ["name"].lower():
        return False
    dt = datetime.datetime.fromtimestamp(occ["start_at"], tz=_BERLIN)
    if dt.weekday() != rule["weekday"]:
        return False
    if rule["hour"] is not None:
        rule_min = rule["hour"] * 60 + (rule["minute"] or 0)
        occ_min = dt.hour * 60 + dt.minute
        if abs(occ_min - rule_min) > rule["tolerance_minutes"]:
            return False
    return True


def get_course_slots(name: str) -> list[dict]:
    """Return distinct (weekday, hour, minute) slots for upcoming occurrences of a course."""
    now = int(time.time())
    with db() as conn:
        rows = conn.execute(
            "SELECT start_at FROM occurrences WHERE name=? AND start_at>? AND canceled_at IS NULL ORDER BY start_at",
            (name, now),
        ).fetchall()
    seen = set()
    slots = []
    for r in rows:
        dt = datetime.datetime.fromtimestamp(r["start_at"], tz=_BERLIN)
        key = (dt.weekday(), dt.hour, dt.minute)
        if key not in seen:
            seen.add(key)
            slots.append({"weekday": dt.weekday(), "hour": dt.hour, "minute": dt.minute})
    slots.sort(key=lambda s: (s["weekday"], s["hour"], s["minute"]))
    return slots


def get_distinct_course_names() -> list[str]:
    now = int(time.time())
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT name FROM occurrences WHERE start_at > ? AND canceled_at IS NULL ORDER BY name",
            (now,),
        ).fetchall()
        return [r["name"] for r in rows]


def apply_recurring_rules() -> int:
    """Match active rules against future unsubscribed occurrences. Returns new subscription count."""
    now = int(time.time())
    with db() as conn:
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM recurring_subscriptions WHERE active=1"
        ).fetchall()]
        if not rules:
            return 0
        candidates = [dict(r) for r in conn.execute(
            """
            SELECT o.id, o.name, o.start_at, o.studio_id
            FROM occurrences o
            LEFT JOIN subscriptions s ON s.occurrence_id = o.id
            WHERE o.start_at > ? AND o.canceled_at IS NULL AND s.occurrence_id IS NULL
            """,
            (now,),
        ).fetchall()]
        new_count = 0
        for rule in rules:
            for occ in candidates:
                if _matches_rule(rule, occ):
                    conn.execute(
                        "INSERT OR IGNORE INTO subscriptions(occurrence_id) VALUES(?)",
                        (occ["id"],),
                    )
                    new_count += conn.execute("SELECT changes()").fetchone()[0]
            conn.execute(
                "UPDATE recurring_subscriptions SET last_matched_at=datetime('now') WHERE id=?",
                (rule["id"],),
            )
        return new_count


def preview_recurring_rule(rule_id: int) -> list[dict]:
    """Dry-run: return matching future occurrences without writing to DB."""
    now = int(time.time())
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM recurring_subscriptions WHERE id=?", (rule_id,)
        ).fetchone()
        if not row:
            return []
        rule = dict(row)
        candidates = [dict(r) for r in conn.execute(
            """
            SELECT o.id, o.name, o.start_at, o.studio_id,
                   (s.occurrence_id IS NOT NULL) AS already_subscribed
            FROM occurrences o
            LEFT JOIN subscriptions s ON s.occurrence_id = o.id
            WHERE o.start_at > ? AND o.canceled_at IS NULL
            """,
            (now,),
        ).fetchall()]
        return [c for c in candidates if _matches_rule(rule, c)]
