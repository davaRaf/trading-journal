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
import re
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

-- Хто зробив знімок. Потрібно, щоб під ним показати посилання на журнал
-- автора — і лише поки той тримає журнал відкритим. У старих посилань
-- автора немає, вони так і лишаються без підпису.
ALTER TABLE shares ADD COLUMN IF NOT EXISTS user_id BIGINT;

-- Статистика посилань для власників: знімки видаляються після терміну, а
-- ця таблиця лишається. kind — стабільний тип (trade, day, week, month,
-- year, ts, review), views — відкриття сторінки людьми (не краулерами).
CREATE TABLE IF NOT EXISTS share_stats (
  id       TEXT PRIMARY KEY,
  user_id  BIGINT,
  kind     TEXT NOT NULL DEFAULT '',
  created  BIGINT NOT NULL,
  views    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS share_stats_user ON share_stats (user_id);
"""

BOT_UA = re.compile(r"bot|crawl|spider|preview|telegram|discord|facebook|whatsapp|slack|"
                    r"twitter|viber|skype|linkedin|curl|wget|python-requests", re.I)


def kind_of(payload):
    """Тип знімка. Нові кладуть data.type; для старих вгадуємо за вмістом."""
    p = payload or {}
    t = str(p.get("type") or "").strip().lower()
    if t in ("trade", "day", "week", "month", "year", "ts", "review"):
        return t
    if p.get("ts"):
        return "ts"
    if p.get("review"):
        return "review"
    if p.get("calendar"):
        return "period"
    if p.get("trades"):
        return "trade"
    return "other"


def hit(sid, user_agent=""):
    """Людина відкрила сторінку за посиланням. Краулери превʼю не рахуємо."""
    if BOT_UA.search(user_agent or ""):
        return
    try:
        init()
        with db.connect() as conn:
            conn.execute("UPDATE share_stats SET views = views + 1 WHERE id=%s", (sid,))
    except Exception:
        pass

_ready = False


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


def create(payload, ttl_key, ttl_seconds, user_id=None):
    init()
    sid = secrets.token_urlsafe(9)          # 12 символів, вистачає з запасом
    now = int(time.time())
    rec = {"id": sid, "created": now,
           "expires": now + ttl_seconds if ttl_seconds else 0,
           "ttl": ttl_key, "data": payload, "user_id": user_id}
    with db.connect() as conn:
        conn.execute("INSERT INTO shares (id, data, created, expires, ttl, user_id) "
                     "VALUES (%s,%s,%s,%s,%s,%s)",
                     (sid, Jsonb(payload), now, rec["expires"], ttl_key, user_id))
        conn.execute("INSERT INTO share_stats (id, user_id, kind, created) VALUES (%s,%s,%s,%s)",
                     (sid, user_id, kind_of(payload), now))
        # заодно підмітаємо те, що вже прострочилось
        conn.execute("DELETE FROM shares WHERE expires > 0 AND expires < %s", (now,))
    return rec


def read(sid):
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT id, data, created, expires, ttl, user_id "
                           "FROM shares WHERE id=%s", (sid,)).fetchone()
        if not row:
            return None
        if row["expires"] and time.time() > row["expires"]:
            conn.execute("DELETE FROM shares WHERE id=%s", (sid,))
            return None
    return {"id": row["id"], "data": row["data"], "created": row["created"],
            "expires": row["expires"], "ttl": row["ttl"], "user_id": row["user_id"]}
