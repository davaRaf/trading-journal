# -*- coding: utf-8 -*-
"""
Аналіз дня: що людина побачила на графіку зранку і як воно відпрацювало.

По одному запису на день і на людину. Зберігаємо документом (JSON) з тієї
самої причини, що й стратегію: рівнів у кожного різна кількість, сценаріїв
теж, і набір полів ще змінюватиметься.

Окремо винесені в колонки тільки дві оцінки — «ринок пішов за планом» і
«тримався плану». За ними рахується статистика за місяць, і робити це
запитом по JSON щоразу не хочеться.

Скріни лежать поряд зі скрінами угод, але з іменем `dn<id людини>_...` —
власник видно з назви, чужий файл не віддасться.
"""
import base64
import os
import re
import time

from psycopg.types.json import Jsonb

import db
import filestore

SCHEMA = """
CREATE TABLE IF NOT EXISTS day_notes (
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  "date"     TEXT   NOT NULL,
  data       JSONB  NOT NULL DEFAULT '{}'::jsonb,
  match_mark TEXT   NOT NULL DEFAULT '',
  hold_mark  TEXT   NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, "date")
);
CREATE INDEX IF NOT EXISTS day_notes_user ON day_notes (user_id, "date" DESC);
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


def valid_date(d):
    return bool(DATE_RE.match(str(d or "")))


def get(user_id, date):
    init()
    with db.connect() as conn:
        row = conn.execute('SELECT data FROM day_notes WHERE user_id=%s AND "date"=%s',
                           (user_id, date)).fetchone()
    return (row or {}).get("data") or None


def put(user_id, date, data):
    init()
    marks = (data or {}).get("marks") or {}
    with db.connect() as conn:
        conn.execute(
            'INSERT INTO day_notes (user_id, "date", data, match_mark, hold_mark) '
            "VALUES (%s, %s, %s, %s, %s) "
            'ON CONFLICT (user_id, "date") DO UPDATE SET data=EXCLUDED.data, '
            "match_mark=EXCLUDED.match_mark, hold_mark=EXCLUDED.hold_mark, updated_at=now()",
            (user_id, date, Jsonb(data or {}),
             str(marks.get("match") or ""), str(marks.get("hold") or "")))


def drop(user_id, date):
    init()
    with db.connect() as conn:
        conn.execute('DELETE FROM day_notes WHERE user_id=%s AND "date"=%s', (user_id, date))


def days(user_id, limit=400):
    """Які дні вже розібрані — щоб позначити їх у календарі й гортати."""
    init()
    with db.connect() as conn:
        rows = conn.execute(
            'SELECT "date", match_mark, hold_mark FROM day_notes '
            'WHERE user_id=%s ORDER BY "date" DESC LIMIT %s', (user_id, limit)).fetchall()
    return [{"date": r["date"], "match": r["match_mark"], "hold": r["hold_mark"]} for r in rows]


def notes_since(user_id, since):
    """Розбори від дати й новіші — з них рахується підсумок за місяць."""
    init()
    with db.connect() as conn:
        rows = conn.execute(
            'SELECT "date", data, match_mark, hold_mark FROM day_notes '
            'WHERE user_id=%s AND "date" >= %s ORDER BY "date"', (user_id, since)).fetchall()
    return [{"date": r["date"], "data": r["data"] or {},
             "match": r["match_mark"], "hold": r["hold_mark"]} for r in rows]


# ----------------------------------------------------------- скріни ----

DATAURL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.S)
NAME_RE = re.compile(r"^dn(\d+)_[0-9a-z]+\.(png|jpg|jpeg|webp|gif)$", re.I)
MAX_BYTES = 6 * 1024 * 1024


def save_shot(user_id, data_url, shots_dir):
    m = DATAURL_RE.match(data_url or "")
    if not m:
        raise ValueError("не картинка")
    try:
        raw = base64.b64decode(m.group(2))
    except Exception:
        raise ValueError("зіпсований файл")
    if len(raw) > MAX_BYTES:
        raise ValueError("завеликий файл")
    ext = m.group(1).lower().replace("jpeg", "jpg")
    name = "dn%d_%x.%s" % (int(user_id), int(time.time() * 1000), ext)
    # у базі — надовго, на диску — кешем: у контейнерів файлова система
    # тимчасова, і після оновлення коду картинки зникли б
    try:
        filestore.put(name, raw)
    except Exception:
        pass
    try:
        with open(os.path.join(shots_dir, name), "wb") as f:
            f.write(raw)
    except OSError:
        pass
    return name


def owns_shot(user_id, name):
    m = NAME_RE.match(name or "")
    return bool(m) and m.group(1) == str(user_id)
