# -*- coding: utf-8 -*-
"""
Торгова стратегія людини: правила, за якими вона входить у ринок.

Лежить окремою таблицею, по одному запису на користувача, і зберігається
цілим документом (JSON). Розбивати на колонки не стали: набір полів у
кожного свій — хтось описує чотири таймфрейми, хтось два, хтось додає
свої випадки для беззбитку. Плюс форма ще змінюватиметься.

Скріни до правил кладуться в ту саму теку, що й скріни угод, але з
іменем `ts<id користувача>_...`. Так власника видно з самого імені файлу,
і чужий скрін не віддасться, навіть якщо хтось вгадає назву.
"""
import base64
import os
import re
import time

from psycopg.types.json import Jsonb

import db
import filestore

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
  user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  data       JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_ready = False


def init():
    """Таблиця створюється при першому зверненні: так модуль не залежить
    від того, чи згадали про нього в db.init()."""
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


def get(user_id):
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT data FROM strategies WHERE user_id=%s",
                           (user_id,)).fetchone()
    return (row or {}).get("data") or None


def put(user_id, data):
    init()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO strategies (user_id, data) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET data=EXCLUDED.data, updated_at=now()",
            (user_id, Jsonb(data or {})))


def clear(user_id):
    init()
    with db.connect() as conn:
        conn.execute("DELETE FROM strategies WHERE user_id=%s", (user_id,))


# ----------------------------------------------------------- скріни ----

DATAURL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.S)
NAME_RE = re.compile(r"^ts(\d+)_[0-9a-z]+\.(png|jpg|jpeg|webp|gif)$", re.I)
MAX_BYTES = 6 * 1024 * 1024


def save_shot(user_id, data_url, shots_dir):
    """Кладе картинку з data-URL у файл і повертає його ім'я."""
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
    name = "ts%d_%x.%s" % (int(user_id), int(time.time() * 1000), ext)
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


def used_files(data):
    """Усі імена файлів, на які посилається стратегія."""
    out = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("shot", "file") and isinstance(v, str) and v:
                    out.add(v)
                elif k == "shots" and isinstance(v, list):
                    # список імен файлів: скріни супроводу і приклади до моделей
                    for it in v:
                        if isinstance(it, str):
                            if it:
                                out.add(it)
                        else:
                            walk(it)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data or {})
    return out


def sweep(user_id, data, shots_dir):
    """Прибирає файли, на які стратегія більше не посилається.

    Людина може перекласти скрін тричі — старі копії інакше лишаться
    лежати назавжди.
    """
    keep = used_files(data)
    pref = "ts%d_" % int(user_id)
    try:
        names = os.listdir(shots_dir)
    except OSError:
        names = []
    gone = [n for n in names if n.startswith(pref) and n not in keep]
    for n in gone:
        try:
            os.remove(os.path.join(shots_dir, n))
        except OSError:
            pass
    try:
        filestore.delete(gone)
    except Exception:
        pass
