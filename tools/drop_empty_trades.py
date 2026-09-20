# -*- coding: utf-8 -*-
"""
Убирает из журнала строки, которые сделками не являются.

В таблицах Notion между сделками попадаются строки-разделители — заголовок
месяца вроде «1 Месяц». У них заполнено только название, а даты и результата
нет. Раньше импорт брал их наравне с настоящими сделками; теперь такие строки
он отсеивает (notion_public.looks_like_pair), но те, что уже попали в базу,
надо убрать руками — этим скриптом.

Условие: нет даты ИЛИ нет результата. Настоящая сделка без них не бывает.

Запуск:
    python tools/drop_empty_trades.py            # только показать, что найдено
    python tools/drop_empty_trades.py --apply    # удалить (сначала бэкап)

Перед удалением все найденные строки целиком складываются в
data/backup-empty-<дата>.json — чтобы можно было вернуть.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIND = """SELECT * FROM trades
          WHERE COALESCE(TRIM(date),'')='' OR COALESCE(TRIM(result),'')=''
          ORDER BY user_id, id"""


def main():
    apply = "--apply" in sys.argv
    with db.connect() as conn:
        rows = conn.execute(FIND).fetchall()
        if not rows:
            print("Пустых строк нет — журнал чистый.")
            return

        print("Найдено строк без даты или без результата: %d" % len(rows))
        for r in rows:
            print("  id=%s  користувач=%s  інструмент=%r  дата=%r  результат=%r"
                  % (r["id"], r["user_id"], r["pair"], r["date"], r["result"]))

        if not apply:
            print()
            print("Это только просмотр. Чтобы удалить: "
                  "python tools/drop_empty_trades.py --apply")
            return

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(ROOT, "data", "backup-empty-%s.json" % stamp)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([dict(r) for r in rows], f, ensure_ascii=False, indent=1, default=str)
        print()
        print("Бэкап: %s" % path)

        gone = 0
        for r in rows:
            gone += conn.execute("DELETE FROM trades WHERE id=%s AND user_id=%s",
                                 (r["id"], r["user_id"])).rowcount
        conn.commit()
        print("Удалено строк: %d" % gone)


if __name__ == "__main__":
    main()
