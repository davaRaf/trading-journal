# -*- coding: utf-8 -*-
"""
Посилання «поділитись»: знімок дня, тижня, місяця чи однієї угоди.

Раніше знімки лежали файлами в data/shares. На своєму комп'ютері це
нормально, а на хостингу файлова система тимчасова — після кожного
оновлення коду всі роздані посилання переставали відкриватись. Тепер
знімок лежить у базі, тому живе рівно стільки, скільки вибрала людина.

Прострочені записи прибираються дорогою, коли до них звертаються, і
пачкою — при створенні нового посилання.
"""
import secrets
import time

from psycopg.types.json import Jsonb

import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS shares (
  id       TEXT PRIMARY KEY,
  data     JSONB NOT NULL,
  created  BIGINT NOT NULL,
  expires  BIGINT NOT NULL DEFAULT 0,
  ttl      TEXT NOT NULL DEFAULT ''
);
"""

_ready = False


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


def create(payload, ttl_key, ttl_seconds):
    init()
    sid = secrets.token_urlsafe(9)          # 12 символів, вистачає з запасом
    now = int(time.time())
    rec = {"id": sid, "created": now,
           "expires": now + ttl_seconds if ttl_seconds else 0,
           "ttl": ttl_key, "data": payload}
    with db.connect() as conn:
        conn.execute("INSERT INTO shares (id, data, created, expires, ttl) VALUES (%s,%s,%s,%s,%s)",
                     (sid, Jsonb(payload), now, rec["expires"], ttl_key))
        # заодно підмітаємо те, що вже прострочилось
        conn.execute("DELETE FROM shares WHERE expires > 0 AND expires < %s", (now,))
    return rec


def read(sid):
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT id, data, created, expires, ttl FROM shares WHERE id=%s",
                           (sid,)).fetchone()
        if not row:
            return None
        if row["expires"] and time.time() > row["expires"]:
            conn.execute("DELETE FROM shares WHERE id=%s", (sid,))
            return None
    return {"id": row["id"], "data": row["data"], "created": row["created"],
            "expires": row["expires"], "ttl": row["ttl"]}
