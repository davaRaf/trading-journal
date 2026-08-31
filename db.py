# -*- coding: utf-8 -*-
"""
Postgres (Neon). Соединения короткоживущие: и сайт, и бот ходят в одну базу
из разных процессов, держать общее соединение между ними незачем.
"""
import datetime
import secrets

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config import DATABASE_URL

# Текстовые поля сделки. Порядок важен: по нему строятся INSERT/UPDATE.
TEXT_FIELDS = ["pair", "date", "session", "position", "entry_model", "bias", "setup",
               "direction_type", "result", "entry_details", "notes", "mistakes",
               "comments", "emotion", "notion_id"]
NUM_FIELDS = ["rr", "risk"]
FIELDS = TEXT_FIELDS + NUM_FIELDS

LINK_CODE_TTL = datetime.timedelta(minutes=15)


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан — заполни .env (см. .env.example)")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def now():
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------- схема ----

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id                BIGSERIAL PRIMARY KEY,
  email             TEXT NOT NULL,
  nickname          TEXT NOT NULL,
  email_norm        TEXT NOT NULL UNIQUE,
  pw_hash           TEXT NOT NULL,
  pw_salt           TEXT NOT NULL,
  pw_iters          INTEGER NOT NULL,
  telegram_id       BIGINT UNIQUE,
  telegram_username TEXT,
  digest_hour       SMALLINT NOT NULL DEFAULT 8,
  digest_minute     SMALLINT NOT NULL DEFAULT 0,
  digest_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_nickname_norm ON users (lower(nickname));

