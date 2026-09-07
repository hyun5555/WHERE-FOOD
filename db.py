"""SQLite menu evidence and request-linked feedback (no ORM required)."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db(path):
    with connect(path) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS menu_items (
                place_id TEXT NOT NULL,
                menu_name TEXT NOT NULL,
                data_json TEXT NOT NULL,
                PRIMARY KEY (place_id, menu_name)
            );
            CREATE TABLE IF NOT EXISTS recommendation_requests (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES recommendation_requests(id),
                event_type TEXT NOT NULL,
                place_id TEXT,
                rank INTEGER,
                created_at TEXT NOT NULL
            );
        """)


def upsert_menus(path, menus):
    # Validate the entire import before starting this atomic transaction.
    with connect(path) as con:
        con.executemany("""
            INSERT INTO menu_items VALUES (?, ?, ?)
            ON CONFLICT(place_id, menu_name) DO UPDATE SET data_json=excluded.data_json
        """, [(m.place_id, m.menu_name, m.model_dump_json()) for m in menus])


def get_menus(path, place_ids):
    if not place_ids:
        return []
    with connect(path) as con:
        rows = con.execute(
            "SELECT data_json FROM menu_items WHERE place_id IN ("
            + ",".join("?" for _ in place_ids) + ")", list(place_ids)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def menu_count(path):
    with connect(path) as con:
        return con.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0]


def catalog_names(path):
    with connect(path) as con:
        rows = con.execute("SELECT data_json FROM menu_items ORDER BY place_id, menu_name").fetchall()
    return sorted({json.loads(row[0])["restaurant_name"] for row in rows})[:6]


def save_request(path, session_id, result):
    # Keep ranking evidence, not raw query, exact origin or candidate coordinates.
    snapshot = json.loads(json.dumps(result))
    snapshot.pop("origin", None)
    snapshot.pop("location_options", None)
    constraints = snapshot.get("constraints", {})
    constraints.pop("location_text", None)
    constraints.pop("source_spans", None)
    for item in snapshot.get("recommendations", []):
        for key in ("x", "y", "address_name", "road_address_name"):
            item.pop(key, None)
        if item.get("route"):
            # Routing links can embed the user's precise starting coordinates.
            item["route"]["source_url"] = "https://map.kakao.com/link/to/" + item["id"]
    with connect(path) as con:
        con.execute("INSERT INTO recommendation_requests VALUES (?, ?, ?, ?)", (
            result["request_id"], session_id,
            json.dumps(snapshot, ensure_ascii=False), utcnow(),
        ))


def record_event(path, session_id, event):
    with connect(path) as con:
        row = con.execute(
            "SELECT snapshot_json FROM recommendation_requests WHERE id=? AND session_id=?",
            (str(event.request_id), session_id),
        ).fetchone()
        if row is None:
            raise ValueError("현재 세션의 추천 요청을 찾을 수 없습니다.")
        items = json.loads(row[0])["recommendations"]
        item = next((p for p in items if p["id"] == event.place_id), None)
        if event.event_type == "recommendations_viewed":
            if event.place_id is not None or not items:
                raise ValueError("표시할 추천 결과가 없습니다.")
        elif item is None:
            raise ValueError("이 요청에서 추천한 식당만 기록할 수 있습니다.")
        values = (str(event.id), str(event.request_id), event.event_type,
                  event.place_id, item["rank"] if item else None)
        previous = con.execute(
            "SELECT id, request_id, event_type, place_id, rank FROM events WHERE id=?",
            (str(event.id),),
        ).fetchone()
        if previous:
            if tuple(previous) != values:
                raise ValueError("이미 사용된 이벤트 ID입니다.")
            return
        con.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", (*values, utcnow()))
