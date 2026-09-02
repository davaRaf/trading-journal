# -*- coding: utf-8 -*-
"""
Перекладывает скриншоты из папки в базу.

Нужно один раз — когда картинки накопились файлами, а журнал переезжает
на хостинг: там файловая система у контейнера временная, а база нет.

Запуск (по строке подключения из окружения, то есть из .env):

    python tools/shots_to_db.py

Или явно указать, куда класть — например, в базу на хостинге:

    python tools/shots_to_db.py "postgresql://…"

Скрипт пропускает то, что уже в базе, так что повторный запуск безопасен.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if len(sys.argv) > 1:
    os.environ["DATABASE_URL"] = sys.argv[1]

import config  # noqa: E402
import db  # noqa: E402
import filestore  # noqa: E402

SHOTS = os.path.join(config.DATA_DIR, "screenshots")


def main():
    if not config.DATABASE_URL:
        print("не задан DATABASE_URL — заполни .env или передай строку аргументом")
        return 1

    names = sorted(n for n in os.listdir(SHOTS)
                   if os.path.isfile(os.path.join(SHOTS, n)) and not n.startswith("."))
    if not names:
        print("в папке нет картинок:", SHOTS)
        return 0

    size = sum(os.path.getsize(os.path.join(SHOTS, n)) for n in names)
    print("нашёл %d файлов, вместе %.1f МБ" % (len(names), size / 1024 / 1024))

    filestore.init()
    with db.connect() as conn:
        rows = conn.execute("SELECT name FROM files").fetchall()
    have = {r["name"] for r in rows}

    added = skipped = failed = 0
    for i, name in enumerate(names, 1):
        if name in have:
            skipped += 1
            continue
        try:
            if filestore.ingest(os.path.join(SHOTS, name), name):
                added += 1
            else:
                failed += 1
        except Exception as e:
            print("  %s — не вышло: %s" % (name, e))
            failed += 1
        if i % 100 == 0:
            print("  %d из %d" % (i, len(names)))

    print("положено %d, уже были %d, не вышло %d" % (added, skipped, failed))
    with db.connect() as conn:
        row = conn.execute("SELECT count(*) n, coalesce(sum(length(bytes)),0) b "
                           "FROM files").fetchone()
    print("в базе теперь: %d картинок, %.1f МБ" % (row["n"], row["b"] / 1024 / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
