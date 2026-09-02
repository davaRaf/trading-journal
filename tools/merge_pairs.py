# -*- coding: utf-8 -*-
"""
Схлопывает разные написания одного инструмента в одно.

Из-за ручного ввода один и тот же индекс попадал в базу по-разному
(«NAS 100» и «NAS100», «GER40» и «GER 40»), и статистика делилась
между строками-близнецами. Здесь мы приводим их к одному написанию —
тому, которого в журнале больше.

Запуск:
    python tools/merge_pairs.py            # только показать, что изменится
    python tools/merge_pairs.py --apply    # записать в базу (сначала бэкап)

Перед записью в data/backup-pairs-<дата>.json складывается id, пользователь,
инструмент и дата каждой сделки — чтобы можно было вернуть как было.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# написание-дубль -> как правильно. Слева то, чего в журнале меньше.
MERGE = {
    "NAS100": "NAS 100",
    "GER 40": "GER40",
    "SP500":  "S&P 500",
}


def backup(conn):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(ROOT, "data", "backup-pairs-%s.json" % stamp)
    rows = conn.execute("SELECT id, user_id, pair, date FROM trades ORDER BY id").fetchall()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([dict(r) for r in rows], f, ensure_ascii=False, indent=1, default=str)
    return path, len(rows)


def main():
    apply = "--apply" in sys.argv
    with db.connect() as conn:
        print("Сейчас в базе:")
        for r in conn.execute(
                "SELECT pair, COUNT(*) n FROM trades GROUP BY pair ORDER BY n DESC").fetchall():
            print("  %-10s %s" % (r["pair"], r["n"]))

        print()
        print("Будет объединено:" if not apply else "Объединяю:")
        plan = []
        for bad, good in MERGE.items():
            n = conn.execute("SELECT COUNT(*) n FROM trades WHERE pair=%s", (bad,)).fetchone()["n"]
            if n:
                plan.append((bad, good, n))
                print("  %-10s -> %-10s %s сделок" % (bad, good, n))
        if not plan:
            print("  нечего объединять")
            return

        if not apply:
            print()
            print("Это только просмотр. Чтобы записать: python tools/merge_pairs.py --apply")
            return

        path, cnt = backup(conn)
        print()
        print("Бэкап: %s (%d строк)" % (path, cnt))

        total = 0
        for bad, good, _ in plan:
            total += conn.execute("UPDATE trades SET pair=%s WHERE pair=%s", (good, bad)).rowcount
        conn.commit()
        print("Обновлено сделок: %d" % total)

        print()
        print("Стало:")
        for r in conn.execute(
                "SELECT pair, COUNT(*) n FROM trades GROUP BY pair ORDER BY n DESC").fetchall():
            print("  %-10s %s" % (r["pair"], r["n"]))


if __name__ == "__main__":
    main()
