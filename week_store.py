# -*- coding: utf-8 -*-
"""
Аналіз тижня: що розмітили на вихідних — і як тиждень це відпрацював.

Те саме, що й аналіз дня (day_store), тільки запис один на тиждень. Поля
всередині ті самі, тому й тут документ (JSON): активів у тижні кілька, у
кожного свої скріни, рівні та сценарії.

Ключ тижня — дата понеділка (`2026-10-05`). Не номер ISO-тижня: з датою
вся арифметика лишається звичайною (±7 днів), у календарі тиждень
знаходиться без окремого перерахунку, а межа року не дає двох «тижнів 1».

Скріни спільні з розбором дня: той самий префікс `dn`, те саме /dnshot/.
Своє сховище тут нічого б не додало, а власника видно з імені файлу.
"""
import datetime
import re

from psycopg.types.json import Jsonb

import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS week_notes (
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  "week"     TEXT   NOT NULL,
  data       JSONB  NOT NULL DEFAULT '{}'::jsonb,
  match_mark TEXT   NOT NULL DEFAULT '',
  hold_mark  TEXT   NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, "week")
);
CREATE INDEX IF NOT EXISTS week_notes_user ON week_notes (user_id, "week" DESC);
"""

_ready = False


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_week(w):
    """Ключ тижня — існуюча дата, і саме понеділок.

    Перевіряємо день тижня, а не лише формат: інакше той самий тиждень
    ліг би в базу під сімома різними ключами, і друга правка не знайшла б
    першу.
    """
    w = str(w or "")
    if not DATE_RE.match(w):
        return False
    try:
        return datetime.date.fromisoformat(w).weekday() == 0
    except ValueError:
        return False


def monday(date):
    """Понеділок того тижня, у який потрапляє дата. Порожнє — None."""
    d = str(date or "")
    if not DATE_RE.match(d):
        return None
    try:
        day = datetime.date.fromisoformat(d)
    except ValueError:
        return None
    return (day - datetime.timedelta(days=day.weekday())).isoformat()


def get(user_id, week):
    init()
    with db.connect() as conn:
        row = conn.execute('SELECT data FROM week_notes WHERE user_id=%s AND "week"=%s',
                           (user_id, week)).fetchone()
    return (row or {}).get("data") or None


def put(user_id, week, data):
    init()
    marks = (data or {}).get("marks") or {}
    with db.connect() as conn:
        conn.execute(
            'INSERT INTO week_notes (user_id, "week", data, match_mark, hold_mark) '
            "VALUES (%s, %s, %s, %s, %s) "
            'ON CONFLICT (user_id, "week") DO UPDATE SET data=EXCLUDED.data, '
            "match_mark=EXCLUDED.match_mark, hold_mark=EXCLUDED.hold_mark, updated_at=now()",
            (user_id, week, Jsonb(data or {}),
             str(marks.get("match") or ""), str(marks.get("hold") or "")))


def drop(user_id, week):
    init()
    with db.connect() as conn:
        conn.execute('DELETE FROM week_notes WHERE user_id=%s AND "week"=%s', (user_id, week))


def weeks(user_id, limit=200):
    """Які тижні вже розібрані — щоб позначити їх у календарі й гортати."""
    init()
    with db.connect() as conn:
        rows = conn.execute(
            'SELECT "week", match_mark, hold_mark FROM week_notes '
            'WHERE user_id=%s ORDER BY "week" DESC LIMIT %s', (user_id, limit)).fetchall()
    return [{"week": r["week"], "match": r["match_mark"], "hold": r["hold_mark"]} for r in rows]


def notes_since(user_id, since):
    """Розбори тижнів від дати й новіші — з них збирається знімок за посиланням."""
    init()
    with db.connect() as conn:
        rows = conn.execute(
            'SELECT "week", data, match_mark, hold_mark FROM week_notes '
            'WHERE user_id=%s AND "week" >= %s ORDER BY "week"', (user_id, since)).fetchall()
    return [{"week": r["week"], "data": r["data"] or {},
             "match": r["match_mark"], "hold": r["hold_mark"]} for r in rows]
