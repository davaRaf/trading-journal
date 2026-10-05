# -*- coding: utf-8 -*-
"""
Заметки: свободный текст с названием, не привязанный к сделке.

Люди просили место «просто записать мысль» — правило, вывод недели,
список задач. Живут в «Обзоре» маленькой карточкой, пишутся в боковой
панели (static/notes.js).
"""
import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT NOT NULL DEFAULT '',
  body       TEXT NOT NULL DEFAULT '',
  pinned     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notes_user ON notes (user_id, updated_at DESC);
"""

MAX_NOTES = 500            # на человека; больше — уже не заметки, а архив
MAX_TITLE = 120
MAX_BODY = 20000

_ready = False


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


def _out(r):
    return {"id": r["id"], "title": r["title"], "body": r["body"], "pinned": r["pinned"],
            "updated": r["updated_at"].isoformat(), "created": r["created_at"].isoformat()}


def lst(uid):
    init()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM notes WHERE user_id=%s "
                            "ORDER BY pinned DESC, updated_at DESC", (uid,)).fetchall()
    return [_out(r) for r in rows]


def save(uid, note):
    """Новая (без id) или правка своей. None — чужая/нет такой или упёрлись в лимит."""
    init()
    note = note or {}
    title = str(note.get("title") or "").strip()[:MAX_TITLE]
    body = str(note.get("body") or "").rstrip()[:MAX_BODY]
    pinned = bool(note.get("pinned"))
    try:
        nid = int(note.get("id") or 0)
    except (TypeError, ValueError):
        return None
    with db.connect() as conn:
        if nid:
            row = conn.execute(
                "UPDATE notes SET title=%s, body=%s, pinned=%s, updated_at=now() "
                "WHERE id=%s AND user_id=%s RETURNING *",
                (title, body, pinned, nid, uid)).fetchone()
        else:
            n = conn.execute("SELECT count(*) AS n FROM notes WHERE user_id=%s",
                             (uid,)).fetchone()["n"]
            if n >= MAX_NOTES:
                return None
            row = conn.execute(
                "INSERT INTO notes (user_id, title, body, pinned) VALUES (%s,%s,%s,%s) "
                "RETURNING *", (uid, title, body, pinned)).fetchone()
        conn.commit()
    return _out(row) if row else None


def drop(uid, nid):
    init()
    with db.connect() as conn:
        conn.execute("DELETE FROM notes WHERE id=%s AND user_id=%s", (nid, uid))
        conn.commit()
