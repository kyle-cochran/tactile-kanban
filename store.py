import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TagRecord:
    mac: str
    nfc_uid: Optional[str]
    width: int
    height: int
    alias: str
    last_seen: Optional[str]


@dataclass
class Assignment:
    mac: str
    github_item_id: str
    issue_number: int
    issue_title: str
    status: str
    status_option_id: str
    assignee: str
    sprint_id: str
    assigned_at: str


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tags (
                    mac       TEXT PRIMARY KEY,
                    nfc_uid   TEXT UNIQUE,
                    width     INTEGER NOT NULL DEFAULT 0,
                    height    INTEGER NOT NULL DEFAULT 0,
                    alias     TEXT NOT NULL DEFAULT '',
                    last_seen TEXT
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    mac              TEXT PRIMARY KEY REFERENCES tags(mac),
                    github_item_id   TEXT NOT NULL,
                    issue_number     INTEGER NOT NULL,
                    issue_title      TEXT NOT NULL,
                    status           TEXT NOT NULL DEFAULT 'Todo',
                    status_option_id TEXT NOT NULL DEFAULT '',
                    assignee         TEXT NOT NULL DEFAULT '',
                    sprint_id        TEXT NOT NULL,
                    assigned_at      TEXT NOT NULL
                );
            """)

    def upsert_tag(self, mac: str, width: int, height: int, alias: str = ""):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO tags (mac, width, height, alias, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mac) DO UPDATE SET
                    width     = excluded.width,
                    height    = excluded.height,
                    alias     = CASE WHEN excluded.alias != '' THEN excluded.alias ELSE alias END,
                    last_seen = excluded.last_seen
                """,
                (mac, width, height, alias, datetime.utcnow().isoformat()),
            )

    def set_nfc_uid(self, mac: str, nfc_uid: str):
        with self._conn() as conn:
            conn.execute("UPDATE tags SET nfc_uid=? WHERE mac=?", (nfc_uid, mac))

    def get_tag_by_nfc(self, nfc_uid: str) -> Optional[TagRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tags WHERE nfc_uid=?", (nfc_uid,)
            ).fetchone()
            return _row_to_tag(row) if row else None

    def get_tag(self, mac: str) -> Optional[TagRecord]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tags WHERE mac=?", (mac,)).fetchone()
            return _row_to_tag(row) if row else None

    def get_all_tags(self) -> list[TagRecord]:
        with self._conn() as conn:
            return [_row_to_tag(r) for r in conn.execute("SELECT * FROM tags").fetchall()]

    def set_assignment(
        self,
        mac: str,
        item_id: str,
        issue_number: int,
        issue_title: str,
        status: str,
        status_option_id: str,
        assignee: str,
        sprint_id: str,
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO assignments
                    (mac, github_item_id, issue_number, issue_title,
                     status, status_option_id, assignee, sprint_id, assigned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac) DO UPDATE SET
                    github_item_id   = excluded.github_item_id,
                    issue_number     = excluded.issue_number,
                    issue_title      = excluded.issue_title,
                    status           = excluded.status,
                    status_option_id = excluded.status_option_id,
                    assignee         = excluded.assignee,
                    sprint_id        = excluded.sprint_id,
                    assigned_at      = excluded.assigned_at
                """,
                (
                    mac,
                    item_id,
                    issue_number,
                    issue_title,
                    status,
                    status_option_id,
                    assignee,
                    sprint_id,
                    datetime.utcnow().isoformat(),
                ),
            )

    def update_assignment_status(self, mac: str, status: str, status_option_id: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE assignments SET status=?, status_option_id=? WHERE mac=?",
                (status, status_option_id, mac),
            )

    def get_assignment(self, mac: str) -> Optional[Assignment]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM assignments WHERE mac=?", (mac,)
            ).fetchone()
            return _row_to_assignment(row) if row else None

    def get_all_assignments(self) -> list[tuple[TagRecord, Assignment]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT t.*, a.github_item_id, a.issue_number, a.issue_title,
                       a.status, a.status_option_id, a.assignee, a.sprint_id, a.assigned_at
                FROM tags t
                JOIN assignments a ON t.mac = a.mac
                """
            ).fetchall()
            return [(_row_to_tag(r), _row_to_assignment(r)) for r in rows]

    def get_unassigned_tags(self) -> list[TagRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT t.* FROM tags t
                LEFT JOIN assignments a ON t.mac = a.mac
                WHERE a.mac IS NULL
                """
            ).fetchall()
            return [_row_to_tag(r) for r in rows]

    def get_tags_without_nfc(self) -> list[TagRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tags WHERE nfc_uid IS NULL"
            ).fetchall()
            return [_row_to_tag(r) for r in rows]

    def remove_assignment(self, mac: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM assignments WHERE mac=?", (mac,))


def _row_to_tag(row) -> TagRecord:
    return TagRecord(
        mac=row["mac"],
        nfc_uid=row["nfc_uid"],
        width=row["width"],
        height=row["height"],
        alias=row["alias"],
        last_seen=row["last_seen"],
    )


def _row_to_assignment(row) -> Assignment:
    return Assignment(
        mac=row["mac"],
        github_item_id=row["github_item_id"],
        issue_number=row["issue_number"],
        issue_title=row["issue_title"],
        status=row["status"],
        status_option_id=row["status_option_id"],
        assignee=row["assignee"],
        sprint_id=row["sprint_id"],
        assigned_at=row["assigned_at"],
    )
