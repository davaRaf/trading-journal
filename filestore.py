# -*- coding: utf-8 -*-
"""
Скриншоты в базе.

Раньше картинки лежали только файлами в data/screenshots. На своём
компьютере это нормально, а на хостинге у контейнера файловая система
временная: обновил код — папка пустая, в сделках вместо графиков дырки.

Поэтому картинка теперь лежит в базе, а файл на диске остаётся кэшем:
если он есть — отдаём его (быстрее), если нет — достаём из базы и
попутно кладём обратно на диск.

Кто чей файл — решает не эта таблица, а те же проверки, что и раньше:
для сделок db.owns_screenshot, для ТС и разборов дня — имя файла с
номером владельца. Здесь только байты.
"""
import os

import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  name       TEXT PRIMARY KEY,
  mime       TEXT NOT NULL DEFAULT 'application/octet-stream',
  bytes      BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_ready = False

MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif"}


def init():
    global _ready
    if _ready:
        return
    with db.connect() as conn:
        conn.execute(SCHEMA)
    _ready = True


def mime_of(name):
    return MIME.get(str(name).rsplit(".", 1)[-1].lower(), "application/octet-stream")


def put(name, raw, mime=None):
    """Кладёт картинку в базу. Повторный вызов с тем же именем перезаписывает."""
    init()
    with db.connect() as conn:
        conn.execute("INSERT INTO files (name, mime, bytes) VALUES (%s, %s, %s) "
                     "ON CONFLICT (name) DO UPDATE SET mime=EXCLUDED.mime, bytes=EXCLUDED.bytes",
                     (name, mime or mime_of(name), raw))


def get(name):
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT mime, bytes FROM files WHERE name=%s", (name,)).fetchone()
    if not row:
        return None
    return row["mime"], bytes(row["bytes"])


def has(name):
    init()
    with db.connect() as conn:
        row = conn.execute("SELECT 1 FROM files WHERE name=%s", (name,)).fetchone()
    return row is not None


def delete(names):
    names = [n for n in (names or []) if n]
    if not names:
        return
    init()
    with db.connect() as conn:
        conn.execute("DELETE FROM files WHERE name = ANY(%s)", (list(names),))


def ingest(path, name=None):
    """Переносит файл с диска в базу. Файл на месте оставляем — он кэш."""
    if not os.path.exists(path):
        return False
    with open(path, "rb") as f:
        raw = f.read()
    if not raw:
        return False
    put(name or os.path.basename(path), raw)
    return True


def cache(shots_dir, name):
    """Достаёт картинку из базы на диск, чтобы дальше отдавать файлом.
    Возвращает путь или None."""
    got = get(name)
    if not got:
        return None
    path = os.path.join(shots_dir, os.path.basename(name))
    tmp = path + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(got[1])
        os.replace(tmp, path)
    except OSError:
        return None
    return path