CREATE TABLE IF NOT EXISTS trades (
  id                    TEXT PRIMARY KEY,
  user_id               BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  "pair"                TEXT NOT NULL DEFAULT '',
  "date"                TEXT NOT NULL DEFAULT '',
  "session"             TEXT NOT NULL DEFAULT '',
  "position"            TEXT NOT NULL DEFAULT '',
  "entry_model"         TEXT NOT NULL DEFAULT '',
  "bias"                TEXT NOT NULL DEFAULT '',
  "setup"               TEXT NOT NULL DEFAULT '',
  "direction_type"      TEXT NOT NULL DEFAULT '',
  "result"              TEXT NOT NULL DEFAULT '',
  "entry_details"       TEXT NOT NULL DEFAULT '',
  "notes"               TEXT NOT NULL DEFAULT '',
  "mistakes"            TEXT NOT NULL DEFAULT '',
  "comments"            TEXT NOT NULL DEFAULT '',
  "emotion"             TEXT NOT NULL DEFAULT '',
  "notion_id"           TEXT NOT NULL DEFAULT '',   -- id записи в Notion: чтобы импорт не задваивал
  rr                    DOUBLE PRECISION,
  risk                  DOUBLE PRECISION,
  screenshots           JSONB NOT NULL DEFAULT '[]'::jsonb,
  hidden                BOOLEAN NOT NULL DEFAULT FALSE,
  emotion_prompt_status TEXT NOT NULL DEFAULT 'na',
  emotion_prompt_msg_id BIGINT,
  emotion_prompt_at     TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trades_user ON trades (user_id);
CREATE INDEX IF NOT EXISTS trades_user_date ON trades (user_id, "date");
CREATE INDEX IF NOT EXISTS trades_pending_emotion ON trades (user_id)
  WHERE emotion_prompt_status = 'pending';

CREATE TABLE IF NOT EXISTS link_codes (
  code       TEXT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS notified_events (
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_key   TEXT NOT NULL,
  kind        TEXT NOT NULL,
  notified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, event_key, kind)
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Своими словами ответ храним отдельно: в emotion лежит категория для статистики,
-- а тут — как человек это сказал.
ALTER TABLE trades ADD COLUMN IF NOT EXISTS emotion_raw TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS "notion_id" TEXT NOT NULL DEFAULT '';
"""


def init():
    with connect() as conn:
        conn.execute(SCHEMA)
        conn.commit()


# ----------------------------------------------------------------- meta ----

def meta_get(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(key, value):
    with connect() as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (%s, %s) "
                     "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                     (key, str(value)))
        conn.commit()


# ------------------------------------------------------------ пользователи ----

def create_user(email, nickname, pw_hash, pw_salt, pw_iters):
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO users (email, nickname, email_norm, pw_hash, pw_salt, pw_iters) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (email, nickname, email.strip().lower(), pw_hash, pw_salt, pw_iters)).fetchone()
        conn.commit()
    return row


def get_user(uid):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()


def get_user_by_login(login):
    """Вход по почте или по нику — на экране входа одно поле на оба варианта."""
    key = (login or "").strip().lower()
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email_norm=%s OR lower(nickname)=%s LIMIT 1",
            (key, key)).fetchone()


def get_user_by_telegram(tg_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE telegram_id=%s", (tg_id,)).fetchone()


def linked_users():
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id IS NOT NULL ORDER BY id").fetchall()


# ---------------------------------------------------------------- сделки ----

def _row_to_trade(row):
    if row is None:
        return None
    t = {"id": row["id"]}
    for f in TEXT_FIELDS:
        t[f] = row[f] or ""
    for f in NUM_FIELDS:
        t[f] = row[f]
    t["screenshots"] = row["screenshots"] or []
    if row["hidden"]:
        t["hidden"] = True
    return t


def list_trades(user_id):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM trades WHERE user_id=%s ORDER BY created_at",
                            (user_id,)).fetchall()
    return [_row_to_trade(r) for r in rows]


def get_trade(tid, user_id=None):
    sql = "SELECT * FROM trades WHERE id=%s"
    args = [tid]
    if user_id is not None:
        sql += " AND user_id=%s"
        args.append(user_id)
    with connect() as conn:
        return _row_to_trade(conn.execute(sql, args).fetchone())


def notion_known(user_id):
    """Что у человека уже есть: инструменты и id записей Notion.
    Импорт по ним понимает, что переносить не нужно."""
    with connect() as conn:
        rows = conn.execute('SELECT DISTINCT "pair", "notion_id" FROM trades '
                            'WHERE user_id=%s', (user_id,)).fetchall()
    known = {(r["pair"] or "").strip() for r in rows if (r["pair"] or "").strip()}
    seen = {r["notion_id"] for r in rows if r["notion_id"]}
    return known, seen


def owns_screenshot(user_id, filename):
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM trades WHERE user_id=%s AND screenshots @> %s LIMIT 1",
            (user_id, Jsonb([{"file": filename}]))).fetchone()
    return row is not None


def _trade_values(t):
    vals = [t.get(f) or "" for f in TEXT_FIELDS]
    vals += [t.get(f) for f in NUM_FIELDS]
    vals += [Jsonb(t.get("screenshots") or []), bool(t.get("hidden"))]
    return vals


_COLS = ", ".join('"%s"' % f for f in FIELDS) + ", screenshots, hidden"
_PLACEHOLDERS = ", ".join(["%s"] * (len(FIELDS) + 2))
_SETS = ", ".join('"%s"=%%s' % f for f in FIELDS) + ", screenshots=%s, hidden=%s"


def insert_trade(user_id, t, emotion_status="na"):
    with connect() as conn:
        conn.execute(
            "INSERT INTO trades (id, user_id, %s, emotion_prompt_status) "
            "VALUES (%%s, %%s, %s, %%s)" % (_COLS, _PLACEHOLDERS),
            [t["id"], user_id] + _trade_values(t) + [emotion_status])
        conn.commit()
    return t


def update_trade(user_id, t):
    with connect() as conn:
        cur = conn.execute(
            "UPDATE trades SET %s WHERE id=%%s AND user_id=%%s" % _SETS,
            _trade_values(t) + [t["id"], user_id])
        conn.commit()
    return cur.rowcount > 0


def delete_trade(user_id, tid):
    with connect() as conn:
        cur = conn.execute("DELETE FROM trades WHERE id=%s AND user_id=%s", (tid, user_id))
        conn.commit()
    return cur.rowcount > 0


# ------------------------------------------------------- эмоция по сделке ----

def mark_emotion_pending(tid, msg_id=None):
    with connect() as conn:
        conn.execute("UPDATE trades SET emotion_prompt_status='pending', "
                     "emotion_prompt_msg_id=%s, emotion_prompt_at=now() WHERE id=%s",
                     (msg_id, tid))
        conn.commit()


def set_emotion_prompt_msg(tid, msg_id):
    with connect() as conn:
        conn.execute("UPDATE trades SET emotion_prompt_msg_id=%s WHERE id=%s", (msg_id, tid))
        conn.commit()


def set_trade_emotion(tid, emotion, raw=None):
    """Пишем ответ только если промпт всё ещё ждёт — защита от второго нажатия."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE trades SET \"emotion\"=%s, emotion_raw=%s, emotion_prompt_status='answered' "
            "WHERE id=%s AND emotion_prompt_status='pending'", (emotion, raw, tid))
        conn.commit()
    return cur.rowcount > 0


def trades_with_emotion(user_id):
    """Для разбора: только закрытые сделки, где эмоция известна."""
    with connect() as conn:
        return conn.execute(
            "SELECT \"emotion\", \"result\", rr, risk, \"date\", \"pair\", \"setup\", "
            "\"mistakes\", emotion_raw FROM trades "
            "WHERE user_id=%s AND \"emotion\" <> '' AND \"result\" <> '' ORDER BY \"date\"",
            (user_id,)).fetchall()


def pending_emotion_trades(user_id):
    with connect() as conn:
        return conn.execute(
            "SELECT id, \"pair\", \"date\", emotion_prompt_msg_id FROM trades "
            "WHERE user_id=%s AND emotion_prompt_status='pending' ORDER BY emotion_prompt_at",
            (user_id,)).fetchall()


# ------------------------------------------------------- привязка Telegram ----

def create_link_code(user_id):
    code = secrets.token_hex(4)
    with connect() as conn:
        conn.execute("INSERT INTO link_codes (code, user_id, expires_at) VALUES (%s, %s, %s)",
                     (code, user_id, now() + LINK_CODE_TTL))
        conn.commit()
    return code


def consume_link_code(code, tg_id, tg_username):
    """Возвращает ('ok', user) / ('bad', None) / ('taken', None)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM link_codes WHERE code=%s AND used_at IS NULL "
            "AND expires_at > now()", (code,)).fetchone()
        if not row:
            return "bad", None
        try:
            conn.execute("UPDATE users SET telegram_id=%s, telegram_username=%s WHERE id=%s",
                         (tg_id, tg_username, row["user_id"]))
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            return "taken", None
        conn.execute("UPDATE link_codes SET used_at=now() WHERE code=%s", (code,))
        user = conn.execute("SELECT * FROM users WHERE id=%s", (row["user_id"],)).fetchone()
        conn.commit()
    return "ok", user


def unlink_telegram(user_id):
    with connect() as conn:
        conn.execute("UPDATE users SET telegram_id=NULL, telegram_username=NULL WHERE id=%s",
                     (user_id,))
        conn.commit()


# --------------------------------------------------------- напоминания ----

def already_notified(user_id, event_key, kind):
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM notified_events WHERE user_id=%s AND event_key=%s "
                           "AND kind=%s", (user_id, event_key, kind)).fetchone()
    return row is not None


def record_notified(user_id, event_key, kind):
    """True — если запись создана нами (значит уведомление ещё не отправляли)."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO notified_events (user_id, event_key, kind) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING", (user_id, event_key, kind))
        conn.commit()
    return cur.rowcount > 0
